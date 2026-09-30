import pandas as pd
import pytest

from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport
from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator.localization import collect_localized
from price_lens.orchestrator.registry import MarketplaceAdapter
from price_lens.orchestrator.validation import parse_research_plan


@pytest.mark.parametrize("platform,domains", [
    ("amazon", ["amazon.de", "amazon.fr"]),
    ("ebay", ["ebay.de", "ebay.fr"]),
    ("zalando", ["zalando.de", "zalando.fr"]),
    ("mediamarkt", ["mediamarkt.de", "mediamarkt.es"]),
])
def test_localized_query_is_executed_only_on_its_domain(platform, domains):
    overrides = {
        domains[0]: {"search_term": "Laufschuhe", "language": "de"},
        domains[1]: {"search_term": "chaussures" if platform != "mediamarkt" else "zapatillas",
                     "language": "fr" if platform != "mediamarkt" else "es"},
    }
    plan = parse_research_plan({
        "research_question": "Shoes", "marketplaces": {platform: domains},
        "require_localized_queries": True,
        "searches": [{"search_term": "running shoes", "product_type": "Shoes",
                      "include": ["running"], "audiences": ["men"],
                      "localized_queries": overrides}],
    })
    calls = []

    def collect(subplan, log):
        domain = subplan.marketplaces[0]
        calls.append(domain)
        search = subplan.searches[0]
        assert search.search_term == overrides[domain]["search_term"]
        assert search.rule.include == ()  # No accidental English filtering.
        return ScrapeOutcome(pd.DataFrame([{
            "marketplace": domain, "search_term": search.search_term, "product_name": "shoe",
        }]), ScrapeReport(platform=platform, status="completed", pages_succeeded=1))

    outcome = collect_localized(MarketplaceAdapter(platform, collect),
                                plan.platform_plan(platform), lambda _: None)
    assert calls == domains
    assert list(outcome.raw_products["source_search_term"]) == ["running shoes"] * 2
    assert list(outcome.raw_products["query_language"]) == [
        overrides[d]["language"] for d in domains
    ]
    assert plan.to_dict()["require_localized_queries"] is True


def test_missing_domain_translation_fails_before_browser():
    with pytest.raises(RequestValidationError, match="missing localized_queries"):
        parse_research_plan({
            "research_question": "Shoes", "marketplaces": {"amazon": ["amazon.de"]},
            "require_localized_queries": True,
            "searches": [{"search_term": "shoes", "product_type": "Shoes"}],
        })
