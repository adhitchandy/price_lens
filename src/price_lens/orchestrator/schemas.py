from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from price_lens.core.schemas import MarketplaceSearchPlan, ProductRule, SearchSpec

SUPPORTED_PLATFORMS = ("amazon", "ebay", "zalando", "mediamarkt")
SUPPORTED_AUDIENCES = ("men", "women", "kids")


@dataclass(frozen=True)
class ResearchSearch:
    search_term: str
    product_type: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    audiences: tuple[str, ...] = ()
    localized_queries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def applies_to(self, platform: str) -> bool:
        return not self.platforms or platform in self.platforms


@dataclass(frozen=True)
class ReviewConfig:
    instruction: str = "Keep products that directly satisfy the research question."
    batch_size: int = 30
    minimum_keep_confidence: float = 0.8
    allowed_brands: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchPlan:
    research_question: str
    marketplaces: dict[str, tuple[str, ...]]
    searches: tuple[ResearchSearch, ...]
    target_results: int | None = None
    headless: bool = True
    pages: int = 1
    retries: int = 2
    delay_seconds: tuple[float, float] = (1.5, 3.5)
    output_dir: Path = Path("output")
    cleaning: dict[str, Any] = field(default_factory=dict)
    postcodes: dict[str, str] = field(default_factory=dict)
    set_location: bool = True
    enrich_details: bool = False
    max_detail_products: int | None = None
    review: ReviewConfig = field(default_factory=ReviewConfig)
    require_localized_queries: bool = False
    max_products: int | None = None

    @property
    def platforms(self) -> tuple[str, ...]:
        return tuple(self.marketplaces)

    def platform_plan(self, platform: str) -> MarketplaceSearchPlan:
        searches = tuple(
            SearchSpec(
                search.search_term,
                ProductRule(search.product_type, search.include, search.exclude),
                search.audiences if platform == "zalando" else (),
                search.localized_queries,
            )
            for search in self.searches
            if search.applies_to(platform)
        )
        return MarketplaceSearchPlan(
            searches=searches,
            marketplaces=self.marketplaces[platform],
            headless=self.headless,
            set_location=self.set_location,
            postcodes=self.postcodes,
            pages=self.pages,
            retries=self.retries,
            delay_seconds=self.delay_seconds,
            output_dir=self.output_dir,
            cleaning=self.cleaning,
            enrich_details=self.enrich_details,
            max_detail_products=self.max_detail_products,
            max_products=self.max_products,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["marketplaces"] = {
            platform: list(domains) for platform, domains in self.marketplaces.items()
        }
        payload["searches"] = [
            {
                **asdict(search),
                "include": list(search.include),
                "exclude": list(search.exclude),
                "platforms": list(search.platforms),
                "audiences": list(search.audiences),
            }
            for search in self.searches
        ]
        return payload
