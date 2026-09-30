import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

from price_lens.core.classification import classify_product, normalize_ws, parse_keywords
from price_lens.core.currency import canonical_currency_symbol, normalize_currency_text
from price_lens.core.schemas import utc_now

from .constants import (
    AMAZON_DOMAINS,
    DOLLAR_DOMAIN_CCY,
    DOMAIN_TO_CCY,
    FX_TO_USD,
    SYMBOL_TO_CCY_UNAMBIGUOUS,
)


def resolve_currency_code(symbol: str, domain: str) -> str:
    """
    Turn a price symbol (e.g. '$', 'AU$', '£') into an ISO currency code.
    Uses domain as tiebreaker for ambiguous '$'.
    Falls back to DOMAIN_TO_CCY if symbol is unrecognised.
    """
    s = (symbol or "").strip()

    # Try exact match first
    if s in SYMBOL_TO_CCY_UNAMBIGUOUS:
        return SYMBOL_TO_CCY_UNAMBIGUOUS[s]

    # Case-insensitive fallback for plain text codes like "usd", "eur"
    s_up = s.upper()
    if s_up in FX_TO_USD:
        return s_up

    # Ambiguous "$" — use domain to decide
    if s in ("$", "US$"):
        return DOLLAR_DOMAIN_CCY.get(domain, "USD")

    # Unknown symbol — fall back to domain default
    return DOMAIN_TO_CCY.get(domain, "USD")

# ─────────────────────────────────────────────────────────────────────────────
# PARSING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_for_path(text):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)[:150]

def extract_currency_dynamic(price_str):
    if not price_str:
        return ""
    match = re.search(r"(\d+(?:[.,]\d+)*)", price_str)
    if not match:
        return ""
    start, end = match.span()
    prefix = price_str[:start].strip()
    return prefix if prefix else price_str[end:].strip()

def parse_price_to_float(price_text):
    if not price_text:
        return None
    s = price_text.replace("\u00a0", " ").strip()
    m = re.search(r"(\d[\d.,]*)", s)
    if not m:
        return None
    num = m.group(1)
    if "." in num and "," in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        parts = num.split(",")
        num = num.replace(",", ".") if len(parts[-1]) in (1, 2) else num.replace(",", "")
    try:
        return float(num)
    except ValueError:
        return None

def convert_to_usd(amount, ccy_code):
    if amount is None:
        return None
    rate = FX_TO_USD.get(ccy_code)
    return round(amount * rate, 2) if rate else None

def parse_kw(text):
    return parse_keywords(text)

# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def extract_title_and_link(card, domain):
    a = card.select_one('[data-cy="title-recipe"] a, h2 a.a-link-normal, h2 a')
    if not a:
        return None, None
    title = normalize_ws(a.get_text())
    href  = a.get("href", "")
    dp    = re.search(r"(/dp/[A-Z0-9]{8,12})", unquote(href))
    if dp:
        href = f"https://{domain}{dp.group(1)}"
    elif href.startswith("/"):
        href = f"https://{domain}{href}"
    return title, href

def extract_primary_price_text(card):
    for price_el in card.select(".a-price"):
        parent_classes = price_el.parent.get("class", []) if price_el.parent else []
        if "a-text-price" in parent_classes:
            continue
        off = price_el.select_one(".a-offscreen")
        if off:
            return normalize_currency_text(
                off.get_text().replace("\u00a0", " ").strip()
            )
    return ""

def extract_rating(card):
    alt = card.select_one(".a-icon-alt")
    if alt:
        m = re.search(r"(\d+(?:\.\d+)?)", alt.get_text())
        return float(m.group(1)) if m else None
    return None


def extract_review_count(card):
    for selector in (".s-underline-text", "[aria-label*='ratings']", "[aria-label*='reviews']"):
        element = card.select_one(selector)
        if not element:
            continue
        text = element.get("aria-label", "") or element.get_text(" ", strip=True)
        match = re.search(r"([\d.,]+)", text)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            return int(digits) if digits else None
    return None


def extract_product_id(card, link):
    asin = normalize_ws(card.get("data-asin", "")).upper()
    if asin:
        return asin
    match = re.search(r"/dp/([A-Z0-9]{8,12})", link or "", flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def is_sponsored(card):
    if card.select_one(".s-sponsored-label-text, [data-component-type='sp-sponsored-result']"):
        return True
    return "sponsored" in card.get_text(" ", strip=True).lower()[:120]

def parse_html(html_source, domain, search_term, rules):
    soup  = BeautifulSoup(html_source, "lxml")
    cards = soup.find_all(attrs={"data-asin": True},
                          class_=re.compile(r"\bs-result-item\b"))
    rows  = []
    for card in cards:
        title, link = extract_title_and_link(card, domain)
        if not title:
            continue
        price_text  = extract_primary_price_text(card)
        # Detect currency from the actual symbol in the price string,
        # using the domain as a tiebreaker for ambiguous symbols like "$"
        raw_symbol  = extract_currency_dynamic(price_text)
        ccy_code    = resolve_currency_code(raw_symbol, domain)
        symbol      = canonical_currency_symbol(ccy_code, raw_symbol)
        price_value = parse_price_to_float(price_text)
        product_id = extract_product_id(card, link)
        scraped_at = utc_now()
        rows.append({
            "platform":       "amazon",
            "marketplace":    domain,
            "product_type":   classify_product(title, rules, search_term),
            "search_term":    search_term,
            "origin_country": AMAZON_DOMAINS.get(domain, domain),
            "product_name":   title,
            "product_id":     product_id,
            "currency_code":  ccy_code,
            "currency_symbol": symbol,
            "currency":       symbol,
            "price_text":     price_text,
            "price":          price_text,
            "price_value":    price_value,
            "price_usd":      convert_to_usd(price_value, ccy_code),
            "rating":         extract_rating(card),
            "review_count":   extract_review_count(card),
            "sponsored":      is_sponsored(card),
            "product_url":    link,
            "link":           link,
            "scraped_at":     scraped_at,
        })
    return rows
