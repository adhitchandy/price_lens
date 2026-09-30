import pandas as pd
import pytest

from price_lens.core.currency import (
    detect_currency,
    normalize_currency_text,
    normalize_price_number,
)
from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport
from price_lens.marketplaces.ebay.constants import (
    DOMAIN_TO_CURRENCY,
    EBAY_MARKETPLACES,
)
from price_lens.marketplaces.ebay.health import build_health_table, health_summary
from price_lens.marketplaces.ebay.scraper import build_search_url

PRICE_SAMPLES = {
    "ebay.com": ("$1,234.56", 1234.56),
    "ebay.co.uk": ("£1,234.56", 1234.56),
    "ebay.de": ("EUR 1.234,56", 1234.56),
    "ebay.fr": ("1 234,56 EUR", 1234.56),
    "ebay.it": ("EUR 1.234,56", 1234.56),
    "ebay.es": ("1.234,56 EUR", 1234.56),
    "ebay.ca": ("C $1,234.56", 1234.56),
    "ebay.com.au": ("AU $1,234.56", 1234.56),
    "ebay.at": ("EUR 1.234,56", 1234.56),
    "ebay.nl": ("EUR 1.234,56", 1234.56),
    "ebay.ie": ("EUR 1,234.56", 1234.56),
}


@pytest.mark.parametrize("domain", list(EBAY_MARKETPLACES))
def test_every_configured_domain_has_currency_and_local_price_sample(domain):
    assert domain in DOMAIN_TO_CURRENCY
    text, expected_value = PRICE_SAMPLES[domain]
    currency, _symbol = detect_currency(text, DOMAIN_TO_CURRENCY[domain])
    assert currency == DOMAIN_TO_CURRENCY[domain]
    assert normalize_price_number(text) == expected_value


def test_iso_euro_and_windows_mojibake_use_canonical_symbol():
    assert detect_currency("EUR 59,95", "EUR") == ("EUR", "€")
    assert detect_currency("â‚¬59,95", "EUR") == ("EUR", "€")
    assert normalize_currency_text("â‚¬59,95") == "€59,95"


def test_health_table_passes_complete_domain_matrix():
    report = ScrapeReport(platform="ebay")
    report.events = [
        {
            "marketplace": domain,
            "status": "succeeded",
            "listings": 20,
            "final_domain": domain,
            "currency_codes": [DOMAIN_TO_CURRENCY[domain]],
        }
        for domain in EBAY_MARKETPLACES
    ]
    table = build_health_table(ScrapeOutcome(pd.DataFrame(), report), list(EBAY_MARKETPLACES))
    summary = health_summary(table)
    assert summary["marketplaces_checked"] == len(EBAY_MARKETPLACES)
    assert summary["all_passed"] is True


def test_health_table_warns_on_cross_domain_redirect():
    report = ScrapeReport(platform="ebay")
    report.events = [
        {
            "marketplace": "ebay.ie",
            "status": "succeeded",
            "listings": 20,
            "final_domain": "ebay.com",
            "currency_codes": ["EUR"],
        }
    ]
    table = build_health_table(ScrapeOutcome(pd.DataFrame(), report), ["ebay.ie"])
    assert table.iloc[0]["status"] == "warning"
    assert bool(table.iloc[0]["redirected_outside_marketplace"]) is True


def test_first_page_url_matches_manual_search_structure_without_tracking_fields():
    url = build_search_url("ebay.de", "mirrorless camera", 1)
    assert url == (
        "https://www.ebay.de/sch/i.html?"
        "_nkw=mirrorless+camera&_sacat=0&_from=R40"
    )
    assert "_pgn" not in url
    assert "_trksid" not in url
    assert "_odkw" not in url


def test_later_page_url_adds_page_number():
    url = build_search_url("ebay.de", "mirrorless camera", 3)
    assert "_pgn=3" in url
