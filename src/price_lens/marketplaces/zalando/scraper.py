from __future__ import annotations

import random
import time
import urllib.parse
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from price_lens.core.budget import collected_count, per_audience_target
from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport, utc_now

from .parser import (
    discover_audience_paths,
    parse_html,
    parse_product_detail,
    search_audience_path,
)

LogFunction = Callable[[str], None]
ProgressFunction = Callable[[float], None]

RESULT_COLUMNS = [
    "platform",
    "marketplace",
    "product_type",
    "search_term",
    "origin_country",
    "audience",
    "brand",
    "product_name",
    "product_id",
    "currency_code",
    "currency_symbol",
    "currency",
    "price_text",
    "price",
    "price_value",
    "price_usd",
    "rating",
    "review_count",
    "sponsored",
    "seller",
    "condition",
    "shipping_price_text",
    "shipping_price_value",
    "buying_format",
    "color",
    "availability",
    "image_url",
    "detail_enriched",
    "product_url",
    "link",
    "scraped_at",
]

COOKIE_ACCEPT_SELECTOR = (
    "button[data-testid='uc-accept-all-button'], "
    "button[data-testid='consent-banner-accept'], "
    "button[id*='accept-all'], "
    "#uc-btn-accept-banner"
)


def _firefox_options(headless: bool) -> Options:
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.set_preference(
        "general.useragent.override",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    options.set_preference("permissions.default.image", 2)
    options.set_preference("media.autoplay.default", 5)
    return options


def build_search_url(
    domain: str,
    term: str,
    page: int,
    audience: str,
    audience_url: str | None = None,
) -> str:
    params: dict[str, str | int] = {"q": term}
    if page > 1:
        params["p"] = page
    base = audience_url or f"https://www.{domain}/{audience}/"
    parts = urlsplit(base)
    return urlunsplit(
        (parts.scheme or "https", parts.netloc, parts.path, urllib.parse.urlencode(params), "")
    )


def _search_audiences(rules: list[dict]) -> tuple[str, ...]:
    audiences = dict.fromkeys(
        audience for rule in rules for audience in rule.get("audiences", [])
    )
    return tuple(audiences) or ("men",)


def _accept_cookie_banner(driver) -> bool:
    try:
        button = WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, COOKIE_ACCEPT_SELECTOR))
        )
        button.click()
        return True
    except (TimeoutException, WebDriverException):
        return False


def _load_page(driver, url: str, *, check_consent: bool) -> bool:
    driver.get(url)
    accepted = _accept_cookie_banner(driver) if check_consent else False
    if accepted:
        driver.get(url)
    WebDriverWait(driver, 12).until(
        lambda current: current.execute_script("return document.readyState") == "complete"
    )
    return accepted


def _discover_storefront_routes(driver, domain: str) -> tuple[dict[str, str], bool, str]:
    homepage = f"https://www.{domain}/"
    accepted = _load_page(driver, homepage, check_consent=True)
    WebDriverWait(driver, 12).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="genderLink"] a[href]')
        )
    )
    paths = discover_audience_paths(driver.page_source)
    if not paths:
        raise TimeoutException("Zalando audience links could not be discovered")
    final_homepage = driver.current_url
    routes = {
        audience: urljoin(
            final_homepage, search_audience_path(domain, audience, path)
        )
        for audience, path in paths.items()
    }
    return routes, accepted, final_homepage


def _block_reason(driver) -> str | None:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
    except WebDriverException:
        return "page body unavailable"
    signals = {
        "captcha": "captcha",
        "verify you are human": "verification challenge",
        "access denied": "access denied",
        "unusual traffic": "automated-traffic challenge",
    }
    return next((reason for signal, reason in signals.items() if signal in body), None)


def _deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    with_id = df[df["product_id"].notna()].drop_duplicates(
        subset=["marketplace", "product_id"], keep="first"
    )
    without_id = df[df["product_id"].isna()].drop_duplicates(
        subset=["marketplace", "product_name", "price_value"], keep="first"
    )
    return pd.concat([with_id, without_id], ignore_index=True)


