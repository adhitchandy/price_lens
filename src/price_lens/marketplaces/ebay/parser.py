from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from price_lens.core.classification import classify_product, normalize_ws
from price_lens.core.currency import (
    convert_to_usd,
    detect_currency,
    normalize_price_number,
)
from price_lens.core.schemas import utc_now

from .constants import DOMAIN_TO_CURRENCY, EBAY_MARKETPLACES


def canonicalize_url(url: str | None, domain: str | None = None) -> str | None:
    if not url:
        return None
    if url.startswith("/") and domain:
        url = f"https://www.{domain}{url}"
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def extract_item_id(url: str | None, card) -> str | None:
    legacy_id = normalize_ws(card.get("data-view", ""))
    match = re.search(r"(?:itemId|iid)[:=](\d{9,15})", legacy_id, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"/itm/(?:[^/?]+/)?(\d{9,15})", url or "", re.IGNORECASE)
    return match.group(1) if match else None


def _text(card, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        element = card.select_one(selector)
        if element:
            value = normalize_ws(element.get_text(" ", strip=True))
            if value:
                return value
    return ""


def extract_rating(card) -> float | None:
    text = _text(card, (".x-star-rating .clipped", ".s-item__reviews", "[aria-label*='stars']"))
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(match.group(1).replace(",", ".")) if match else None


def extract_review_count(card) -> int | None:
    text = _text(card, (".s-item__reviews-count", ".s-item__reviews"))
    match = re.search(r"([\d.,]+)", text)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else None


def _listing_cards(soup: BeautifulSoup) -> list:
    selectors = (
        "li.s-item, li.s-card, div.s-item, div.s-card, .su-card-container, "
        "[data-testid='item-card'], [data-testid='item-list-card']"
    )
    cards = soup.select(selectors)
    if not cards:
        for link in soup.select("a[href*='/itm/']"):
            candidate = link
            for _level in range(8):
                candidate = candidate.parent
                if candidate is None:
                    break
                if candidate.select_one(".s-item__price, .s-card__price, [class*='price']"):
                    cards.append(candidate)
                    break
    seen: set[int] = set()
    unique = []
    for card in cards:
        identity = id(card)
        if identity not in seen:
            seen.add(identity)
            unique.append(card)
    return unique


def parse_html(html_source: str, domain: str, search_term: str, rules: list[dict]) -> list[dict]:
    soup = BeautifulSoup(html_source, "lxml")
    rows = []
    for card in _listing_cards(soup):
        link_element = card.select_one(
            "a.s-item__link, a.s-card__link, [data-testid='item-link'], a[href*='/itm/']"
        )
        title = _text(
            card,
            (
                ".s-item__title",
                ".s-card__title",
                "[data-testid='item-title']",
                "[role='heading']",
                "h3",
            ),
        )
        title = re.sub(r"^New Listing\s*", "", title, flags=re.IGNORECASE)
        if not title or title.lower() == "shop on ebay" or not link_element:
            continue

        product_url = canonicalize_url(link_element.get("href"), domain)
        price_text = _text(
            card,
            (".s-item__price", ".s-card__price", "[data-testid='item-price']"),
        )
        default_currency = DOMAIN_TO_CURRENCY.get(domain, "USD")
        currency_code, currency_symbol = detect_currency(price_text, default_currency)
        price_value = normalize_price_number(price_text)
        shipping_text = _text(
            card,
            (".s-item__shipping", ".s-item__logisticsCost", ".s-card__shipping"),
        )
        shipping_value = 0.0 if "free" in shipping_text.lower() else normalize_price_number(shipping_text)
        bids_text = _text(card, (".s-item__bids", ".s-card__bids"))
        rows.append(
            {
                "platform": "ebay",
                "marketplace": domain,
                "product_type": classify_product(title, rules, search_term),
                "search_term": search_term,
                "origin_country": EBAY_MARKETPLACES.get(domain, domain),
                "product_name": title,
                "product_id": extract_item_id(product_url, card),
                "currency_code": currency_code,
                "currency_symbol": currency_symbol,
                "currency": currency_symbol,
                "price_text": price_text,
                "price": price_text,
                "price_value": price_value,
                "price_usd": convert_to_usd(price_value, currency_code),
                "rating": extract_rating(card),
                "review_count": extract_review_count(card),
                "sponsored": "sponsored" in card.get_text(" ", strip=True).lower(),
                "seller": _text(card, (".s-item__seller-info-text", ".s-item__seller-info")),
                "condition": _text(card, (".SECONDARY_INFO", ".s-item__subtitle", ".s-card__subtitle")),
                "shipping_price_text": shipping_text,
                "shipping_price_value": shipping_value,
                "buying_format": "auction" if bids_text else "buy_it_now",
                "product_url": product_url,
                "link": product_url,
                "scraped_at": utc_now(),
            }
        )
    return rows
