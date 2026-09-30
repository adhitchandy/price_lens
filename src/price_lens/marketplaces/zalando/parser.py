from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from price_lens.core.classification import classify_product, normalize_ws
from price_lens.core.currency import (
    canonical_currency_symbol,
    convert_to_usd,
    detect_currency,
    normalize_price_number,
)
from price_lens.core.schemas import utc_now

from .constants import (
    DOMAIN_AUDIENCE_PATH_OVERRIDES,
    DOMAIN_SEARCH_PATH_PREFIX,
    DOMAIN_TO_CURRENCY,
    ZALANDO_MARKETPLACES,
)

AUDIENCE_ORDER = ("women", "men", "kids")


def canonicalize_url(url: str | None, domain: str) -> str | None:
    if not url:
        return None
    absolute = urljoin(f"https://www.{domain}/", url)
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))


def extract_product_id(url: str | None) -> str | None:
    match = re.search(r"-([a-z0-9]{9,18}-[a-z0-9]{3})\.html", url or "", re.IGNORECASE)
    return match.group(1).upper() if match else None


def discover_audience_paths(html_source: str) -> dict[str, str]:
    """Read localized audience paths from Zalando's ordered shop selector."""
    soup = BeautifulSoup(html_source, "lxml")
    paths: list[str] = []
    for container in soup.select('[data-testid="genderLink"]'):
        link = container.select_one("a[href]")
        if not link:
            continue
        path = urlsplit(link.get("href", "")).path
        path = re.sub(r"-home/?$", "/", path)
        if path and path not in paths:
            paths.append(path)
        if len(paths) == len(AUDIENCE_ORDER):
            break
    if len(paths) != len(AUDIENCE_ORDER):
        return {}
    return dict(zip(AUDIENCE_ORDER, paths, strict=True))


def search_audience_path(domain: str, audience: str, discovered_path: str) -> str:
    override = DOMAIN_AUDIENCE_PATH_OVERRIDES.get(domain, {}).get(audience)
    if override:
        return override
    prefix = DOMAIN_SEARCH_PATH_PREFIX.get(domain)
    if not prefix:
        return discovered_path
    slug = discovered_path.strip("/")
    return f"/{prefix}{slug}/"


def _current_price_text(card) -> str:
    header = card.select_one("header")
    if not header:
        return ""
    for paragraph in header.select("section p"):
        text = normalize_ws(paragraph.get_text(" ", strip=True))
        if not text:
            continue
        lowered = text.lower()
        if "regular price" not in lowered and "last lowest price" not in lowered:
            return text
    return ""


def parse_html(
    html_source: str,
    domain: str,
    search_term: str,
    rules: list[dict],
    audience: str | None = None,
) -> list[dict]:
    """Parse rendered Zalando search cards without relying on generated CSS classes."""
    soup = BeautifulSoup(html_source, "lxml")
    rows: list[dict[str, Any]] = []
    for card in soup.select("article"):
        header = card.select_one("header h3")
        product_link = card.select_one("a[href$='.html']")
        if not header or not product_link:
            continue
        parts = [normalize_ws(span.get_text(" ", strip=True)) for span in header.find_all("span")]
        parts = [part for part in parts if part]
        if len(parts) < 2:
            continue
        brand, name = parts[0], parts[1]
        product_url = canonicalize_url(product_link.get("href"), domain)
        price_text = _current_price_text(card)
        default_currency = DOMAIN_TO_CURRENCY.get(domain, "EUR")
        currency_code, currency_symbol = detect_currency(price_text, default_currency)
        price_value = normalize_price_number(price_text)
        image = card.select_one("img[src]")
        rows.append(
            {
                "platform": "zalando",
                "marketplace": domain,
                "product_type": classify_product(f"{brand} {name}", rules, search_term),
                "search_term": search_term,
                "origin_country": ZALANDO_MARKETPLACES.get(domain, domain),
                "audience": audience,
                "brand": brand,
                "product_name": name,
                "product_id": extract_product_id(product_url),
                "currency_code": currency_code,
                "currency_symbol": currency_symbol,
                "currency": currency_symbol,
                "price_text": price_text,
                "price": price_text,
                "price_value": price_value,
                "price_usd": convert_to_usd(price_value, currency_code),
                "rating": None,
                "review_count": None,
                "sponsored": "sponsored" in card.get_text(" ", strip=True).lower(),
                "seller": None,
                "condition": "New",
                "shipping_price_text": None,
                "shipping_price_value": None,
                "buying_format": "retail",
                "color": None,
                "availability": None,
                "image_url": image.get("src") if image else None,
                "detail_enriched": False,
                "product_url": product_url,
                "link": product_url,
                "scraped_at": utc_now(),
            }
        )
    return rows


def _json_ld_nodes(soup: BeautifulSoup) -> list[Any]:
    nodes: list[Any] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        nodes.extend(payload if isinstance(payload, list) else [payload])
    return nodes


def parse_product_detail(html_source: str, domain: str) -> dict[str, Any]:
    """Extract one product-level record from Zalando's Schema.org ProductGroup."""
    soup = BeautifulSoup(html_source, "lxml")
    group = next(
        (
            node
            for node in _json_ld_nodes(soup)
            if isinstance(node, dict) and node.get("@type") == "ProductGroup"
        ),
        None,
    )
    if not group:
        return {}

    variants = group.get("hasVariant") or []
    offers = [variant.get("offers", {}) for variant in variants if isinstance(variant, dict)]
    offer = next((item for item in offers if item.get("price") is not None), {})
    price_value = normalize_price_number(str(offer.get("price", "")))
    currency_code = str(offer.get("priceCurrency") or DOMAIN_TO_CURRENCY.get(domain, "EUR"))
    currency_symbol = canonical_currency_symbol(currency_code)
    availabilities = {
        str(item.get("availability", "")).rsplit("/", 1)[-1]
        for item in offers
        if item.get("availability")
    }
    availability = "InStock" if "InStock" in availabilities else next(iter(availabilities), None)
    brand = group.get("brand") or {}
    images = group.get("image") or []
    if isinstance(images, str):
        images = [images]
    product_url = canonicalize_url(group.get("url"), domain)
    return {
        "brand": brand.get("name") if isinstance(brand, dict) else str(brand),
        "product_name": group.get("name"),
        "product_id": group.get("productGroupID") or extract_product_id(product_url),
        "product_url": product_url,
        "link": product_url,
        "price_text": f"{currency_symbol}{price_value:g}" if price_value is not None else None,
        "price": f"{currency_symbol}{price_value:g}" if price_value is not None else None,
        "price_value": price_value,
        "currency_code": currency_code,
        "currency_symbol": currency_symbol,
        "currency": currency_symbol,
        "price_usd": convert_to_usd(price_value, currency_code),
        "color": group.get("color"),
        "availability": availability,
        "image_url": images[0] if images else None,
        "detail_enriched": True,
    }
