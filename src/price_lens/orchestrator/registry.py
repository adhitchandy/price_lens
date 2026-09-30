from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import MarketplaceSearchPlan
from price_lens.marketplaces.amazon.scraper import AmazonScraper
from price_lens.marketplaces.ebay.scraper import EbayScraper
from price_lens.marketplaces.mediamarkt.scraper import MediaMarktScraper
from price_lens.marketplaces.zalando.scraper import ZalandoScraper

LogFunction = Callable[[str], None]


@dataclass(frozen=True)
class MarketplaceAdapter:
    name: str
    collect: Callable[[MarketplaceSearchPlan, LogFunction], ScrapeOutcome]


def _amazon(plan: MarketplaceSearchPlan, log: LogFunction) -> ScrapeOutcome:
    return AmazonScraper().search_with_report(
        plan.search_config(),
        list(plan.marketplaces),
        headless=plan.headless,
        delay=plan.delay_seconds,
        postcodes=plan.postcodes,
        set_location=plan.set_location,
        pages=plan.pages,
        retries=plan.retries,
        log=log,
        max_products=plan.max_products,
    )


def _ebay(plan: MarketplaceSearchPlan, log: LogFunction) -> ScrapeOutcome:
    return EbayScraper().search_with_report(
        plan.search_config(),
        list(plan.marketplaces),
        headless=plan.headless,
        delay=plan.delay_seconds,
        pages=plan.pages,
        retries=plan.retries,
        log=log,
        max_products=plan.max_products,
    )


def _zalando(plan: MarketplaceSearchPlan, log: LogFunction) -> ScrapeOutcome:
    return ZalandoScraper().search_with_report(
        plan.search_config(),
        list(plan.marketplaces),
        headless=plan.headless,
        delay=plan.delay_seconds,
        pages=plan.pages,
        retries=plan.retries,
        enrich_details=plan.enrich_details,
        max_detail_products=plan.max_detail_products,
        log=log,
        max_products=plan.max_products,
    )


def _mediamarkt(plan: MarketplaceSearchPlan, log: LogFunction) -> ScrapeOutcome:
    return MediaMarktScraper().search_with_report(
        plan.search_config(),
        list(plan.marketplaces),
        headless=plan.headless,
        delay=plan.delay_seconds,
        pages=plan.pages,
        retries=plan.retries,
        enrich_details=plan.enrich_details,
        max_detail_products=plan.max_detail_products,
        languages=plan.languages,
        diagnostics_dir=plan.output_dir / "diagnostics",
        log=log,
        max_products=plan.max_products,
    )


MARKETPLACE_REGISTRY = {
    "amazon": MarketplaceAdapter("amazon", _amazon),
    "ebay": MarketplaceAdapter("ebay", _ebay),
    "zalando": MarketplaceAdapter("zalando", _zalando),
    "mediamarkt": MarketplaceAdapter("mediamarkt", _mediamarkt),
}
