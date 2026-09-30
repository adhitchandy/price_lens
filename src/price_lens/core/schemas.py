from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProductRule:
    product_type: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def as_legacy_dict(self) -> dict[str, Any]:
        return {
            "type": self.product_type,
            "include": list(self.include),
            "exclude": list(self.exclude),
        }


@dataclass(frozen=True)
class SearchSpec:
    search_term: str
    rule: ProductRule
    audiences: tuple[str, ...] = ()
    localized_queries: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketplaceSearchPlan:
    searches: tuple[SearchSpec, ...]
    marketplaces: tuple[str, ...]
    headless: bool = True
    set_location: bool = True
    postcodes: dict[str, str] = field(default_factory=dict)
    pages: int = 1
    retries: int = 2
    delay_seconds: tuple[float, float] = (1.5, 3.5)
    output_dir: Path = Path("output")
    cleaning: dict[str, Any] = field(default_factory=dict)
    enrich_details: bool = False
    max_detail_products: int | None = None
    languages: dict[str, str] = field(default_factory=dict)
    max_products: int | None = None

    def search_config(self) -> dict[str, list[dict[str, Any]]]:
        config: dict[str, list[dict[str, Any]]] = {}
        for search in self.searches:
            rule = search.rule.as_legacy_dict()
            if search.audiences:
                rule["audiences"] = list(search.audiences)
            config.setdefault(search.search_term, []).append(rule)
        return config

    def to_dict(self) -> dict[str, Any]:
        return {
            "searches": [
                {
                    "search_term": search.search_term,
                    "product_type": search.rule.product_type,
                    "include": list(search.rule.include),
                    "exclude": list(search.rule.exclude),
                    "audiences": list(search.audiences),
                    "localized_queries": search.localized_queries,
                }
                for search in self.searches
            ],
            "marketplaces": list(self.marketplaces),
            "headless": self.headless,
            "set_location": self.set_location,
            "postcodes": self.postcodes,
            "pages": self.pages,
            "retries": self.retries,
            "delay_seconds": list(self.delay_seconds),
            "output_dir": str(self.output_dir),
            "cleaning": self.cleaning,
            "enrich_details": self.enrich_details,
            "max_detail_products": self.max_detail_products,
            "languages": self.languages,
            "max_products": self.max_products,
        }


@dataclass
class ProductRecord:
    platform: str
    marketplace: str
    search_term: str
    product_name: str
    product_type: str
    product_id: str | None
    currency_code: str
    price_value: float | None
    product_url: str | None
    origin_country: str | None = None
    currency_symbol: str | None = None
    price_text: str | None = None
    price_usd: float | None = None
    rating: float | None = None
    review_count: int | None = None
    sponsored: bool = False
    seller: str | None = None
    condition: str | None = None
    shipping_price_text: str | None = None
    shipping_price_value: float | None = None
    buying_format: str | None = None
    brand: str | None = None
    color: str | None = None
    availability: str | None = None
    image_url: str | None = None
    detail_enriched: bool = False
    audience: str | None = None
    scraped_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapeReport:
    platform: str = "amazon"
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    pages_requested: int = 1
    pages_attempted: int = 0
    pages_succeeded: int = 0
    listings_collected: int = 0
    unique_listings: int = 0
    missing_price_count: int = 0
    duplicate_count: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Backward-compatible, platform-named aliases for type clarity at call sites.
AmazonSearchPlan = MarketplaceSearchPlan
EbaySearchPlan = MarketplaceSearchPlan
ZalandoSearchPlan = MarketplaceSearchPlan
MediaMarktSearchPlan = MarketplaceSearchPlan
