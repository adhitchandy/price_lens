from pathlib import Path

from price_lens.marketplaces.amazon.parser import (
    parse_html,
    parse_price_to_float,
    resolve_currency_code,
)


def test_price_parsing_for_decimal_conventions():
    assert parse_price_to_float("€1.299,95") == 1299.95
    assert parse_price_to_float("$1,299.95") == 1299.95
    assert parse_price_to_float("₹999") == 999.0


def test_bare_dollar_uses_marketplace():
    assert resolve_currency_code("$", "amazon.ca") == "CAD"
    assert resolve_currency_code("$", "amazon.com") == "USD"


def test_parse_html_returns_agent_ready_fields():
    html = (Path(__file__).parent / "fixtures" / "amazon_search_page.html").read_text(
        encoding="utf-8"
    )
    rules = [{"type": "Digital Camera", "include": ["camera"], "exclude": ["battery"]}]
    rows = parse_html(html, "amazon.de", "digital camera", rules)

    assert len(rows) == 2
    assert rows[0]["platform"] == "amazon"
    assert rows[0]["marketplace"] == "amazon.de"
    assert rows[0]["product_id"] == "B0TEST1234"
    assert rows[0]["price_value"] == 1299.95
    assert rows[0]["currency_symbol"] == "€"
    assert rows[0]["review_count"] == 1234
    assert rows[0]["product_url"] == "https://amazon.de/dp/B0TEST1234"
    assert rows[1]["sponsored"] is True
    assert rows[1]["product_type"] == "Digital Camera (Accessory)"
