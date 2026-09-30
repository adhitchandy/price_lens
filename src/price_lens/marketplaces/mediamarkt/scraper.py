from __future__ import annotations

import hashlib
import json
import random
import re
import tempfile
import time
from dataclasses import fields
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ProductRecord, ScrapeReport, utc_now

from .constants import (
    DOMAIN_TO_LANGUAGE_PATH,
    MEDIAMARKT_MARKETPLACES,
    UNAVAILABLE_MARKETPLACES,
)
from .parser import (
    landing_category_link,
    listing_state,
    next_page_url,
    parse_html,
    parse_product_detail,
)

RESULT_COLUMNS = [f.name for f in fields(ProductRecord)] + ["currency", "price", "link"]
LOAD_MORE = ('[data-test="mms-search-srp-loadmore"], [data-testid="mms-search-srp-loadmore"], '
             '[data-test*="load-more"], [data-test*="loadmore"], '
             '[data-testid*="load-more"], [data-testid*="loadmore"]')
MORE_LABEL = re.compile(
    r"weitere produkte|mehr produkte|load more|show more products|"
    r"(?:voir|afficher) (?:plus|davantage)|meer producten|toon meer|"
    r"(?:mostrar|ver|cargar) m[aá]s|(?:mostra|carica|vedi) (?:altri|pi[uù])|"
    r"(?:pokaż|pokaz|załaduj|wczytaj) (?:więcej|wiecej)|"
    r"további termék|több termék|daha fazla|mais produtos", re.IGNORECASE,
)
NEXT_LABEL = re.compile(
    r"^(?:next(?: page)?|weiter|nächste(?: seite)?|suivant(?:e)?|"
    r"volgende(?: pagina)?|siguiente|successiv[ao]|następna|következő|sonraki)(?:\s*[›»→])?$",
    re.IGNORECASE,
)
REJECT_LABELS = (
    "Alle ablehnen", "Alles ablehnen", "Ablehnen", "Nur notwendige", "Nur notwendige Cookies",
    "Nur erforderliche Cookies", "Reject all", "Reject", "Tout refuser",
    "Alles weigeren", "Alles afwijzen", "Rechazar todas", "Rechazar todo",
    "Rifiuta tutti", "Odrzuć wszystkie", "Összes elutasítása", "Tümünü reddet",
    "Rejeitar todos", "Denegar", "Denegar todo", "Rechazar", "Reddet", "Weigeren",
    "Rifiuta", "Odrzuć", "Elutasítás", "Refuser",
)

# Fallback labels when no direct reject button exists (e.g. MediaMarkt AT)
CONSENT_FALLBACK_LABELS = (
    "Alles zulassen", "Alle zulassen", "Alle akzeptieren", "Alles akzeptieren",
    "Zulassen", "Speichern", "Accept all", "Allow all", "Accepter tout",
    "Alles toestaan", "Aceptar todo", "Accetta tutti", "Aceptar", "Alles accepteren",
    "Accepteren", "Kabul et", "Tümünü kabul et", "Accetta", "Akceptuję", "Zaakceptuj wszystkie",
    "Összes elfogadása", "Elfogadom", "Tout accepter", "Accepter", "Akzeptieren",
)


class StorefrontError(RuntimeError):
    """Unsupported redirect or explicit site challenge: do not retry/bypass."""


def _firefox_options(headless):
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.set_preference("media.autoplay.default", 5)
    return options


def build_search_url(domain: str, term: str, page: int, language: str | None = None) -> str:
    language = language or DOMAIN_TO_LANGUAGE_PATH[domain]
    params = {"query": term}
    if page > 1:
        params["page"] = page
    return f"https://www.{domain}/{language}/search.html?{urlencode(params)}"


# Language-independent MediaMarkt/MediaWorld consent controls (same layer in every country),
# plus common CMPs. Order of preference: reject > save defaults (necessary only) > accept.
CONSENT_SELECTORS = (
    ("rejected", "#pwa-consent-layer-deny-all-button, [data-test='pwa-consent-layer-deny-all'], "
                 "#onetrust-reject-all-handler, [data-testid='uc-deny-all-button']"),
    ("saved", "[data-test='pwa-consent-layer-save-settings']"),
    ("accepted", "#pwa-consent-layer-accept-all-button, [data-test='pwa-consent-layer-accept-all'], "
                 "#onetrust-accept-btn-handler, [data-testid='uc-accept-all-button']"),
)


