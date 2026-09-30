"""Builder helpers: country groups, product presets, translation gaps, run-time estimate."""
from __future__ import annotations

import math

from .analyst import CATALOG

COUNTRY_GROUPS: dict[str, list[str]] = {
    "DACH": ["Germany", "Austria", "Switzerland"],
    "Big 5 Europe": ["Germany", "France", "Italy", "Spain", "United Kingdom"],
    "Benelux": ["Belgium", "Netherlands", "Luxembourg"],
    "Nordics": ["Sweden", "Denmark", "Norway", "Finland"],
    "Central & Eastern Europe": ["Poland", "Czech Republic", "Slovakia", "Hungary", "Romania",
                                 "Bulgaria", "Croatia", "Slovenia"],
    "North America": ["United States", "Canada", "Mexico"],
    "All available": ["all"],
}

PRODUCT_PRESETS: dict[str, dict] = {
    "Fashion & shoes": {
        "platforms": ["zalando", "amazon", "ebay"],
        "audiences": ["men", "women", "kids"],
        "exclude": ["socks", "laces", "insoles", "shoe bag"],
    },
    "Electronics & appliances": {
        "platforms": ["mediamarkt", "amazon", "ebay"],
        "audiences": [],
        "exclude": ["case", "cover", "screen protector", "cable", "charger", "adapter", "holder"],
    },
}

LANGUAGE_NAMES = {
    "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "nl": "Dutch",
    "pl": "Polish", "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish",
    "pt": "Portuguese", "tr": "Turkish", "cs": "Czech", "sk": "Slovak", "hu": "Hungarian",
    "ro": "Romanian", "bg": "Bulgarian", "hr": "Croatian", "sl": "Slovenian", "el": "Greek",
    "et": "Estonian", "lv": "Latvian", "lt": "Lithuanian", "ja": "Japanese", "ar": "Arabic",
    "en": "English",
}


def countries_on(platform: str) -> set[str]:
    return {info["country"] for info in CATALOG.get(platform, {}).values()}


def apply_country_group(search: dict, group: str) -> list[str]:
    """Set every target's countries to the group (where available). Returns notes."""
    wanted = COUNTRY_GROUPS[group]
    notes = []
    for target in search.get("targets") or []:
        if wanted == ["all"]:
            target["countries"] = ["all"]
            continue
        available = [c for c in wanted if c in countries_on(target["platform"])]
        missing = [c for c in wanted if c not in available]
        target["countries"] = available
        if missing:
            notes.append(f"{target['platform'].title()} has no storefront in: {', '.join(missing)}")
    return notes


def apply_product_preset(search: dict, preset: str) -> list[str]:
    """Pick the preset's platforms (keeping chosen countries where available), audiences and
    exclude words. Returns notes about countries a platform does not cover."""
    config = PRODUCT_PRESETS[preset]
    chosen = []
    for target in search.get("targets") or []:
        for country in target.get("countries") or []:
            if country not in chosen:
                chosen.append(country)
    chosen = chosen or ["Germany"]
    notes, targets = [], []
    for platform in config["platforms"]:
        if "all" in chosen:
            countries = ["all"]
        else:
            countries = [c for c in chosen if c in countries_on(platform)]
            missing = [c for c in chosen if c not in countries]
            if missing:
                notes.append(f"{platform.title()} has no storefront in: {', '.join(missing)}")
        targets.append({"platform": platform, "countries": countries, "platform_options": {}})
    search["targets"] = targets
    search["audiences"] = list(config["audiences"])
    search.pop("split_audiences", None)
    filters = search.setdefault("query", {}).setdefault("filters", {})
    filters["exclude"] = list(dict.fromkeys([*(filters.get("exclude") or []), *config["exclude"]]))
    return notes


def storefronts(search: dict) -> list[tuple[str, str, str, str]]:
    """(platform, domain, country, language) for every storefront a search touches."""
    out = []
    for target in search.get("targets") or []:
        countries = target.get("countries") or []
        for domain, info in CATALOG.get(target.get("platform"), {}).items():
            if "all" in countries or info["country"] in countries:
                out.append((target["platform"], domain, info["country"], info["language"]))
    return out


def missing_translations(search: dict) -> dict[str, list[str]]:
    """Non-English storefront languages with no translated query: {language: [countries]}."""
    translations = (search.get("query") or {}).get("translations") or {}
    gaps: dict[str, list[str]] = {}
    for _, _, country, language in storefronts(search):
        value = translations.get(language)
        if isinstance(value, dict):
            value = value.get("search_term")
        if language != "en" and not (isinstance(value, str) and value.strip()):
            gaps.setdefault(language, [])
            if country not in gaps[language]:
                gaps[language].append(country)
    return gaps


# Rough per-platform behaviour, measured on typical runs; for an order-of-magnitude estimate.
PRODUCTS_PER_PAGE = {"amazon": 22, "ebay": 60, "zalando": 84, "mediamarkt": 12}
SECONDS_PER_PAGE = {"amazon": 8, "ebay": 8, "zalando": 10, "mediamarkt": 18}
SECONDS_PER_STOREFRONT = {"amazon": 25, "ebay": 15, "zalando": 25, "mediamarkt": 30}
SECONDS_PER_DETAIL_PAGE = 6


def estimate_minutes(preview_rows: list[dict], execution: dict) -> int:
    """Very rough run time: storefront start-up + pages x (load + polite delay)."""
    delay = execution.get("delay_seconds") or [2.5, 4.5]
    pause = (float(delay[0]) + float(delay[-1])) / 2
    target = execution.get("products_per_storefront")
    seconds = 0.0
    seen_storefronts = set()
    for row in preview_rows:
        platform = row["platform"]
        queries = max(1, len([a for a in str(row.get("audience") or "").split(",") if a.strip()])) \
            if platform == "zalando" else 1
        per_query = math.ceil(target / queries) if target else None
        pages = (min(20, max(1, math.ceil(per_query / PRODUCTS_PER_PAGE[platform])))
                 if per_query else int(execution.get("pages") or 1))
        seconds += queries * pages * (SECONDS_PER_PAGE[platform] + pause)
        if row["domain"] not in seen_storefronts:
            seen_storefronts.add(row["domain"])
            seconds += SECONDS_PER_STOREFRONT[platform]
            if execution.get("enrich_details") and platform in {"zalando", "mediamarkt"}:
                seconds += int(execution.get("max_detail_products") or 30) * SECONDS_PER_DETAIL_PAGE
    return max(1, round(seconds / 60))
