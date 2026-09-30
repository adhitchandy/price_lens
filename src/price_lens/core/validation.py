from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import MarketplaceSearchPlan, ProductRule, SearchSpec


class RequestValidationError(ValueError):
    """Raised when a scrape request is unsafe, incomplete, or schema-invalid."""


def _string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RequestValidationError(f"'{field_name}' must be a list of strings")
    return tuple(item.strip().lower() for item in value if item.strip())


def parse_marketplace_plan(
    data: dict[str, Any], supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    if not isinstance(data, dict):
        raise RequestValidationError("The request must be a JSON object")

    raw_searches = data.get("searches")
    if not isinstance(raw_searches, list) or not raw_searches:
        raise RequestValidationError("'searches' must contain at least one search object")

    searches: list[SearchSpec] = []
    for index, item in enumerate(raw_searches, start=1):
        if not isinstance(item, dict):
            raise RequestValidationError(f"Search {index} must be an object")
        term = str(item.get("search_term", "")).strip()
        product_type = str(item.get("product_type", "")).strip()
        if not term or not product_type:
            raise RequestValidationError(
                f"Search {index} requires non-empty 'search_term' and 'product_type'"
            )
        include = _string_list(item.get("include", []), f"searches[{index}].include")
        exclude = _string_list(item.get("exclude", []), f"searches[{index}].exclude")
        audiences = _string_list(item.get("audiences", []), f"searches[{index}].audiences")
        unknown_audiences = sorted(set(audiences) - {"men", "women", "kids"})
        if unknown_audiences:
            raise RequestValidationError(
                f"Search {index} has unsupported audience(s): {', '.join(unknown_audiences)}"
            )
        searches.append(
            SearchSpec(term.lower(), ProductRule(product_type, include, exclude), audiences)
        )

    marketplaces = data.get("marketplaces")
    if not isinstance(marketplaces, list) or not marketplaces:
        raise RequestValidationError("'marketplaces' must contain at least one marketplace domain")
    if not all(isinstance(item, str) for item in marketplaces):
        raise RequestValidationError("'marketplaces' must be a list of strings")
    unknown = sorted(set(marketplaces) - supported_marketplaces)
    if unknown:
        raise RequestValidationError(f"Unsupported marketplace(s): {', '.join(unknown)}")

    pages = data.get("pages", 1)
    retries = data.get("retries", 2)
    if not isinstance(pages, int) or not 1 <= pages <= 20:
        raise RequestValidationError("'pages' must be an integer between 1 and 20")
    if not isinstance(retries, int) or not 0 <= retries <= 5:
        raise RequestValidationError("'retries' must be an integer between 0 and 5")

    delay = data.get("delay_seconds", [1.5, 3.5])
    if (
        not isinstance(delay, list)
        or len(delay) != 2
        or not all(isinstance(value, (int, float)) for value in delay)
        or delay[0] < 0.5
        or delay[1] < delay[0]
        or delay[1] > 60
    ):
        raise RequestValidationError(
            "'delay_seconds' must be [minimum, maximum], between 0.5 and 60 seconds"
        )

    postcodes = data.get("postcodes", {})
    cleaning = data.get("cleaning", {})
    if not isinstance(postcodes, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in postcodes.items()
    ):
        raise RequestValidationError("'postcodes' must be an object of domain/string pairs")
    if not isinstance(cleaning, dict):
        raise RequestValidationError("'cleaning' must be an object")

    enrich_details = data.get("enrich_details", False)
    max_detail_products = data.get("max_detail_products")
    if not isinstance(enrich_details, bool):
        raise RequestValidationError("'enrich_details' must be true or false")
    if max_detail_products is not None and (
        not isinstance(max_detail_products, int) or not 1 <= max_detail_products <= 1000
    ):
        raise RequestValidationError(
            "'max_detail_products' must be null or an integer between 1 and 1000"
        )

    return MarketplaceSearchPlan(
        searches=tuple(searches),
        marketplaces=tuple(dict.fromkeys(marketplaces)),
        headless=bool(data.get("headless", True)),
        set_location=bool(data.get("set_location", True)),
        postcodes=postcodes,
        pages=pages,
        retries=retries,
        delay_seconds=(float(delay[0]), float(delay[1])),
        output_dir=Path(data.get("output_dir", "output")),
        cleaning=cleaning,
        enrich_details=enrich_details,
        max_detail_products=max_detail_products,
    )


def load_marketplace_plan(
    path: str | Path, supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    request_path = Path(path)
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RequestValidationError(f"Request file not found: {request_path}") from exc
    except json.JSONDecodeError as exc:
        raise RequestValidationError(f"Invalid JSON at line {exc.lineno}: {exc.msg}") from exc
    return parse_marketplace_plan(data, supported_marketplaces)


def parse_amazon_plan(
    data: dict[str, Any], supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    return parse_marketplace_plan(data, supported_marketplaces)


def load_amazon_plan(
    path: str | Path, supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    return load_marketplace_plan(path, supported_marketplaces)


def parse_ebay_plan(
    data: dict[str, Any], supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    return parse_marketplace_plan(data, supported_marketplaces)


def load_ebay_plan(
    path: str | Path, supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    return load_marketplace_plan(path, supported_marketplaces)


def parse_zalando_plan(
    data: dict[str, Any], supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    plan = parse_marketplace_plan(data, supported_marketplaces)
    missing = [str(index) for index, search in enumerate(plan.searches, 1) if not search.audiences]
    if missing:
        raise RequestValidationError(
            "Zalando search audience is required for search(es): " + ", ".join(missing)
        )
    return plan


def load_zalando_plan(
    path: str | Path, supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    request_path = Path(path)
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RequestValidationError(f"Request file not found: {request_path}") from exc
    except json.JSONDecodeError as exc:
        raise RequestValidationError(f"Invalid JSON at line {exc.lineno}: {exc.msg}") from exc
    return parse_zalando_plan(data, supported_marketplaces)


def parse_mediamarkt_plan(
    data: dict[str, Any], supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    return parse_marketplace_plan(data, supported_marketplaces)


def load_mediamarkt_plan(
    path: str | Path, supported_marketplaces: set[str]
) -> MarketplaceSearchPlan:
    return load_marketplace_plan(path, supported_marketplaces)