def _usable(button):
    try:
        return button.is_displayed() and button.is_enabled()
    except WebDriverException:
        return False


def _visible_consent_button(driver, exclude=()):
    for kind, selector in CONSENT_SELECTORS:
        if kind in exclude:
            continue
        if kind == "rejected":
            for label in REJECT_LABELS:
                for button in driver.find_elements(By.XPATH, f"//button[normalize-space(.)='{label}']"):
                    if _usable(button):
                        return kind, button
        for button in driver.find_elements(By.CSS_SELECTOR, selector):
            if _usable(button):
                return kind, button
        if kind == "accepted":
            for label in CONSENT_FALLBACK_LABELS:
                for button in driver.find_elements(By.XPATH, f"//button[normalize-space(.)='{label}']"):
                    if _usable(button):
                        return kind, button
    return None


def _handle_cookie_consent(driver, timeout=6):
    """Close the cookie layer; if a click does not close it, try the next-best control."""
    state = {"action": None, "tried": [], "clicked_at": 0.0}

    def click(current, button):
        try:
            button.click()
        except WebDriverException:
            # Overlays can intercept a native click; fall back to a JS click.
            current.execute_script("arguments[0].click();", button)
        state["clicked_at"] = time.monotonic()
        time.sleep(1.0)

    def handle(current):
        snapshot = _consent_snapshot(current)
        if not snapshot.get("blocked"):
            return state["action"] or False
        # Give the layer a moment to close after a click before trying something else.
        if state["tried"] and time.monotonic() - state["clicked_at"] < 2.5:
            return False
        if len(state["tried"]) >= 3:
            return False
        candidate = (_visible_consent_button(current, tuple(state["tried"])) if state["tried"]
                     else _visible_consent_button(current))
        if candidate is None and not state["tried"] and snapshot.get("button") is not None:
            candidate = (snapshot.get("kind") or "rejected", snapshot["button"])
        if candidate is None:
            return False
        state["action"], button = candidate
        state["tried"].append(candidate[0])
        click(current, button)
        return False

    try:
        return WebDriverWait(driver, max(timeout, 10), poll_frequency=0.5).until(handle)
    except TimeoutException:
        snapshot = _consent_snapshot(driver)
        if snapshot.get("blocked"):
            labels = list(dict.fromkeys(snapshot.get("labels", [])))
            raise StorefrontError("Cookie consent dialog did not close; collection stopped. "
                                  f"Visible controls: {labels}") from None
        return state["action"]


def _consent_snapshot(driver):
    all_allowed = list(REJECT_LABELS + CONSENT_FALLBACK_LABELS)
    return driver.execute_script("""
        const labels = new Set(arguments[0].map(s => s.toLocaleLowerCase()));
        const rejects = new Set(__REJECTS__.map(s => s.toLocaleLowerCase()));
        let kind = null;
        const visible = e => e.getClientRects().length > 0 &&
            getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
        const roots = [document]; let button = null, blocked = false; const texts = [];
        for (let i=0; i<roots.length; i++) {
            for (const e of roots[i].querySelectorAll('*')) {
                if (e.shadowRoot) roots.push(e.shadowRoot);
                if (!visible(e)) continue;
                if (e.matches('button, [role="button"], input[type="button"]')) {
                    const text = (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' ');
                    if (labels.has(text.toLocaleLowerCase()) && !e.disabled && !button) {
                        button = e;
                        kind = rejects.has(text.toLocaleLowerCase()) ? 'rejected' : 'accepted';
                    }
                }
                if (e.matches('#mms-consent-portal-container, #onetrust-banner-sdk, #usercentrics-root, [data-testid="uc-banner-content"], [role="dialog"], [aria-modal="true"]')) {
                    const content = (e.innerText || '').trim();
                    if (content && /cookie|consent|datenschutz|privatsph|privacy|çerez|sütik/i.test(content)) {
                        blocked = true;
                        for (const b of e.querySelectorAll('button, [role="button"]'))
                            texts.push((b.innerText || b.getAttribute('aria-label') || '').slice(0,150));
                    }
                }
            }
        }
        return {button, kind, blocked, labels: texts.slice(0,15)};
    """.replace("__REJECTS__", json.dumps(list(REJECT_LABELS))), all_allowed)


