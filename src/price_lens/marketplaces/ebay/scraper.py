from __future__ import annotations

import random
import time
import urllib.parse
from collections.abc import Callable
from urllib.parse import urlsplit

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from price_lens.core.budget import collected_count
from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport, utc_now

from .parser import parse_html

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
    options.set_preference("permissions.default.stylesheet", 2)
    options.set_preference("gfx.downloadable_fonts.enabled", False)
    options.set_preference("media.autoplay.default", 5)
    return options


COOKIE_ACCEPT_SELECTOR = (
    "#gdpr-banner-accept, "
    "button[data-testid='gdpr-banner-accept'], "
    "button[data-testid='consent-banner-accept']"
)


def build_search_url(domain: str, term: str, page: int) -> str:
    params: dict[str, str | int] = {
        "_nkw": term,
        "_sacat": 0,
        "_from": "R40",
    }
    if page > 1:
        params["_pgn"] = page
    return f"https://www.{domain}/sch/i.html?{urllib.parse.urlencode(params)}"


def _accept_cookie_banner(driver) -> bool:
    try:
        button = WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, COOKIE_ACCEPT_SELECTOR))
        )
        button.click()
        return True
    except (TimeoutException, WebDriverException):
        return False


def _prepare_search_page(
    driver,
    url: str,
    log_fn: LogFunction,
    check_consent: bool,
) -> bool:
    driver.get(url)
    consent_accepted = _accept_cookie_banner(driver) if check_consent else False
    if consent_accepted:
        log_fn("    🍪 Initialised this domain's consent session")
        try:
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, COOKIE_ACCEPT_SELECTOR))
            )
        except TimeoutException:
            pass
        # Consent handling can asynchronously reload or replace the results DOM.
        # Reload the exact intended search so this does not consume a retry.
        driver.get(url)
    WebDriverWait(driver, 10).until(
        lambda current_driver: current_driver.execute_script(
            "return document.readyState"
        )
        == "complete"
    )
    return consent_accepted


def _block_reason(driver) -> str | None:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
    except WebDriverException:
        return "page body unavailable"
    signals = {
        "security measure": "security measure",
        "verify yourself": "verification challenge",
        "captcha": "captcha",
        "pardon our interruption": "automated-traffic challenge",
    }
    for signal, reason in signals.items():
        if signal in body:
            return reason
    return None


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


class EbayScraper:
    """eBay collector conforming to the common marketplace result schema."""

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
        log: LogFunction | None = None,
        progress: ProgressFunction | None = None,
        max_products: int | None = None,
    ) -> ScrapeOutcome:
        log_fn = log or (lambda _message: None)
        progress_fn = progress or (lambda _value: None)
        report = ScrapeReport(platform="ebay", pages_requested=pages)
        driver = self.driver_factory(options=_firefox_options(headless))
        try:
            try:
                driver.maximize_window()
            except WebDriverException:
                pass

            rows: list[dict] = []
            terms = list(search_config)
            total_pages = max(1, len(terms) * len(marketplaces) * pages)
            completed_pages = 0
            consent_checked_domains: set[str] = set()

            for domain in marketplaces:
                log_fn(f"🌍 Scraping domain: **{domain}**")
                for term in terms:
                    rules = search_config[term]
                    log_fn(f"  🔍 Search term: **{term}**")
                    for page in range(1, pages + 1):
                        report.pages_attempted += 1
                        url = build_search_url(domain, term, page)
                        page_rows: list[dict] | None = None
                        last_error = "unknown failure"
                        final_url = ""
                        consent_initialized = False
                        successful_attempt = 0

                        for attempt in range(1, retries + 2):
                            try:
                                consent_initialized = _prepare_search_page(
                                    driver,
                                    url,
                                    log_fn,
                                    check_consent=domain not in consent_checked_domains,
                                ) or consent_initialized
                                consent_checked_domains.add(domain)
                                final_url = driver.current_url
                                reason = _block_reason(driver)
                                if reason:
                                    raise TimeoutException(reason)
                                WebDriverWait(driver, 12).until(
                                    EC.presence_of_element_located(
                                        (
                                            By.CSS_SELECTOR,
                                            (
                                                "li.s-item, div.s-item, li.s-card, "
                                                "div.s-card, .su-card-container, "
                                                "[data-testid='item-card'], "
                                                "[data-testid='item-list-card'], "
                                                "a[href*='/itm/']"
                                            ),
                                        )
                                    )
                                )
                                time.sleep(random.uniform(delay[0], delay[1]))
                                page_rows = parse_html(driver.page_source, domain, term, rules)
                                if not page_rows:
                                    raise TimeoutException(
                                        "Result links loaded, but no product cards were parsed"
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
                                    "page": page,
                                    "error": last_error,
                                    "requested_url": url,
                                    "final_url": final_url,
                                }
                            )
                            log_fn(f"    ⚠️ Page {page} failed after {retries + 1} attempt(s)")
                        else:
                            rows.extend(page_rows)
                            report.pages_succeeded += 1
                            report.events.append(
                                {
                                    "marketplace": domain,
                                    "search_term": term,
                                    "page": page,
                                    "listings": len(page_rows),
                                    "status": "succeeded",
                                    "requested_url": url,
                                    "final_url": final_url,
                                    "final_domain": urlsplit(final_url).netloc.removeprefix(
                                        "www."
                                    ),
                                    "currency_codes": sorted(
                                        {
                                            row["currency_code"]
                                            for row in page_rows
                                            if row.get("currency_code")
                                        }
                                    ),
                                    "attempts_used": successful_attempt,
                                    "consent_initialized": consent_initialized,
                                }
                            )
                            log_fn(f"    ✅ Page {page}: {len(page_rows)} products found")

                        completed_pages += 1
                        progress_fn(completed_pages / total_pages)
                        if max_products:
                            have = collected_count(rows, domain, term)
                            if have >= max_products:
                                log_fn(f"    🎯 Target reached: {have}/{max_products} products")
                                break
                            if not page_rows:
                                log_fn(f"    ⏹ Stopping after page {page} ({have} products)")
                                break

            raw = pd.DataFrame(rows, columns=RESULT_COLUMNS)
            if not raw.empty:
                raw["price_usd"] = pd.to_numeric(raw["price_usd"], errors="coerce").round(2)
            unique = _deduplicate(raw)
            report.listings_collected = len(raw)
            report.unique_listings = len(unique)
            report.duplicate_count = len(raw) - len(unique)
            report.missing_price_count = int(raw["price_value"].isna().sum())
            report.finished_at = utc_now()
            if report.pages_succeeded == 0:
                report.status = "failed"
            elif report.failures:
                report.status = "completed_with_errors"
            else:
                report.status = "completed"
            return ScrapeOutcome(raw.reset_index(drop=True), report)
        finally:
            driver.quit()

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
):
    return EbayScraper().search(
        search_config,
        selected_domains,
        headless=headless,
        delay=delay,
        log=log_fn,
        progress=progress_fn,
        pages=pages,
        retries=retries,
    )
