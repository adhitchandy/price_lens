from pathlib import Path

from price_lens.marketplaces.zalando.parser import (
    discover_audience_paths,
    parse_html,
    parse_product_detail,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_search_fixture_extracts_brand_name_and_current_price():
    html = (FIXTURES / "zalando_search_page.html").read_text(encoding="utf-8")
    rules = [{"type": "Running Shoes", "include": [], "exclude": []}]
    rows = parse_html(html, "zalando.de", "running shoes", rules, "men")

    assert len(rows) == 2
    assert rows[0]["platform"] == "zalando"
    assert rows[0]["audience"] == "men"
    assert rows[0]["brand"] == "On"
    assert rows[0]["product_name"] == "CLOUD 6 - Trainers - midnight white"
    assert rows[0]["product_id"] == "ONM12P000-K11"
    assert rows[0]["price_value"] == 160.0
    assert rows[0]["currency_code"] == "EUR"
    assert rows[0]["currency_symbol"] == "€"
    assert rows[0]["sponsored"] is True
    assert rows[0]["detail_enriched"] is False
    assert rows[1]["price_value"] == 53.95
    assert "Regular price" not in rows[1]["price_text"]


def test_product_detail_uses_product_group_json_ld():
    html = (FIXTURES / "zalando_product_page.html").read_text(encoding="utf-8")
    detail = parse_product_detail(html, "zalando.de")

    assert detail["brand"] == "On"
    assert detail["product_id"] == "ONM12P000-K11"
    assert detail["product_name"] == "CLOUD 6 - Trainers - midnight white"
    assert detail["price_value"] == 160.0
    assert detail["currency_code"] == "EUR"
    assert detail["currency_symbol"] == "€"
    assert detail["price_text"] == "€160"
    assert detail["color"] == "midnight white/royal blue"
    assert detail["availability"] == "InStock"
    assert detail["detail_enriched"] is True


def test_localized_audience_paths_are_discovered_from_shop_navigation():
    html = """
    <nav aria-label="Shop Selector">
      <span data-testid="genderLink"><a href="/damen-home/">Damen</a></span>
      <span data-testid="genderLink"><a href="/herren-home/">Herren</a></span>
      <span data-testid="genderLink"><a href="/kinder-home/">Kinder</a></span>
    </nav>
    """
    assert discover_audience_paths(html) == {
        "women": "/damen/",
        "men": "/herren/",
        "kids": "/kinder/",
    }


def test_non_audience_fourth_shop_link_is_ignored():
    html = """
    <nav aria-label="Shop Selector">
      <span data-testid="genderLink"><a href="/donna-home/">Donna</a></span>
      <span data-testid="genderLink"><a href="/uomo-home/">Uomo</a></span>
      <span data-testid="genderLink"><a href="/bambini-home/">Bambini</a></span>
      <span data-testid="genderLink"><a href="/vendi/">Vendi</a></span>
    </nav>
    """
    assert discover_audience_paths(html) == {
        "women": "/donna/",
        "men": "/uomo/",
        "kids": "/bambini/",
    }