def _austrian_next_url(driver):
    """Verified from the supplied AT page-one/page-two HTML; preserve all query filters."""
    parts = urlsplit(driver.current_url)
    state = listing_state(driver.page_source)
    if (parts.hostname not in {"mediamarkt.at", "www.mediamarkt.at"}
            or parts.path != "/de/search.html" or state["total"] is None
            or state["loaded"] >= state["total"]):
        return None
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    try:
        page = int(query.get("page", "1"))
    except ValueError:
        return None
    query["page"] = str(page + 1)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _check_storefront(driver, domain):
    if urlsplit(driver.current_url).hostname not in {domain, f"www.{domain}"}:
        raise StorefrontError(f"Unexpected retailer/domain redirect: {driver.current_url}")
    body = driver.find_element(By.TAG_NAME, "body").text.lower()
    if any(s in body for s in (
        "access denied", "zugriff verweigert", "verify you are human",
        "pardon our interruption", "verify yourself", "checking your browser",
        "performing security verification", "verifying you are human",
        "überprüfen, ob sie ein mensch sind", "vérifiez que vous êtes humain",
        "verifica di essere umano", "verificando che tu sia umano",
        "controleer of je een mens bent",
    )) or any(element.is_displayed() for element in driver.find_elements(
        By.CSS_SELECTOR, "iframe[src*='captcha'], #captcha, #challenge-running, "
        "#challenge-stage, iframe[src*='challenges.cloudflare.com']"
    )):
        raise StorefrontError("Access restriction or verification challenge; stopped")


CHALLENGE_GRACE_SECONDS = 20


def _check_storefront_patiently(driver, domain, grace=CHALLENGE_GRACE_SECONDS):
    """Security pages ("performing security verification") often finish by themselves in a
    real browser. Wait passively for that; never interact with or work around the check."""
    deadline = time.monotonic() + grace
    while True:
        try:
            _check_storefront(driver, domain)
            return
        except StorefrontError as exc:
            if "verification challenge" not in str(exc) or time.monotonic() >= deadline:
                if "verification challenge" in str(exc):
                    raise StorefrontError(
                        f"Access restriction or verification challenge; stopped (still shown after "
                        f"{grace}s — the site is blocking automated browsing right now)") from None
                raise
            time.sleep(2)


def _navigate(driver, url, domain):
    driver.get(url)
    WebDriverWait(driver, 15).until(
        lambda current: current.execute_script("return document.readyState") in {"interactive", "complete"}
    )
    _check_storefront_patiently(driver, domain)
    action = _handle_cookie_consent(driver, timeout=15)
    _check_storefront(driver, domain)
    return action


def _start_search(driver, domain, term, language):
    # Submit the real form to preserve search -> category redirects and legacy routes.
    action = _navigate(driver, f"https://www.{domain}/", domain)
    if language in {"fr", "it"} and domain in {"mediamarkt.ch", "mediamarkt.be"}:
        _navigate(driver, f"https://www.{domain}/{language}/", domain)
    def visible_search(current):
        inputs = current.find_elements(
            By.CSS_SELECTOR, 'input[data-test="search-input"], input[data-testid="search-input"], '
            'form[role="search"] input, form[data-test="search-form"] input, input[name="query"]'
        )
        return next((item for item in inputs if item.is_displayed() and item.is_enabled()), False)
    try:
        search = WebDriverWait(driver, 12).until(visible_search)
    except TimeoutException:
        search = None
    if search:
        initial_url = driver.current_url
        search.clear()
        search.send_keys(term)
        search.send_keys(Keys.ENTER)
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.current_url != initial_url
                or d.find_elements(By.CSS_SELECTOR, '[data-test="mms-search-srp-productlist"]')
            )
        except TimeoutException:
            _navigate(driver, build_search_url(domain, term, 1, language), domain)
        _handle_cookie_consent(driver, timeout=1)
    else:
        _navigate(driver, build_search_url(domain, term, 1, language), domain)
    _follow_category_if_landing(driver, domain, term)
    return action


