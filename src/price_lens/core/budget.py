"""Stop collecting once a storefront has delivered the requested number of products."""
from __future__ import annotations

import math
from collections.abc import Iterable


def _key(row: dict) -> str:
    return str(row.get("product_id") or row.get("product_url") or row.get("product_name") or "")


def collected_count(rows: Iterable[dict], domain: str, term: str, audience: str | None = None) -> int:
    """Unique products already collected for one storefront + search term (+ audience)."""
    keys = {
        _key(row)
        for row in rows
        if row.get("marketplace") == domain
        and row.get("search_term") == term
        and (audience is None or row.get("audience") == audience)
    }
    keys.discard("")
    return len(keys)


def per_audience_target(max_products: int | None, audiences: int) -> int | None:
    if not max_products:
        return None
    return max(1, math.ceil(max_products / max(1, audiences)))
