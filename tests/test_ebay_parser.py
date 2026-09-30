from pathlib import Path

from price_lens.marketplaces.ebay.parser import parse_html


def test_ebay_fixture_returns_common_and_marketplace_fields():
    html = (Path(__file__).parent / "fixtures" / "ebay_search_page.html").read_text(
        encoding="utf-8"
    )
    rules = [{"type": "Digital Camera", "include": ["camera"], "exclude": ["battery"]}]
    rows = parse_html(html, "ebay.de", "digital camera", rules)

    assert len(rows) == 2
    assert rows[0]["platform"] == "ebay"
    assert rows[0]["marketplace"] == "ebay.de"
    assert rows[0]["product_id"] == "123456789012"
    assert rows[0]["product_name"] == "Sony Mirrorless Digital Camera"
    assert rows[0]["price_value"] == 1299.95
    assert rows[0]["currency_code"] == "EUR"
    assert rows[0]["currency_symbol"] == "€"
    assert rows[0]["shipping_price_value"] == 0.0
    assert rows[0]["condition"] == "Used"
    assert rows[0]["seller"] == "camera_shop (99.8%)"
    assert rows[0]["rating"] == 4.8
    assert rows[0]["review_count"] == 123
    assert rows[0]["product_url"] == "https://www.ebay.de/itm/Example-Camera/123456789012"

    assert rows[1]["product_id"] == "987654321098"
    assert rows[1]["sponsored"] is True
    assert rows[1]["shipping_price_value"] == 4.99
    assert rows[1]["buying_format"] == "auction"
    assert rows[1]["product_type"] == "Digital Camera (Accessory)"


def test_data_testid_card_variant_is_supported():
    html = """
    <div data-testid="item-card">
      <a data-testid="item-link" href="/itm/Canon-Camera/112233445566?tracking=1">
        <span data-testid="item-title">Canon Digital Camera</span>
      </a>
      <span data-testid="item-price">EUR 499,95</span>
    </div>
    """
    rules = [{"type": "Digital Camera", "include": ["camera"], "exclude": []}]
    rows = parse_html(html, "ebay.de", "digital camera", rules)
    assert len(rows) == 1
    assert rows[0]["product_id"] == "112233445566"
    assert rows[0]["price_value"] == 499.95
    assert rows[0]["product_url"] == "https://www.ebay.de/itm/Canon-Camera/112233445566"