GRID_SELECTOR = '[data-test="mms-search-srp-productlist"], [data-testid="mms-search-srp-productlist"]'


def _follow_category_if_landing(driver, domain, term, wait=12):
    """If the search redirected to an editorial page without a product grid, open the
    best-matching category listed on that page (e.g. mediamarkt.nl 'Smartphone')."""
    try:
        WebDriverWait(driver, wait, poll_frequency=0.5).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, GRID_SELECTOR))
        return None
    except TimeoutException:
        pass
    link = landing_category_link(driver.page_source, driver.current_url, term)
    if link:
        _navigate(driver, link, domain)
    return link


def _row_key(row):
    return row.get("product_id") or row.get("product_url") or row.get("product_name")


class BatchRows(list):
    def __init__(self, rows, *, complete=True, state=None):
        super().__init__(rows)
        self.complete = complete
        self.state = state or {}


def _scroll_listing(driver, *, reset=False):
    """Bring lazy grid slots into view so MediaMarkt renders them.

    MediaMarkt renders only the first cards; the rest are empty ``<li>`` placeholders that
    fill in once they intersect the viewport. Jump straight to the first empty placeholder
    (fast, independent of how slow each poll is) and only report "bottom" once no
    placeholders remain and the end of the grid has been reached.
    """
    return driver.execute_script("""
        const grid = document.querySelector('[data-test="mms-search-srp-productlist"], [data-testid="mms-search-srp-productlist"]');
        if (!grid) return false;
        const rect = grid.getBoundingClientRect();
        const top = Math.max(0, window.scrollY + rect.top - 100);
        if (arguments[0]) {window.scrollTo(0, top); return false;}
        const items = grid.querySelectorAll(':scope > ul > li, :scope > div > ul > li, :scope > ol > li');
        for (const item of items) {
            const empty = !item.querySelector('[data-test], [data-testid], img, a')
                && !(item.innerText || '').trim();
            // Ad slots can stay empty forever: after a few visits, treat them as done.
            if (empty && (+item.dataset.piVisits || 0) < 3) {
                item.dataset.piVisits = (+item.dataset.piVisits || 0) + 1;
                item.scrollIntoView({block: 'center'});
                window.dispatchEvent(new Event('scroll'));
                return false;
            }
        }
        const bottom = Math.max(top, window.scrollY + rect.bottom - window.innerHeight + 100);
        const limit = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        const target = Math.min(bottom, limit);
        if (window.scrollY >= target - 5) return true;
        const before = window.scrollY;
        window.scrollTo(0, Math.min(target, window.scrollY + window.innerHeight));
        window.dispatchEvent(new Event('scroll'));
        // Sticky footers/layout can make the target unreachable: no movement = bottom.
        return window.scrollY <= before + 1;
    """, reset)


