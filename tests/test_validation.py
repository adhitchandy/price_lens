import pytest

from price_lens.core.validation import (
    RequestValidationError,
    parse_amazon_plan,
    parse_ebay_plan,
    parse_mediamarkt_plan,
    parse_zalando_plan,
)

SUPPORTED = {"amazon.de", "amazon.com"}


def test_valid_request_builds_search_config():
    plan = parse_amazon_plan(
        {
            "searches": [
                {
                    "search_term": "digital camera",
                    "product_type": "Digital Camera",
                    "include": ["camera"],
                    "exclude": ["battery"],
                }
            ],
            "marketplaces": ["amazon.de"],
            "pages": 2,
        },
        SUPPORTED,
    )
    assert plan.pages == 2
    assert plan.search_config()["digital camera"][0]["type"] == "Digital Camera"


def test_unknown_marketplace_is_rejected():
    with pytest.raises(RequestValidationError, match="Unsupported marketplace"):
        parse_amazon_plan(
            {
                "searches": [{"search_term": "camera", "product_type": "Camera"}],
                "marketplaces": ["amazon.invalid"],
            },
            SUPPORTED,
        )


def test_excessive_page_count_is_rejected():
    with pytest.raises(RequestValidationError, match="between 1 and 20"):
        parse_amazon_plan(
            {
                "searches": [{"search_term": "camera", "product_type": "Camera"}],
                "marketplaces": ["amazon.de"],
                "pages": 100,
            },
            SUPPORTED,
        )


def test_ebay_plan_uses_the_same_contract():
    plan = parse_ebay_plan(
        {
            "searches": [{"search_term": "camera", "product_type": "Camera"}],
            "marketplaces": ["ebay.de"],
        },
        {"ebay.de"},
    )
    assert plan.search_config()["camera"][0]["type"] == "Camera"


def test_mediamarkt_plan_supports_detail_enrichment():
    plan = parse_mediamarkt_plan(
        {
            "searches": [{"search_term": "pixel", "product_type": "Smartphone"}],
            "marketplaces": ["mediamarkt.de"],
            "enrich_details": True,
            "max_detail_products": 10,
        },
        {"mediamarkt.de"},
    )
    assert plan.enrich_details is True
    assert plan.max_detail_products == 10


def test_zalando_plan_supports_configurable_detail_enrichment():
    plan = parse_zalando_plan(
        {
            "searches": [
                {
                    "search_term": "running shoes",
                    "product_type": "Shoes",
                    "audiences": ["men", "women"],
                }
            ],
            "marketplaces": ["zalando.de"],
            "enrich_details": True,
            "max_detail_products": 25,
        },
        {"zalando.de"},
    )
    assert plan.enrich_details is True
    assert plan.max_detail_products == 25
    assert plan.searches[0].audiences == ("men", "women")


def test_zalando_plan_requires_an_audience():
    with pytest.raises(RequestValidationError, match="audience is required"):
        parse_zalando_plan(
            {
                "searches": [{"search_term": "shoes", "product_type": "Shoes"}],
                "marketplaces": ["zalando.de"],
            },
            {"zalando.de"},
        )
