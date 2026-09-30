from __future__ import annotations

import random
import time
import urllib.parse
from collections.abc import Callable

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

from .constants import DOMAIN_DEFAULT_POSTCODE
from .locations import set_delivery_location
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
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)
    options.set_preference("media.autoplay.default", 5)
    return options


def _clear_interstitial(driver) -> None:
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except WebDriverException:
        return
    if "continue shopping" not in body_text and "click the button below" not in body_text:
        return
    for selector in ("input[type='submit']", "button[type='submit']", "button"):
        try:
            button = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            button.click()
            time.sleep(2.5)
            return
        except (TimeoutException, WebDriverException):
            continue


def _page_block_reason(driver) -> str | None:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
    except WebDriverException:
        return "page body unavailable"
    signals = {
        "captcha": "captcha",
        "robot check": "robot check",
        "enter the characters you see below": "captcha",
        "sorry, we just need to make sure you're not a robot": "robot check",
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


class AmazonScraper:
    """Amazon collector used by Streamlit, the CLI, and future agent tools."""

    def __init__(self, driver_factory: Callable | None = None):
        self.driver_factory = driver_factory or webdriver.Firefox

    def search_with_report(
        self,
        search_config: dict,
        marketplaces: list[str],
        *,
        headless: bool = True,
        delay: tuple[float, float] = (1.5, 3.5),
        postcodes: dict[str, str] | None = None,
        set_location: bool = True,
        pages: int = 1,
        retries: int = 2,
        log: LogFunction | None = None,
        progress: ProgressFunction | None = None,
        max_products: int | None = None,
    ) -> ScrapeOutcome:
        log_fn = log or (lambda _message: None)
        progress_fn = progress or (lambda _value: None)
        report = ScrapeReport(pages_requested=pages)
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
            effective_postcodes = {**DOMAIN_DEFAULT_POSTCODE, **(postcodes or {})}

            for domain in marketplaces:
                if set_location and effective_postcodes.get(domain):
                    set_delivery_location(
                        driver, domain, effective_postcodes[domain], log_fn
                    )
                log_fn(f"🌍 Scraping domain: **{domain}**")

                for term in terms:
                    rules = search_config[term]
                    log_fn(f"  🔍 Search term: **{term}**")

                    for page in range(1, pages + 1):
                        report.pages_attempted += 1
                        url = (
                            f"https://{domain}/s?"
                            + urllib.parse.urlencode({"k": term, "page": page})
                        )
                        page_rows: list[dict] | None = None
                        last_error = "unknown failure"

                        for attempt in range(1, retries + 2):
                            try:
                                driver.get(url)
                                _clear_interstitial(driver)
                                block_reason = _page_block_reason(driver)
                                if block_reason:
                                    raise TimeoutException(block_reason)
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located(
                                        (By.CSS_SELECTOR, "div.s-result-item")
                                    )
                                )
                                time.sleep(random.uniform(delay[0], delay[1]))
                                page_rows = parse_html(
                                    driver.page_source, domain, term, rules
                                )
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
                            failure = {
                                "marketplace": domain,
                                "search_term": term,
                                "page": page,
                                "error": last_error,
                            }
                            report.failures.append(failure)
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
                                log_fn(f"    ⏹ No more results after page {page} ({have} products)")
                                break

            raw = pd.DataFrame(rows, columns=RESULT_COLUMNS)
            if not raw.empty:
                raw["price_usd"] = pd.to_numeric(raw["price_usd"], errors="coerce").round(2)
                raw = raw[[column for column in RESULT_COLUMNS if column in raw.columns]]

            unique = _deduplicate(raw) if not raw.empty else raw
            report.listings_collected = len(raw)
            report.unique_listings = len(unique)
            report.duplicate_count = len(raw) - len(unique)
            report.missing_price_count = (
                int(raw["price_value"].isna().sum())
            )
            report.finished_at = utc_now()
            if report.pages_succeeded == 0:
                report.status = "failed"
            elif report.failures:
                report.status = "completed_with_errors"
            else:
                report.status = "completed"
            return ScrapeOutcome(raw_products=raw.reset_index(drop=True), report=report)
        finally:
            driver.quit()

    def search(
        self,
        search_config: dict,
        marketplaces: list[str],
        **kwargs,
    ) -> pd.DataFrame:
        outcome = self.search_with_report(search_config, marketplaces, **kwargs)
        return _deduplicate(outcome.raw_products).reset_index(drop=True)


def run_scrape(
    search_config,
    selected_domains,
    headless,
    delay,
    log_fn,
    progress_fn,
    postcodes=None,
    set_location=True,
    pages=1,
    retries=2,
):
    """Backward-compatible entry point used by the existing Streamlit app."""
    return AmazonScraper().search(
        search_config,
        selected_domains,
        headless=headless,
        delay=delay,
        log=log_fn,
        progress=progress_fn,
        postcodes=postcodes,
        set_location=set_location,
        pages=pages,
        retries=retries,
    )