def _wait_for_new_rows(driver, domain, term, rules, seen, timeout=45):
    collected = {}
    last_signature = None
    last_change = time.monotonic()
    started = last_change
    reset = True
    last_state = {}

    def ready(current):
        nonlocal last_signature, last_change, reset, last_state
        _check_storefront(current, domain)
        html = current.page_source
        last_state = listing_state(html)
        if not last_state["grid_present"] or not last_state["card_count"]:
            return False  # Do not collect homepage recommendations while search is loading.
        rows = parse_html(html, domain, term, rules)
        for row in rows:
            if _row_key(row) not in seen:
                collected[_row_key(row)] = row
        signature = tuple(sorted((str(key), str(row.get("price_value")), row["product_name"])
                                 for key, row in collected.items()))
        now = time.monotonic()
        if signature != last_signature:
            last_change, last_signature = now, signature
        bottom = _scroll_listing(current, reset=reset)
        reset = False
        expected = last_state["loaded"]
        enough = (expected is None or len(seen | set(collected)) >= expected) and len(rows) >= last_state["card_count"]
        # An explicit reached counter is stronger evidence than scroll position.
        # Sticky overlays/layout shifts can prevent scrollY ever reaching our target.
        traversal_complete = (expected is not None and enough) or bottom
        last_state.update({"parsed_cards": len(rows), "collected_unique": len(collected),
                           "scroll_bottom": bool(bottom), "counter_reached": expected is not None and enough,
                           "stable_seconds": round(now - last_change, 2)})
        if (collected and traversal_complete and enough and now - last_change >= 2.5
                and now - started >= 5):
            return BatchRows(collected.values(), state=last_state)
        return False
    try:
        return WebDriverWait(driver, timeout, poll_frequency=0.5).until(ready)
    except TimeoutException as exc:
        if collected:
            return BatchRows(collected.values(), complete=False, state=last_state)
        raise TimeoutException(
            f"No new listing products after {timeout}s; grid_present={last_state.get('grid_present')}; "
            f"counter={last_state.get('counter')!r}; URL={driver.current_url}"
        ) from exc


def _pagination_control(driver):
    for button in driver.find_elements(By.CSS_SELECTOR, LOAD_MORE):
        if button.is_displayed() and button.is_enabled() and button.get_attribute("aria-disabled") != "true":
            return button
    for button in driver.find_elements(By.CSS_SELECTOR, 'button, a[role="button"], nav a'):
        label = " ".join((button.text or button.get_attribute("aria-label") or "").split())
        if (MORE_LABEL.search(label) or NEXT_LABEL.fullmatch(label)) and (
            button.is_displayed() and button.is_enabled()
            and button.get_attribute("aria-disabled") != "true"
        ):
            return button
    return False


def _pagination_diagnostics(driver):
    try:
        return _read_pagination_diagnostics(driver)
    except WebDriverException as exc:
        return {"diagnostic_error": str(exc)}


def _read_pagination_diagnostics(driver):
    return {
        "url": driver.current_url,
        "title": driver.title,
        "listing_state": listing_state(driver.page_source),
        "next_url": next_page_url(driver.page_source, driver.current_url),
        "controls": [
            {"text": b.text[:150], "test_id": b.get_attribute("data-test"),
             "aria_label": b.get_attribute("aria-label"), "enabled": b.is_enabled()}
            for b in driver.find_elements(By.CSS_SELECTOR, 'button, nav a')
            if MORE_LABEL.search(b.text or "") or NEXT_LABEL.fullmatch(b.text or "")
        ][:20],
    }


def _advance_page(driver, domain):
    _handle_cookie_consent(driver, timeout=5)
    # Some country storefronts render the footer control only after scrolling.
    # The preceding batch swept the grid; don't jump past an intersection-triggered footer.
    try:
        button = WebDriverWait(driver, 15, poll_frequency=0.5).until(_pagination_control)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
        button.click()
        return "load_more"
    except TimeoutException:
        pass
    next_url = next_page_url(driver.page_source, driver.current_url) or _austrian_next_url(driver)
    if next_url:
        _navigate(driver, next_url, domain)
        return "next_link"
    return None


def _deduplicate(frame):
    return frame.drop_duplicates(["marketplace", "product_url"]) if not frame.empty else frame


def _save_diagnostics(driver, directory, domain, term, page):
    if directory is None:
        return {}
    digest = hashlib.sha256(f"{domain}|{term}|{page}|{time.time_ns()}".encode()).hexdigest()[:12]
    # Keep filenames short enough for legacy Windows MAX_PATH configurations.
    base = Path(directory).resolve() / digest
    if len(str(base)) + 5 >= 240:
        base = Path(tempfile.gettempdir()) / "pi-diagnostics" / digest
    files = {}
    try:
        base.parent.mkdir(parents=True, exist_ok=True)
        html = Path(str(base) + ".html")
        html.write_text(driver.page_source, encoding="utf-8")
        files["html"] = str(html.resolve())
        screenshot = Path(str(base) + ".png")
        if driver.save_screenshot(str(screenshot)):
            files["screenshot"] = str(screenshot.resolve())
    except (OSError, WebDriverException) as exc:
        files["error"] = str(exc)
    return files


