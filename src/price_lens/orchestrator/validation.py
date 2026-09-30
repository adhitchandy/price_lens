"""Validation and parsing for orchestrator (multi-marketplace) research plans.

The parser returns :class:`price_lens.orchestrator.schemas.ResearchPlan`,
which is the object the runner, localization layer and CLI all rely on
(``platform_plan()``, ``to_dict()``, ``target_results``, ``review`` ...).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from price_lens.core.validation import RequestValidationError
from price_lens.marketplaces.amazon.constants import AMAZON_DOMAINS
from price_lens.marketplaces.ebay.constants import EBAY_MARKETPLACES
from price_lens.marketplaces.mediamarkt.constants import MEDIAMARKT_MARKETPLACES
from price_lens.marketplaces.zalando.constants import ZALANDO_MARKETPLACES

from .schemas import (
    SUPPORTED_AUDIENCES,
    SUPPORTED_PLATFORMS,
    ResearchPlan,
    ResearchSearch,
    ReviewConfig,
)

SUPPORTED_DOMAINS: dict[str, set[str]] = {
    "amazon": set(AMAZON_DOMAINS),
    "ebay": set(EBAY_MARKETPLACES),
    "zalando": set(ZALANDO_MARKETPLACES),
    "mediamarkt": set(MEDIAMARKT_MARKETPLACES),
}


def _string_list(value: Any, field_name: str, *, lower: bool = True) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise RequestValidationError(f"'{field_name}' must be a list of strings")
    cleaned = (item.strip() for item in value if item.strip())
    return tuple(dict.fromkeys(item.lower() if lower else item for item in cleaned))


def _parse_marketplaces(raw: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict) or not raw:
        raise RequestValidationError(
            "'marketplaces' must be an object mapping platform names to lists of domains"
        )
    marketplaces: dict[str, tuple[str, ...]] = {}
    for platform, domains in raw.items():
        if platform not in SUPPORTED_PLATFORMS:
            raise RequestValidationError(
                f"Unsupported platform '{platform}'. Use: {', '.join(SUPPORTED_PLATFORMS)}"
            )
        if isinstance(domains, str):
            domains = [domains]
        parsed = _string_list(domains, f"marketplaces.{platform}")
        if not parsed:
            raise RequestValidationError(f"'marketplaces.{platform}' needs at least one domain")
        unknown = sorted(set(parsed) - SUPPORTED_DOMAINS[platform])
        if unknown:
            raise RequestValidationError(
                f"Unsupported {platform} marketplace(s): {', '.join(unknown)}"
            )
        marketplaces[platform] = parsed
    return marketplaces


def _parse_localized(value: Any, index: int) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RequestValidationError(f"Search {index} 'localized_queries' must be an object")
    localized: dict[str, dict[str, Any]] = {}
    for domain, entry in value.items():
        if not isinstance(entry, dict):
            raise RequestValidationError(
                f"Search {index} localized_queries['{domain}'] must be an object"
            )
        term = str(entry.get("search_term", "")).strip()
        language = str(entry.get("language", "")).strip()
        if not term or not language:
            raise RequestValidationError(
                f"Search {index} localized_queries['{domain}'] needs 'search_term' and 'language'"
            )
        localized[str(domain).strip().lower()] = {
            "language": language,
            "search_term": term,
            # Always present so the localization layer can index them directly.
            "include": list(_string_list(entry.get("include", []), f"localized_queries.{domain}.include")),
            "exclude": list(_string_list(entry.get("exclude", []), f"localized_queries.{domain}.exclude")),
        }
        audience = entry.get("audience")
        if audience is not None:
            if audience not in SUPPORTED_AUDIENCES:
                raise RequestValidationError(
                    f"Search {index} localized_queries['{domain}'] has unsupported audience '{audience}'")
            localized[str(domain).strip().lower()]["audience"] = audience
    return localized


def _parse_searches(raw: Any, marketplaces: dict[str, tuple[str, ...]],
                    require_localized: bool) -> tuple[ResearchSearch, ...]:
    if not isinstance(raw, (list, tuple)) or not raw:
        raise RequestValidationError("'searches' must contain at least one search object")

    searches: list[ResearchSearch] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise RequestValidationError(f"Search {index} must be an object")
        term = str(item.get("search_term", "")).strip()
        product_type = str(item.get("product_type", "")).strip()
        if not term or not product_type:
            raise RequestValidationError(
                f"Search {index} requires non-empty 'search_term' and 'product_type'"
            )

        platforms = _string_list(item.get("platforms", []), f"searches[{index}].platforms")
        unknown_platforms = sorted(set(platforms) - set(marketplaces))
        if unknown_platforms:
            raise RequestValidationError(
                f"Search {index} targets platform(s) not listed in 'marketplaces': "
                + ", ".join(unknown_platforms)
            )

        audiences = _string_list(item.get("audiences", []), f"searches[{index}].audiences")
        unknown_audiences = sorted(set(audiences) - set(SUPPORTED_AUDIENCES))
        if unknown_audiences:
            raise RequestValidationError(
                f"Search {index} has unsupported audience(s): {', '.join(unknown_audiences)}"
            )

        search = ResearchSearch(
            search_term=term,
            product_type=product_type,
            include=_string_list(item.get("include", []), f"searches[{index}].include"),
            exclude=_string_list(item.get("exclude", []), f"searches[{index}].exclude"),
            platforms=platforms,
            audiences=audiences,
            localized_queries=_parse_localized(item.get("localized_queries"), index),
        )

        if "zalando" in marketplaces and search.applies_to("zalando") and not audiences:
            raise RequestValidationError(
                f"Search {index} targets Zalando and requires 'audiences' (men, women, kids)"
            )

        if require_localized:
            missing = [
                domain
                for platform, domains in marketplaces.items()
                if search.applies_to(platform)
                for domain in domains
                if domain not in search.localized_queries
            ]
            if missing:
                raise RequestValidationError(
                    f"Search {index} is missing localized_queries for: {', '.join(missing)}"
                )
        searches.append(search)
    return tuple(searches)


def _parse_review(raw: Any) -> ReviewConfig:
    if raw is None:
        return ReviewConfig()
    if not isinstance(raw, dict):
        raise RequestValidationError("'review' must be an object")
    defaults = ReviewConfig()
    batch_size = raw.get("batch_size", defaults.batch_size)
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 500:
        raise RequestValidationError("'review.batch_size' must be an integer between 1 and 500")
    confidence = raw.get("minimum_keep_confidence", defaults.minimum_keep_confidence)
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise RequestValidationError("'review.minimum_keep_confidence' must be between 0 and 1")
    instruction = str(raw.get("instruction", defaults.instruction)).strip() or defaults.instruction
    return ReviewConfig(
        instruction=instruction,
        batch_size=batch_size,
        minimum_keep_confidence=float(confidence),
        allowed_brands=_string_list(raw.get("allowed_brands", []), "review.allowed_brands"),
    )


def parse_research_plan(data: dict[str, Any]) -> ResearchPlan:
    """Validate a multi-marketplace research plan and build a runnable ResearchPlan."""
    if not isinstance(data, dict):
        raise RequestValidationError("The research plan must be a JSON object")

    research_question = str(data.get("research_question", "")).strip()
    if not research_question:
        raise RequestValidationError("'research_question' must be a non-empty string")

    marketplaces = _parse_marketplaces(data.get("marketplaces"))

    require_localized = data.get("require_localized_queries", False)
    if not isinstance(require_localized, bool):
        raise RequestValidationError("'require_localized_queries' must be true or false")

    searches = _parse_searches(data.get("searches"), marketplaces, require_localized)

    pages = data.get("pages", 1)
    if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 20:
        raise RequestValidationError("'pages' must be an integer between 1 and 20")

    retries = data.get("retries", 2)
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5:
        raise RequestValidationError("'retries' must be an integer between 0 and 5")

    delay = data.get("delay_seconds", [1.5, 3.5])
    if (
        not isinstance(delay, (list, tuple))
        or len(delay) != 2
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in delay)
        or delay[0] < 0.5
        or delay[1] < delay[0]
        or delay[1] > 60
    ):
        raise RequestValidationError(
            "'delay_seconds' must be [minimum, maximum], between 0.5 and 60 seconds"
        )

    target_results = data.get("target_results")
    if target_results is not None and (
        isinstance(target_results, bool)
        or not isinstance(target_results, int)
        or not 1 <= target_results <= 100000
    ):
        raise RequestValidationError("'target_results' must be null or an integer 1-100000")

    enrich_details = data.get("enrich_details", False)
    if not isinstance(enrich_details, bool):
        raise RequestValidationError("'enrich_details' must be true or false")

    max_detail_products = data.get("max_detail_products")
    if max_detail_products is not None and (
        isinstance(max_detail_products, bool)
        or not isinstance(max_detail_products, int)
        or not 1 <= max_detail_products <= 10000
    ):
        raise RequestValidationError(
            "'max_detail_products' must be null or an integer between 1 and 10000"
        )

    max_products = data.get("max_products")
    if max_products is not None and (
        isinstance(max_products, bool) or not isinstance(max_products, int)
        or not 1 <= max_products <= 5000
    ):
        raise RequestValidationError("'max_products' must be null or an integer between 1 and 5000")

    cleaning = data.get("cleaning", {})
    if not isinstance(cleaning, dict):
        raise RequestValidationError("'cleaning' must be an object")

    postcodes = data.get("postcodes", {})
    if not isinstance(postcodes, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in postcodes.items()
    ):
        raise RequestValidationError("'postcodes' must be an object of domain/string pairs")

    return ResearchPlan(
        research_question=research_question,
        marketplaces=marketplaces,
        searches=searches,
        target_results=target_results,
        headless=bool(data.get("headless", True)),
        pages=pages,
        retries=retries,
        delay_seconds=(float(delay[0]), float(delay[1])),
        output_dir=Path(data.get("output_dir", "output")),
        cleaning=cleaning,
        postcodes=postcodes,
        set_location=bool(data.get("set_location", True)),
        enrich_details=enrich_details,
        max_detail_products=max_detail_products,
        review=_parse_review(data.get("review")),
        require_localized_queries=require_localized,
        max_products=max_products,
    )


def load_research_plan(path: str | Path) -> ResearchPlan:
    """Load and validate a research plan JSON file."""
    plan_path = Path(path)
    try:
        content = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RequestValidationError(f"Research plan not found: {plan_path}") from exc
    except json.JSONDecodeError as exc:
        raise RequestValidationError(
            f"Invalid JSON in {plan_path} at line {exc.lineno}: {exc.msg}"
        ) from exc
    return parse_research_plan(content)
