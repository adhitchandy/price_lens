from __future__ import annotations

import re

DEFAULT_ACCESSORY_KEYWORDS = (
    "case",
    "mount",
    "battery",
    "charger",
    "stand",
    "cable",
    "pouch",
    "holder",
    "adapter",
)


def normalize_ws(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_keywords(value: str | None) -> list[str]:
    return [item.strip().lower() for item in (value or "").split(",") if item.strip()]


def classify_product(
    title: str | None,
    rules: list[dict],
    search_term: str,
    accessory_keywords: tuple[str, ...] = DEFAULT_ACCESSORY_KEYWORDS,
) -> str:
    normalized_title = (title or "").lower()
    for rule in rules:
        if any(excluded in normalized_title for excluded in rule.get("exclude", [])):
            continue
        include = rule.get("include", [])
        if not include or any(included in normalized_title for included in include):
            return rule["type"]
    if any(keyword in normalized_title for keyword in accessory_keywords):
        return f"{search_term.title()} (Accessory)"
    return f"{search_term.title()} (Other)"
