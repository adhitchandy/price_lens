from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import pandas as pd

from price_lens.core.results import ScrapeOutcome

from .constants import DOMAIN_TO_CURRENCY, ZALANDO_MARKETPLACES

HEALTH_COLUMNS = [
    "marketplace", "country", "audience", "status", "pages_succeeded", "listings_parsed",
    "expected_currency", "observed_currencies", "currency_match", "final_domains",
    "requested_paths", "redirected_outside_marketplace", "error",
]


def _belongs_to_marketplace(final_domain: str, marketplace: str) -> bool:
    return final_domain == marketplace or final_domain.endswith(f".{marketplace}")


def build_health_table(
    outcome: ScrapeOutcome,
    marketplaces: list[str] | tuple[str, ...],
    audiences: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    selected_audiences: tuple[str | None, ...]
    if audiences:
        selected_audiences = tuple(audiences)
    else:
        observed_audiences = dict.fromkeys(
            item.get("audience")
            for item in [*outcome.report.events, *outcome.report.failures]
            if item.get("audience")
        )
        selected_audiences = tuple(observed_audiences) or (None,)
    for domain in marketplaces:
        for audience in selected_audiences:
            events = [
                event
                for event in outcome.report.events
                if event.get("marketplace") == domain
                and event.get("stage") != "audience_route_discovery"
                and event.get("audience") == audience
            ]
            failures = [
                failure
                for failure in outcome.report.failures
                if failure.get("marketplace") == domain
                and (
                    failure.get("audience") == audience
                    or failure.get("stage") == "audience_route_discovery"
                )
            ]
            listings = sum(int(event.get("listings", 0)) for event in events)
            final_domains = sorted(
                {event.get("final_domain", "") for event in events if event.get("final_domain")}
            )
            observed = sorted(
                {
                    currency
                    for event in events
                    for currency in event.get("currency_codes", [])
                }
            )
            expected = DOMAIN_TO_CURRENCY[domain]
            requested_paths = sorted(
                {
                    urlsplit(item.get("requested_url", "")).path
                    for item in [*events, *failures]
                    if item.get("requested_url")
                }
            )
            redirected = any(
                not _belongs_to_marketplace(item, domain) for item in final_domains
            )
            currency_match = expected in observed if observed else None
            if not events:
                status = "failed"
            elif listings == 0 or currency_match is not True or redirected or failures:
                status = "warning"
            else:
                status = "passed"
            rows.append(
                {
                    "marketplace": domain,
                    "country": ZALANDO_MARKETPLACES[domain],
                    "audience": audience or "",
                    "status": status,
                    "pages_succeeded": len(events),
                    "listings_parsed": listings,
                    "expected_currency": expected,
                    "observed_currencies": ", ".join(observed),
                    "currency_match": currency_match,
                    "final_domains": ", ".join(final_domains),
                    "requested_paths": ", ".join(requested_paths),
                    "redirected_outside_marketplace": redirected,
                    "error": " | ".join(
                        failure.get("error", "unknown error") for failure in failures
                    ),
                }
            )
    return pd.DataFrame(rows, columns=HEALTH_COLUMNS)


def health_summary(table: pd.DataFrame) -> dict[str, Any]:
    counts = table["status"].value_counts().to_dict()
    return {
        "marketplaces_checked": int(table["marketplace"].nunique()),
        "audience_checks": len(table),
        "passed": int(counts.get("passed", 0)),
        "warnings": int(counts.get("warning", 0)),
        "failed": int(counts.get("failed", 0)),
        "all_passed": bool(len(table) and (table["status"] == "passed").all()),
        "results": table.to_dict(orient="records"),
    }
