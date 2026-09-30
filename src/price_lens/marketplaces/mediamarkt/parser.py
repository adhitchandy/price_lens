from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from price_lens.core.classification import classify_product, normalize_ws
from price_lens.core.currency import (
    canonical_currency_symbol,
    convert_to_usd,
    normalize_price_number,
)
from price_lens.core.schemas import utc_now

from .constants import DOMAIN_TO_CURRENCY, MEDIAMARKT_MARKETPLACES


def canonicalize_url(url: str | None, domain: str) -> str | None:
    if not url:
        return None
    absolute = urljoin(f"https://www.{domain}/", url)
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))


def extract_product_id(url: str | None) -> str | None:
    match = re.search(r"-(\d+)\.html(?:$|[?#])", url or "", re.IGNORECASE)
    return match.group(1) if match else None


def _json_ld_objects(html_source: str) -> Iterable[dict[str, Any]]:
    soup = BeautifulSoup(html_source, "lxml")
    for script in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph")
            if isinstance(graph, list):
                yield from (item for item in graph if isinstance(item, dict))
            yield candidate


def _schema_name(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).rstrip("/").rsplit("/", 1)[-1]
    return text.removesuffix("Condition") or None


def _offer(product: dict[str, Any]) -> dict[str, Any]:
    offers = product.get("offers")
    if isinstance(offers, list):
        return next((item for item in offers if isinstance(item, dict)), {})
    return offers if isinstance(offers, dict) else {}


def _price(offer: dict[str, Any]) -> float | None:
    value = offer.get("price", offer.get("lowPrice"))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _rating(product: dict[str, Any]) -> tuple[float | None, int | None]:
    aggregate = product.get("aggregateRating")
    if not isinstance(aggregate, dict):
        return None, None
    try:
        rating = float(aggregate.get("ratingValue"))
    except (TypeError, ValueError):
        rating = None
    count_value = aggregate.get("reviewCount", aggregate.get("ratingCount"))
    try:
        count = int(count_value)
    except (TypeError, ValueError):
        count = None
    return rating, count


def _brand(product: dict[str, Any], name: str) -> str | None:
    brand = product.get("brand")
    if isinstance(brand, dict):
        value = normalize_ws(str(brand.get("name", "")))
        return value or None
    if isinstance(brand, str) and brand.strip():
        return normalize_ws(brand)
    return None


def _image(product: dict[str, Any]) -> str | None:
    image = product.get("image")
    if isinstance(image, list):
        return str(image[0]) if image else None
    return str(image) if image else None


def _money_text(value: float | None, currency_code: str) -> str | None:
    if value is None:
        return None
    symbol = canonical_currency_symbol(currency_code)
    return f"{value:.2f} {symbol}"


