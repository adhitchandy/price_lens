import pandas as pd
import pytest

from price_lens.cli import build_parser
from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport
from price_lens.marketplaces.zalando.constants import (
    DOMAIN_TO_CURRENCY,
    ZALANDO_MARKETPLACES,
)
from price_lens.marketplaces.zalando.health import build_health_table, health_summary
from price_lens.marketplaces.zalando.parser import search_audience_path
from price_lens.marketplaces.zalando.scraper import build_search_url


def test_all_28_markets_have_expected_currencies():
    assert len(ZALANDO_MARKETPLACES) == 28
    assert set(DOMAIN_TO_CURRENCY) == set(ZALANDO_MARKETPLACES)
    assert DOMAIN_TO_CURRENCY["zalando.bg"] == "EUR"
    assert DOMAIN_TO_CURRENCY["zalando.hr"] == "EUR"
    assert DOMAIN_TO_CURRENCY["zalando.co.uk"] == "GBP"


def test_search_url_is_locale_neutral_and_encodes_pagination():
    assert build_search_url("zalando.de", "running shoes", 1, "men") == (
        "https://www.zalando.de/men/?q=running+shoes"
    )
    assert build_search_url("zalando.fr", "running shoes", 3, "women").endswith(
        "/women/?q=running+shoes&p=3"
    )


def test_discovered_localized_route_and_language_host_are_preserved():
    assert build_search_url(
        "zalando.at",
        "running shoes",
        1,
        "men",
        "https://www.zalando.at/herren/",
    ) == "https://www.zalando.at/herren/?q=running+shoes"


@pytest.mark.parametrize(
    ("domain", "audience", "discovered", "expected"),
    [
        ("zalando.hr", "men", "/muskarci/", "/katalog-muskarci/"),
        ("zalando.ee", "men", "/mehed/", "/kataloog-mehed/"),
        ("zalando.gr", "women", "/gynaikes/", "/gynaikeia/"),
        ("zalando.gr", "men", "/andres/", "/andrika/"),
        ("zalando.hu", "men", "/ferfi/", "/katalogus-ferfi/"),
        ("zalando.lv", "men", "/viriesiem/", "/katalogs-viriesiem/"),
        ("zalando.lt", "men", "/vyrams/", "/katalogas-vyrams/"),
        ("zalando.pt", "men", "/homem/", "/catalogo-homem/"),
        ("zalando.ro", "women", "/femei/", "/catalog-femei/"),
        ("zalando.sk", "men", "/muzi/", "/katalog-muzi/"),
        ("zalando.si", "men", "/moski/", "/katalog-moski/"),
    ],
)
def test_localized_catalog_route_transformations(
    domain, audience, discovered, expected
):
    assert search_audience_path(domain, audience, discovered) == expected


def test_health_accepts_language_subdomain_for_same_marketplace():
    report = ScrapeReport(platform="zalando")
    report.events = [
        {
            "marketplace": "zalando.de", "status": "succeeded", "listings": 40,
            "final_domain": "en.zalando.de", "currency_codes": ["EUR"],
        }
    ]
    table = build_health_table(ScrapeOutcome(pd.DataFrame(), report), ["zalando.de"])
    assert table.iloc[0]["status"] == "passed"
    assert health_summary(table)["all_passed"] is True


def test_health_builds_one_row_per_marketplace_and_audience():
    report = ScrapeReport(platform="zalando")
    report.events = [
        {
            "marketplace": domain,
            "audience": audience,
            "status": "succeeded",
            "listings": 40,
            "final_domain": domain,
            "currency_codes": [DOMAIN_TO_CURRENCY[domain]],
            "requested_url": f"https://www.{domain}/{audience}/?q=shoes",
        }
        for domain in ("zalando.de", "zalando.fr")
        for audience in ("women", "kids")
    ]
    table = build_health_table(
        ScrapeOutcome(pd.DataFrame(), report),
        ["zalando.de", "zalando.fr"],
        ["women", "kids"],
    )
    summary = health_summary(table)

    assert len(table) == 4
    assert set(table["audience"]) == {"women", "kids"}
    assert summary["marketplaces_checked"] == 2
    assert summary["audience_checks"] == 4
    assert summary["all_passed"] is True


def test_health_cli_accepts_audience_subset_without_retesting_men():
    args = build_parser().parse_args(
        ["check-zalando-marketplaces", "--audiences", "women", "kids"]
    )

    assert args.audiences == ["women", "kids"]
    assert args.audience == "men"