class ZalandoScraper:
    """Zalando collector using rendered search cards and optional detail enrichment."""

    def __init__(self, driver_factory: Callable | None = None):
        self.driver_factory = driver_factory or webdriver.Firefox

    def search_with_report(
        self,
        search_config: dict,
        marketplaces: list[str],
        *,
        headless: bool = True,
        delay: tuple[float, float] = (1.5, 3.5),
        pages: int = 1,
        retries: int = 2,
        enrich_details: bool = False,
        max_detail_products: int | None = None,
        log: LogFunction | None = None,
        progress: ProgressFunction | None = None,
        max_products: int | None = None,
    ) -> ScrapeOutcome:
        log_fn = log or (lambda _message: None)
        progress_fn = progress or (lambda _value: None)
        report = ScrapeReport(platform="zalando", pages_requested=pages)
        driver = self.driver_factory(options=_firefox_options(headless))
        try:
            try:
                driver.maximize_window()
            except WebDriverException:
                pass
            rows: list[dict] = []
            searches_per_marketplace = sum(
                len(_search_audiences(rules)) for rules in search_config.values()
            )
            total_pages = max(1, searches_per_marketplace * len(marketplaces) * pages)
            completed_pages = 0
            consent_checked: set[str] = set()

            for domain in marketplaces:
                log_fn(f"🌍 Scraping domain: **{domain}**")
                routes: dict[str, str] = {}
                discovery_error = ""
                storefront_url = ""
                for discovery_attempt in range(1, retries + 2):
                    try:
                        routes, accepted, storefront_url = _discover_storefront_routes(
                            driver, domain
                        )
                        consent_checked.add(domain)
                        route_summary = ", ".join(
                            f"{audience}={urlsplit(url).path}"
                            for audience, url in routes.items()
                        )
                        log_fn(f"  🧭 Storefront routes: {route_summary}")
                        report.events.append(
                            {
                                "marketplace": domain,
                                "stage": "audience_route_discovery",
                                "status": "succeeded",
                                "storefront_url": storefront_url,
                                "audience_routes": routes,
                                "consent_initialized": accepted,
                            }
                        )
                        break
                    except (TimeoutException, WebDriverException) as exc:
                        discovery_error = f"{exc.__class__.__name__}: {exc}"
                        if discovery_attempt <= retries:
                            time.sleep(min(2 ** (discovery_attempt - 1), 8))
                if not routes:
                    report.failures.append(
                        {
                            "marketplace": domain,
                            "stage": "audience_route_discovery",
                            "error": discovery_error,
                            "requested_url": f"https://www.{domain}/",
                            "final_url": driver.current_url,
                        }
                    )
                    log_fn("  ⚠️ Could not discover this storefront's audience routes")
                    completed_pages += searches_per_marketplace * pages
                    progress_fn(completed_pages / total_pages)
                    continue
                for term, rules in search_config.items():
                    audience_list = _search_audiences(rules)
                    audience_target = per_audience_target(max_products, len(audience_list))
                    for audience in audience_list:
                        log_fn(f"  🔍 Search: **{term}** · audience: **{audience}**")
                        for page in range(1, pages + 1):
                            report.pages_attempted += 1
                            url = build_search_url(
                                domain, term, page, audience, routes[audience]
                            )
                            page_rows: list[dict] | None = None
                            last_error = "unknown failure"
                            final_url = ""
                            accepted = False
                            successful_attempt = 0
                            for attempt in range(1, retries + 2):
                                try:
                                    accepted = _load_page(
                                        driver,
                                        url,
                                        check_consent=domain not in consent_checked,
                                    ) or accepted
                                    consent_checked.add(domain)
                                    final_url = driver.current_url
                                    reason = _block_reason(driver)
                                    if reason:
                                        raise TimeoutException(reason)
                                    WebDriverWait(driver, 15).until(
                                        EC.presence_of_element_located(
                                            (
                                                By.CSS_SELECTOR,
                                                "article h3, article a[href$='.html']",
                                            )
                                        )
                                    )
                                    time.sleep(random.uniform(*delay))
                                    page_rows = parse_html(
                                        driver.page_source, domain, term, rules, audience
                                    )
                                    if not page_rows:
                                        raise TimeoutException(
                                            "Product cards loaded but were not parsed"
                                        )
                                    successful_attempt = attempt
                                    break
                                except (TimeoutException, WebDriverException) as exc:
                                    last_error = f"{exc.__class__.__name__}: {exc}"
                                    if attempt <= retries:
                                        wait_seconds = min(2 ** (attempt - 1), 8)
                                        log_fn(
                                            f"    ↻ Page {page}, attempt {attempt} failed; "
                                            f"retrying in {wait_seconds}s"
                                        )
                                        time.sleep(wait_seconds)

                            if page_rows is None:
                                report.failures.append(
                                    {
                                        "marketplace": domain,
                                        "search_term": term,
                                        "audience": audience,
                                        "audience_path": urlsplit(url).path,
                                        "page": page,
                                        "error": last_error,
                                        "requested_url": url,
                                        "final_url": final_url,
                                    }
                                )
                                log_fn(
                                    f"    ⚠️ Page {page} failed after "
                                    f"{retries + 1} attempt(s)"
                                )
                            else:
                                rows.extend(page_rows)
                                report.pages_succeeded += 1
                                report.events.append(
                                    {
                                        "marketplace": domain,
                                        "search_term": term,
                                        "audience": audience,
                                        "audience_path": urlsplit(url).path,
                                        "page": page,
                                        "listings": len(page_rows),
                                        "status": "succeeded",
                                        "requested_url": url,
                                        "final_url": final_url,
                                        "final_domain": urlsplit(final_url).netloc.removeprefix(
                                            "www."
                                        ),
                                        "currency_codes": sorted(
                                            {row["currency_code"] for row in page_rows}
                                        ),
                                        "attempts_used": successful_attempt,
                                        "consent_initialized": accepted,
                                    }
                                )
                                log_fn(f"    ✅ Page {page}: {len(page_rows)} products found")
                            completed_pages += 1
                            progress_fn(completed_pages / total_pages)
                            if audience_target:
                                have = collected_count(rows, domain, term, audience)
                                if have >= audience_target:
                                    log_fn(f"    🎯 Target reached: {have}/{audience_target} ({audience})")
                                    break
                                if not page_rows:
                                    log_fn(f"    ⏹ Stopping after page {page} ({have} products)")
                                    break

            raw = pd.DataFrame(rows, columns=RESULT_COLUMNS)
            raw = self._enrich(
                driver,
                raw,
                retries=retries,
                delay=delay,
                limit=max_detail_products,
                report=report,
                log=log_fn,
            ) if enrich_details and not raw.empty else raw
            unique = _deduplicate(raw)
            report.listings_collected = len(raw)
            report.unique_listings = len(unique)
            report.duplicate_count = len(raw) - len(unique)
            report.missing_price_count = int(raw["price_value"].isna().sum())
            report.finished_at = utc_now()
            report.status = (
                "failed"
                if report.pages_succeeded == 0
                else "completed_with_errors"
                if report.failures
                else "completed"
            )
            return ScrapeOutcome(raw.reset_index(drop=True), report)
        finally:
            driver.quit()

    def _enrich(self, driver, df, *, retries, delay, limit, report, log):
        indexes = list(df.index[:limit]) if limit is not None else list(df.index)
        log(f"  🔎 Enriching {len(indexes)} product detail page(s)")
        succeeded = 0
        for number, index in enumerate(indexes, start=1):
            url = df.at[index, "product_url"]
            last_error = ""
            detail: dict = {}
            for attempt in range(retries + 1):
                try:
                    driver.get(url)
                    WebDriverWait(driver, 12).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "script[type='application/ld+json']")
                        )
                    )
                    time.sleep(random.uniform(*delay))
                    detail = parse_product_detail(driver.page_source, df.at[index, "marketplace"])
                    if not detail:
                        raise TimeoutException("ProductGroup JSON-LD was not found")
                    break
                except (TimeoutException, WebDriverException) as exc:
                    last_error = f"{exc.__class__.__name__}: {exc}"
                    if attempt < retries:
                        time.sleep(min(2**attempt, 8))
            if detail:
                for key, value in detail.items():
                    if value is not None:
                        df.at[index, key] = value
                succeeded += 1
            else:
                report.failures.append(
                    {"marketplace": df.at[index, "marketplace"], "product_url": url,
                     "stage": "detail_enrichment", "error": last_error}
                )
            log(f"    Detail {number}/{len(indexes)}: {'✅' if detail else '⚠️'}")
        report.events.append(
            {"stage": "detail_enrichment", "requested": len(indexes), "succeeded": succeeded}
        )
        return df

    def search(self, search_config: dict, marketplaces: list[str], **kwargs) -> pd.DataFrame:
        outcome = self.search_with_report(search_config, marketplaces, **kwargs)
        return _deduplicate(outcome.raw_products).reset_index(drop=True)


def run_scrape(
    search_config,
    selected_domains,
    headless,
    delay,
    log_fn,
    progress_fn,
    pages=1,
    retries=2,
    enrich_details=False,
    max_detail_products=None,
):
    return ZalandoScraper().search(
        search_config,
        selected_domains,
        headless=headless,
        delay=delay,
        log=log_fn,
        progress=progress_fn,
        pages=pages,
        retries=retries,
        enrich_details=enrich_details,
        max_detail_products=max_detail_products,
    )
