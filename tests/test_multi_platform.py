import json
from pathlib import Path

import pandas as pd
import pytest

from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport
from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator.analyst import compile_analyst_plan, upgrade_to_v2
from price_lens.orchestrator.audiences import audience_query
from price_lens.orchestrator.localization import collect_localized
from price_lens.orchestrator.registry import MarketplaceAdapter

ROOT = Path(__file__).parents[1]


def plan(audiences=("men", "women"), split=None, overrides=None):
    search = {
        "id": "s1", "product_type": "Sneakers", "audiences": list(audiences),
        "query": {"default": "sneakers", "translations": {"de": "Sneaker", "fr": "baskets"},
                  "filters": {"exclude": ["socks"]}},
        "targets": [
            {"platform": "zalando", "countries": ["Germany", "France"]},
            {"platform": "amazon", "countries": ["Germany", "United Kingdom"]},
            {"platform": "ebay", "countries": ["France"]},
        ],
    }
    if split is not None:
        search["split_audiences"] = split
    if overrides:
        search["query"]["audience_queries"] = overrides
    return {"schema_version": "analyst-v2", "research_question": "Sneakers",
            "execution": {"products_per_storefront": 20}, "searches": [search]}


def test_same_search_runs_on_all_platforms_with_audience_split():
    plans, preview = compile_analyst_plan(plan(overrides={"de": {"women": "Damen Sneaker Low"}}))
    research = plans[0]
    assert research.platforms == ("zalando", "amazon", "ebay")
    zalando = research.platform_plan("zalando").searches
    assert [(s.search_term, s.audiences) for s in zalando] == [("sneakers", ("men", "women"))]
    amazon = research.platform_plan("amazon").searches
    assert [s.search_term for s in amazon] == ["men's sneakers", "women's sneakers"]
    queries = {(r["domain"], r["audience"]): r["query"] for r in preview}
    assert queries[("amazon.de", "men")] == "Herren Sneaker"
    assert queries[("amazon.de", "women")] == "Damen Sneaker Low"      # explicit override
    assert queries[("amazon.co.uk", "women")] == "women's sneakers"
    assert queries[("ebay.fr", "men")] == "baskets homme"
    assert queries[("zalando.de", "men, women")] == "Sneaker"
    assert all("socks" in r["exclude"] for r in preview)


def test_no_split_or_no_audience_runs_plain_query_elsewhere():
    _, preview = compile_analyst_plan(plan(split=False))
    assert {r["query"] for r in preview if r["platform"] == "amazon"} == {"Sneaker", "sneakers"}
    _, preview = compile_analyst_plan(plan(audiences=()))
    zalando = [r for r in preview if r["platform"] == "zalando"]
    assert zalando[0]["audience"] == "men, women, kids"  # Zalando defaults to all shops
    assert {r["audience"] for r in preview if r["platform"] != "zalando"} == {""}


def test_bad_audience_fields_are_rejected():
    bad = plan()
    bad["searches"][0]["audiences"] = ["teens"]
    with pytest.raises(RequestValidationError, match="audiences"):
        compile_analyst_plan(bad)
    bad = plan(overrides={"de": {"boys": "Jungen"}})
    with pytest.raises(RequestValidationError, match="audience_queries"):
        compile_analyst_plan(bad)


def test_audience_templates():
    assert audience_query("Sneaker", "kids", "de") == "Kinder Sneaker"
    assert audience_query("baskets", "women", "fr") == "baskets femme"
    assert audience_query("x", "men", "zz") == "men's x"  # unknown language -> English


def test_amazon_rows_are_tagged_with_their_audience():
    plans, _ = compile_analyst_plan(plan())
    amazon_plan = plans[0].platform_plan("amazon")

    def collect(subplan, _log):
        rows = [{"marketplace": subplan.marketplaces[0], "search_term": s.search_term,
                 "product_name": "shoe"} for s in subplan.searches]
        return ScrapeOutcome(pd.DataFrame(rows), ScrapeReport(platform="amazon", status="completed"))

    outcome = collect_localized(MarketplaceAdapter("amazon", collect), amazon_plan, lambda _m: None)
    tagged = set(zip(outcome.raw_products["search_term"], outcome.raw_products["audience"]))
    assert ("Herren Sneaker", "men") in tagged and ("women's sneakers", "women") in tagged


def test_v1_audiences_stay_zalando_only_after_upgrade():
    v1 = json.loads((ROOT / "examples/analyst_plan.json").read_text())
    v2 = upgrade_to_v2(v1)
    assert v2["searches"][0]["split_audiences"] is False
    _, preview = compile_analyst_plan(v2)
    assert {r["audience"] for r in preview if r["platform"] == "amazon"} == {""}


def test_builder_supports_several_platforms_per_search():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "apps/unified_app.py"), default_timeout=60).run()
    platforms = next(w for w in app.multiselect if w.label == "Platforms")
    platforms.set_value(["mediamarkt", "amazon"]).run()
    amazon = next(w for w in app.multiselect if w.label == "Countries on Amazon")
    amazon.set_value(["Germany", "France"]).run()
    assert not app.exception
    targets = app.session_state["plan"]["searches"][0]["targets"]
    assert [(t["platform"], t["countries"]) for t in targets] == [
        ("mediamarkt", ["Germany"]), ("amazon", ["Germany", "France"])]
    run = next(b for b in app.button if b.label == "🚀 Run scraper")
    assert not run.disabled