def parse_html(
    html_source: str,
    domain: str,
    search_term: str,
    rules: list[dict],
) -> list[dict[str, Any]]:
    """Parse MediaMarkt search/category results from their Schema.org ItemList."""
    soup = BeautifulSoup(html_source, "lxml")
    item_list = next(
        (item for item in _json_ld_objects(html_source) if item.get("@type") == "ItemList"),
        None,
    )
    rows: list[dict[str, Any]] = []
    for entry in (item_list or {}).get("itemListElement", []):
        if not isinstance(entry, dict):
            continue
        product = entry.get("item", entry)
        if not isinstance(product, dict) or product.get("@type") not in {
            "Product",
            "ProductGroup",
        }:
            continue
        name = normalize_ws(str(product.get("name", "")))
        if not name:
            continue
        offer = _offer(product)
        price_value = _price(offer)
        currency_code = str(
            offer.get("priceCurrency") or DOMAIN_TO_CURRENCY.get(domain, "EUR")
        ).upper()
        currency_symbol = canonical_currency_symbol(currency_code)
        rating, review_count = _rating(product)
        product_url = canonicalize_url(product.get("url") or offer.get("url"), domain)
        rows.append(
            {
                "platform": "mediamarkt",
                "marketplace": domain,
                "product_type": classify_product(name, rules, search_term),
                "search_term": search_term,
                "origin_country": MEDIAMARKT_MARKETPLACES.get(domain, domain),
                "audience": None,
                "brand": _brand(product, name),
                "product_name": name,
                "product_id": str(product.get("sku") or extract_product_id(product_url) or "")
                or None,
                "currency_code": currency_code,
                "currency_symbol": currency_symbol,
                "currency": currency_symbol,
                "price_text": _money_text(price_value, currency_code),
                "price": _money_text(price_value, currency_code),
                "price_value": price_value,
                "price_usd": convert_to_usd(price_value, currency_code),
                "rating": rating,
                "review_count": review_count,
                "sponsored": False,
                "seller": None,
                "condition": _schema_name(offer.get("itemCondition")),
                "shipping_price_text": None,
                "shipping_price_value": None,
                "buying_format": "retail",
                "color": product.get("color"),
                "availability": _schema_name(offer.get("availability")),
                "image_url": _image(product),
                "detail_enriched": False,
                "product_url": product_url,
                "link": product_url,
                "scraped_at": utc_now(),
            }
        )
    # Rendered cards are authoritative: load-more often leaves SEO JSON-LD unchanged.
    # Join metadata by canonical URL, never by position, and do not append stale SEO rows.
    listing = soup.select_one('[data-test="mms-search-srp-productlist"], '
                              '[data-testid="mms-search-srp-productlist"]')
    cards = (listing if listing is not None else soup).select('[data-test="mms-product-card"], [data-testid="mms-product-card"], '
                        '[data-test="product-card"], [data-testid="product-card"]')
    if not cards:
        return rows
    metadata = {row["product_url"]: row for row in rows}
    rendered = []
    for card in cards:
        title = card.select_one('[data-test="product-title"], [data-testid="product-title"], h2, h3')
        link = card.select_one('a[href*="/product/"]')
        if not title or not link:
            continue
        url = canonicalize_url(link.get("href"), domain)
        name = normalize_ws(title.get_text(" ", strip=True))
        row = metadata.get(url, {}).copy()
        price = card.select_one('[data-test="mms-price"], [data-testid="mms-price"], '
                                '[data-test="price"], [itemprop="price"]')
        if price:
            # Remove RRP, previous prices, legal/shipping text and financing offers.
            price = BeautifulSoup(str(price), "lxml")
            for node in price.select(
                '[data-test*="strike"], [data-test*="additional-info"], button, del, s'
            ):
                node.decompose()
            text = next(
                (value for value in price.stripped_strings
                 if "%" not in value and re.search(r"\d", value)),
                "",
            )
            text = text.replace("’", "").replace("'", "")
            price_value = normalize_price_number(text)
        else:
            text, price_value = None, None
        code = DOMAIN_TO_CURRENCY[domain]
        symbol = canonical_currency_symbol(code)
        rating = card.select_one('[data-test="mms-customer-rating"]')
        count = card.select_one('[data-test="mms-customer-rating-count"]')
        image = card.select_one('img[src]')
        seller = card.select_one('[data-test="mms-third-party-provider-link"]')
        row.update({
            "platform": "mediamarkt", "marketplace": domain, "search_term": search_term,
            "product_type": classify_product(name, rules, search_term),
            "origin_country": MEDIAMARKT_MARKETPLACES[domain],
            "product_name": name, "product_url": url, "link": url,
            "product_id": extract_product_id(url), "currency_code": code,
            "currency_symbol": symbol, "currency": symbol,
            "price_text": text, "price": text, "price_value": price_value,
            "price_usd": convert_to_usd(price_value, code),
            "rating": row.get("rating") if row.get("rating") is not None else
                normalize_price_number(rating.get("aria-label", "") if rating else ""),
            "review_count": row.get("review_count") if row.get("review_count") is not None
                else int(re.sub(r"\D", "", count.get_text()) or "0") if count else None,
            "seller": seller.get_text(" ", strip=True) if seller else None,
            "sponsored": bool(re.search(
                r"\b(gesponsert|sponsored|sponsorisé|sponsorizzato|patrocinado|"
                r"sponsorowane|szponzorált|sponsorlu|gesponsord)\b",
                card.get_text(" ", strip=True), re.IGNORECASE,
            )),
            "image_url": image.get("src") if image else row.get("image_url"),
            "detail_enriched": False, "buying_format": "retail", "scraped_at": utc_now(),
        })
        rendered.append(row)
    return rendered


def listing_state(html_source: str) -> dict[str, Any]:
    """Read the storefront's explicit loaded/total counter, not an assumed batch size."""
    soup = BeautifulSoup(html_source, "lxml")
    grid = soup.select_one('[data-test="mms-search-srp-productlist"], '
                           '[data-testid="mms-search-srp-productlist"]')
    counter = soup.select_one('[data-test="loading-test"], [data-testid="loading-test"]')
    text = counter.get_text(" ", strip=True) if counter else ""
    # e.g. "12 von 3169", "12 / 518 termék", "24 of 300 products"; trailing words allowed.
    match = re.fullmatch(
        r"\s*(\d[\d.,\s]*?)\s*(?:von|of|sur|de|van|di|z|/|out of|из|od|av|af)\s*(\d[\d.,\s]*?)"
        r"(?:\s*[^\d\s][^\d]*)?\s*",
        text, re.IGNORECASE,
    )
    loaded, total = (None, None)
    if match:
        loaded, total = [int(re.sub(r"\D", "", value)) for value in match.groups()]
        if loaded > total:
            loaded, total = None, None
    return {"grid_present": grid is not None, "loaded": loaded, "total": total,
            "counter": text, "card_count": len(grid.select(
                '[data-test="mms-product-card"], [data-testid="mms-product-card"], '
                '[data-test="product-card"], [data-testid="product-card"]'
            )) if grid else 0}


