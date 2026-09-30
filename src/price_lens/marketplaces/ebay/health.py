from __future__ import annotations

from typing import Any

import pandas as pd

from price_lens.core.results import ScrapeOutcome

from .constants import DOMAIN_TO_CURRENCY, EBAY_MARKETPLACES

HEALTH_COLUMNS = [
    "marketplace",
    "country",
    "status",
    "pages_succeeded",
    "listings_parsed",
    "expected_currency",
    "observed_currencies",
    "currency_match",
    "final_domains",
    "redirected_outside_marketplace",
    "error",
]


def build_health_table(
    outcome: ScrapeOutcome, marketplaces: list[str] | tuple[str, ...]
) -> pd.DataFrame:
    events = outcome.report.events
    failures = outcome.report.failures
    rows: list[dict[str, Any]] = []
    for domain in marketplaces:
        domain_events = [event for event in events if event["marketplace"] == domain]
        domain_failures = [failure for failure in failures if failure["marketplace"] == domain]
        listings = sum(int(event.get("listings", 0)) for event in domain_events)
        final_domains = sorted(
            {event.get("final_domain", "") for event in domain_events if event.get("final_domain")}
        )
        observed = sorted(
            {
                currency
                for event in domain_events
                for currency in event.get("currency_codes", [])
            }
        )
        expected = DOMAIN_TO_CURRENCY[domain]
        redirected = any(final_domain != domain for final_domain in final_domains)
        currency_match = expected in observed if observed else None

        if not domain_events:
            status = "failed"
        elif listings == 0 or currency_match is None or redirected or currency_match is False or domain_failures:
            status = "warning"
        else:
            status = "passed"

        rows.append(
            {
                "marketplace": domain,
                "country": EBAY_MARKETPLACES[domain],
                "status": status,
                "pages_succeeded": len(domain_events),
                "listings_parsed": listings,
                "expected_currency": expected,
                "observed_currencies": ", ".join(observed),
                "currency_match": currency_match,
                "final_domains": ", ".join(final_domains),
                "redirected_outside_marketplace": redirected,
                "error": " | ".join(
                    failure.get("error", "unknown error") for failure in domain_failures
                ),
            }
        )
    return pd.DataFrame(rows, columns=HEALTH_COLUMNS)


def health_summary(table: pd.DataFrame) -> dict[str, Any]:
    counts = table["status"].value_counts().to_dict()
    return {
        "marketplaces_checked": len(table),
        "passed": int(counts.get("passed", 0)),
        "warnings": int(counts.get("warning", 0)),
        "failed": int(counts.get("failed", 0)),
        "all_passed": bool(len(table) and (table["status"] == "passed").all()),
        "results": table.to_dict(orient="records"),
    }