class MediaMarktScraper:
    def __init__(self, driver_factory=None):
        self.driver_factory = driver_factory or webdriver.Firefox

    def search_with_report(
        self, search_config, marketplaces, *, headless=True, delay=(1.5, 3.5),
        pages=1, retries=2, enrich_details=False, max_detail_products=None,
        languages=None, log=None, progress=None, diagnostics_dir=None, max_products=None,
    ):
        unknown = set(marketplaces) - set(MEDIAMARKT_MARKETPLACES)
        if unknown:
            raise ValueError(f"Unsupported MediaMarkt domains: {sorted(unknown)}")
        log = log or (lambda _: None)
        progress = progress or (lambda _: None)
        report = ScrapeReport(platform="mediamarkt", pages_requested=pages)
        rows = []
        driver = None
        try:
            for domain in marketplaces:
                if domain in UNAVAILABLE_MARKETPLACES:
                    report.failures.append({
                        "marketplace": domain, "stage": "storefront",
                        "error": UNAVAILABLE_MARKETPLACES[domain], "status": "unavailable",
                    })
                    log(f"{domain}: {UNAVAILABLE_MARKETPLACES[domain]}")
                    continue
                if driver is None:
                    driver = self.driver_factory(options=_firefox_options(headless))
                    driver.set_page_load_timeout(45)
                for term, rules in search_config.items():
                    seen = set()
                    stop = False
                    action = None
                    for page in range(1, pages + 1):
                        report.pages_attempted += 1
                        fresh = None
                        mode = "initial"
                        error = ""
                        # Capture before clicking: the browser URL may advance before cards
                        # render. Reading rel=next afterwards could skip the missing batch.
                        fallback_url = ((next_page_url(driver.page_source, driver.current_url) or _austrian_next_url(driver))
                                        if page > 1 else None)
                        advance_started = False
                        for attempt in range(retries + 1):
                            try:
                                if page == 1:
                                    action = _start_search(
                                        driver, domain, term, (languages or {}).get(domain)
                                    )
                                else:
                                    # First check whether the previous timed-out click finished.
                                    if not advance_started:
                                        state = listing_state(driver.page_source)
                                        if state["total"] is not None and state["loaded"] >= state["total"]:
                                            log(f"{domain} | {term}: end of results ({state['counter']})")
                                            report.events.append({"marketplace": domain, "search_term": term,
                                                                  "page": page, "status": "end_of_results"})
                                            stop = True
                                            break
                                        mode = _advance_page(driver, domain)
                                        advance_started = mode is not None
                                    if mode is None:
                                        raise TimeoutException(
                                            f"No usable next-page control/link; counter={state['counter']!r}; "
                                            f"URL={driver.current_url}. Remaining requested batches unverified."
                                        )
                                try:
                                    fresh = _wait_for_new_rows(driver, domain, term, rules, seen)
                                except TimeoutException:
                                    # Client-side handlers can fail outside DE. Use the site's own
                                    # next URL as a fallback, preserving category, query and filters.
                                    if page == 1 or not fallback_url:
                                        raise
                                    _navigate(driver, fallback_url, domain)
                                    mode = "next_link_after_stalled_click"
                                    fresh = _wait_for_new_rows(driver, domain, term, rules, seen)
                                time.sleep(random.uniform(*delay))
                                break
                            except StorefrontError as exc:
                                error = str(exc)
                                stop = True
                                break
                            except (TimeoutException, WebDriverException) as exc:
                                error = (f"{type(exc).__name__}: {exc}; batch={page}; "
                                         f"URL={driver.current_url}")
                                fresh = None
                                if attempt < retries:
                                    time.sleep(min(2 ** attempt, 8))
                        if fresh:
                            complete = getattr(fresh, "complete", True)
                            batch_state = getattr(fresh, "state", {})
                            fresh = list({_row_key(r): r for r in fresh}.values())
                            seen.update(_row_key(r) for r in fresh)
                            for row in fresh:
                                row["collection_page"] = page
                                row["collection_complete"] = complete
                            rows.extend(fresh)
                            report.pages_succeeded += int(complete)
                            report.events.append({
                                "marketplace": domain, "search_term": term, "page": page,
                                "status": "succeeded" if complete else "partial", "listings": len(fresh),
                                "listing_state": batch_state,
                                "new_products": len(fresh), "unique_products_so_far": len(seen),
                                "pagination_method": mode, "attempts_used": attempt + 1,
                                "consent_action": action, "final_url": driver.current_url,
                            })
                            log(f"{domain} | {term} | batch {page}: {len(fresh)} new products"
                                + ("" if complete else " (PARTIAL: grid did not finish loading)"))
                            if not complete:
                                report.failures.append({
                                    "marketplace": domain, "search_term": term, "page": page,
                                    "stage": "grid_loading", "error": "Grid never settled or advertised count not reached",
                                    "listing_state": batch_state,
                                    "diagnostic_files": _save_diagnostics(driver, diagnostics_dir, domain, term, page),
                                })
                                stop = True
                        elif error:
                            report.failures.append({
                                "marketplace": domain, "search_term": term, "page": page,
                                "stage": "pagination" if page > 1 else "search",
                                "error": error, "final_url": driver.current_url,
                                "unique_products_so_far": len(seen),
                                "diagnostics": _pagination_diagnostics(driver),
                                "diagnostic_files": _save_diagnostics(driver, diagnostics_dir, domain, term, page),
                            })
                            stop = True
                            log(f"{domain} | {term}: stopped; {error}")
                        progress(min(1, report.pages_succeeded / max(
                            1, pages * len(search_config) * len(marketplaces)
                        )))
                        if max_products and not stop and len(seen) >= max_products:
                            log(f"{domain} | {term}: target reached ({len(seen)}/{max_products} products)")
                            stop = True
                        if stop:
                            break
            raw = pd.DataFrame(rows).reindex(columns=RESULT_COLUMNS + ["collection_page", "collection_complete"])
            if enrich_details and not raw.empty:
                self._enrich(driver, raw, max_detail_products, retries, delay, report)
            report.listings_collected = len(raw)
            report.unique_listings = len(_deduplicate(raw))
            report.duplicate_count = len(raw) - report.unique_listings
            report.missing_price_count = int(raw["price_value"].isna().sum())
            report.status = (
                "failed" if not rows else
                "completed_with_errors" if report.failures else "completed"
            )
            report.finished_at = utc_now()
            progress(1.0)
            return ScrapeOutcome(raw, report)
        finally:
            if driver:
                driver.quit()

    def _enrich(self, driver, frame, limit, retries, delay, report):
        cache = {}
        for index, row in frame.iterrows():
            url = row["product_url"]
            if not url:
                continue
            if url not in cache:
                if limit is not None and len(cache) >= limit:
                    continue
                cache[url] = {}
                for attempt in range(retries + 1):
                    try:
                        _navigate(driver, url, row["marketplace"])
                        detail = WebDriverWait(driver, 15).until(
                            lambda d, market=row["marketplace"]:
                                parse_product_detail(d.page_source, market) or False
                        )
                        if detail.get("product_id") != row["product_id"]:
                            raise StorefrontError("Detail redirected to a different product")
                        cache[url] = detail
                        time.sleep(random.uniform(*delay))
                        break
                    except (StorefrontError, WebDriverException) as exc:
                        if isinstance(exc, StorefrontError) or attempt == retries:
                            report.failures.append({
                                "stage": "detail_enrichment", "product_url": url,
                                "marketplace": row["marketplace"], "error": str(exc),
                            })
                            break
            for key, value in cache[url].items():
                if value is not None:
                    frame.at[index, key] = value

    def search(self, search_config, marketplaces, **kwargs):
        return _deduplicate(
            self.search_with_report(search_config, marketplaces, **kwargs).raw_products
        ).reset_index(drop=True)


def run_scrape(search_config, selected_domains, headless, delay, log_fn, progress_fn, **kwargs):
    return MediaMarktScraper().search(
        search_config, selected_domains, headless=headless, delay=delay,
        log=log_fn, progress=progress_fn, **kwargs,
    )
