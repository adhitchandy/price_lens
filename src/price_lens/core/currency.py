from __future__ import annotations

import re

FX_TO_USD = {
    "USD": 1.0,
    "EUR": 1.167,
    "GBP": 1.364,
    "CAD": 0.731,
    "AUD": 0.6495,
    "JPY": 0.006883,
    "INR": 0.0114,
    "SEK": 0.1051,
    "PLN": 0.2679,
    "TRY": 0.0197,
    "AED": 0.2723,
    "SAR": 0.2667,
    "EGP": 0.0194,
    "SGD": 0.7857,
    "BRL": 0.1696,
    "MXN": 0.0530,
    "BGN": 0.5966,
    "CHF": 1.2600,
    "CZK": 0.0478,
    "DKK": 0.1564,
    "HUF": 0.00302,
    "NOK": 0.1160,
    "RON": 0.2300,
}

SYMBOL_TO_CURRENCY = {
    "£": "GBP",
    "€": "EUR",
    "¥": "JPY",
    "₹": "INR",
    "ZŁ": "PLN",
    "SEK": "SEK",
    "₺": "TRY",
    "AED": "AED",
    "SAR": "SAR",
    "EGP": "EGP",
    "S$": "SGD",
    "R$": "BRL",
    "MX$": "MXN",
    "BGN": "BGN",
    "CHF": "CHF",
    "KČ": "CZK",
    "CZK": "CZK",
    "DKK": "DKK",
    "HUF": "HUF",
    "NOK": "NOK",
    "LEI": "RON",
    "RON": "RON",
    "CA$": "CAD",
    "C$": "CAD",
    "AU$": "AUD",
    "A$": "AUD",
}

CURRENCY_TO_SYMBOL = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "INR": "₹",
    "PLN": "zł",
    "TRY": "₺",
    "SGD": "S$",
    "BRL": "R$",
    "MXN": "MX$",
    "CAD": "C$",
    "AUD": "A$",
}

_MOJIBAKE_REPLACEMENTS = {
    "â‚¬": "€",
    "Â£": "£",
    "Â¥": "¥",
    "â‚¹": "₹",
    "â‚º": "₺",
}


def normalize_currency_text(value: str | None) -> str:
    """Repair common Windows/Excel mojibake without changing other listing text."""
    text = value or ""
    for broken, replacement in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(broken, replacement)
    return text


def canonical_currency_symbol(currency_code: str, fallback: str = "") -> str:
    """Return a display symbol while keeping the ISO code in its own column."""
    code = (currency_code or "").upper()
    return CURRENCY_TO_SYMBOL.get(code, fallback or code)


def normalize_price_number(price_text: str | None) -> float | None:
    if not price_text:
        return None
    price_text = normalize_currency_text(price_text)
    match = re.search(r"(\d[\d\s.,]*)", price_text.replace("\u00a0", " "))
    if not match:
        return None
    number = match.group(1).strip().replace(" ", "")
    if "." in number and "," in number:
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif "," in number:
        tail = number.rsplit(",", 1)[-1]
        number = number.replace(",", ".") if len(tail) in (1, 2) else number.replace(",", "")
    try:
        return float(number)
    except ValueError:
        return None


def detect_currency(price_text: str | None, default: str) -> tuple[str, str]:
    text = normalize_currency_text(price_text).upper().strip()
    for code in FX_TO_USD:
        if re.search(rf"\b{re.escape(code)}\b", text):
            return code, canonical_currency_symbol(code)
    for symbol, code in sorted(SYMBOL_TO_CURRENCY.items(), key=lambda item: -len(item[0])):
        if symbol in text:
            return code, canonical_currency_symbol(code, symbol)
    if "$" in text:
        return default if default in {"USD", "CAD", "AUD", "SGD", "MXN"} else "USD", "$"
    return default, canonical_currency_symbol(default)


def convert_to_usd(amount: float | None, currency_code: str) -> float | None:
    if amount is None:
        return None
    rate = FX_TO_USD.get(currency_code)
    return round(amount * rate, 2) if rate is not None else None