def next_page_url(html_source: str, current_url: str) -> str | None:
    """Follow the site's actual next link (including category redirects), same host only."""
    soup = BeautifulSoup(html_source, "lxml")
    for link in soup.select('link[rel="next"][href], a[rel="next"][href]'):
        url = urljoin(current_url, link["href"])
        if (urlsplit(url).scheme == "https"
                and urlsplit(url).netloc == urlsplit(current_url).netloc
                and url != current_url):
            return url
    current_parts = urlsplit(current_url)
    current_query = parse_qs(current_parts.query)
    for link in soup.select('a[href]'):
        url = urljoin(current_url, link["href"])
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if parts.scheme != "https" or parts.netloc != current_parts.netloc or parts.path != current_parts.path:
            continue
        for key in ("page", "p", "pageNumber"):
            try:
                current = int(current_query.get(key, ["1"])[0])
            except ValueError:
                continue
            # Do not follow a different category filter or search that happens to use page=2.
            other = {k: v for k, v in current_query.items() if k != key}
            if (query.get(key) == [str(current + 1)]
                    and {k: v for k, v in query.items() if k != key} == other):
                return url
    return None


def parse_product_detail(html_source: str, domain: str) -> dict[str, Any]:
    """Parse explicit MediaMarkt product evidence from BuyAction/ProductGroup JSON-LD."""
    product: dict[str, Any] | None = None
    for item in _json_ld_objects(html_source):
        if item.get("@type") == "BuyAction" and isinstance(item.get("object"), dict):
            product = item["object"]
            break
        if item.get("@type") in {"Product", "ProductGroup"}:
            product = item
    if not product:
        return {}

    offer = _offer(product)
    price_value = _price(offer)
    currency_code = str(
        offer.get("priceCurrency") or DOMAIN_TO_CURRENCY.get(domain, "EUR")
    ).upper()
    product_url = canonicalize_url(product.get("url") or offer.get("url"), domain)
    name = normalize_ws(str(product.get("name", "")))
    rating, review_count = _rating(product)
    shipping = offer.get("shippingDetails")
    if isinstance(shipping, list):
        shipping = next((item for item in shipping if isinstance(item, dict)), {})
    shipping = shipping if isinstance(shipping, dict) else {}
    shipping_rate = shipping.get("shippingRate")
    shipping_rate = shipping_rate if isinstance(shipping_rate, dict) else {}
    try:
        shipping_value = float(shipping_rate.get("value"))
    except (TypeError, ValueError):
        shipping_value = None
    variant = next(
        (
            item
            for item in product.get("hasVariant", [])
            if isinstance(item, dict)
            and str(item.get("sku", "")) == str(product.get("sku", ""))
        ),
        {},
    )
    currency_symbol = canonical_currency_symbol(currency_code)
    return {
        "brand": _brand(product, name),
        "product_name": name or None,
        "product_id": str(product.get("sku") or extract_product_id(product_url) or "")
        or None,
        "currency_code": currency_code,
        "currency_symbol": currency_symbol,
        "currency": currency_symbol,
        "price_text": _money_text(price_value, currency_code),
        "price": _money_text(price_value, currency_code),
        "price_value": price_value,
        "price_usd": convert_to_usd(price_value, currency_code),
        "rating": rating,
        "review_count": review_count,
        "condition": _schema_name(offer.get("itemCondition")),
        "shipping_price_text": _money_text(shipping_value, currency_code),
        "shipping_price_value": shipping_value,
        "color": variant.get("color") or product.get("color"),
        "availability": _schema_name(offer.get("availability")),
        "image_url": _image(product),
        "product_url": product_url,
        "link": product_url,
        "detail_enriched": True,
    }


def _norm_words(text: str) -> list[str]:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).split()


def landing_category_link(html_source: str, current_url: str, term: str) -> str | None:
    """Some storefronts redirect a search to an editorial landing page without a product
    grid (e.g. mediamarkt.nl "Smartphone" -> /specials/mobiele-telefoons). Pick the
    same-host category link that best matches the search term, or None."""
    wanted = _norm_words(term)
    if not wanted:
        return None
    variants = {" ".join(wanted), " ".join(wanted) + "s", " ".join(wanted) + "en"}
    host = urlsplit(current_url).netloc
    best: tuple[tuple[int, int], str] | None = None
    for link in BeautifulSoup(html_source, "lxml").select('a[href*="/category/"]'):
        url = urljoin(current_url, link["href"])
        if urlsplit(url).netloc != host:
            continue
        text = " ".join(_norm_words(link.get_text(" ", strip=True)))
        slug = " ".join(_norm_words(re.sub(r"-\d+\.html$", "", urlsplit(url).path.rsplit("/", 1)[-1])))
        if text in variants:
            level = 3
        elif slug in variants:
            level = 2
        elif all(any(w == t or w + "s" == t for t in text.split()) for w in wanted):
            level = 1
        else:
            continue
        score = (level, -len(text.split()))
        if best is None or score > best[0]:
            best = (score, url)
    return best[1] if best else None
