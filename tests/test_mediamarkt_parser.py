from pathlib import Path

from selenium.common.exceptions import NoSuchElementException

from price_lens.marketplaces.mediamarkt.parser import (
    parse_html,
    parse_product_detail,
)
from price_lens.marketplaces.mediamarkt.scraper import (
    _handle_cookie_consent,
    build_search_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_search_item_list_extracts_common_product_fields():
    html = (FIXTURES / "mediamarkt_search_page.html").read_text(encoding="utf-8")
    rules = [{"type": "Smartphone", "include": [], "exclude": []}]

    rows = parse_html(html, "mediamarkt.de", "smartphone", rules)

    assert len(rows) == 2
    assert rows[0]["platform"] == "mediamarkt"
    assert rows[0]["marketplace"] == "mediamarkt.de"
    assert rows[0]["brand"] is None  # Title prefixes are not structured brand evidence.
    assert rows[0]["product_id"] == "3032640"
    assert rows[0]["price_value"] == 404.9
    assert rows[0]["currency_code"] == "EUR"
    assert rows[0]["currency_symbol"] == "€"
    assert rows[0]["rating"] == 4.732
    assert rows[0]["review_count"] == 153
    assert rows[0]["condition"] is None
    assert rows[0]["detail_enriched"] is False
    assert rows[1]["product_url"].startswith("https://www.mediamarkt.de/")


def test_product_detail_extracts_buy_action_product_group():
    html = (FIXTURES / "mediamarkt_product_page.html").read_text(encoding="utf-8")

    detail = parse_product_detail(html, "mediamarkt.de")

    assert detail["brand"] == "GOOGLE"
    assert detail["product_id"] == "3032640"
    assert detail["price_value"] == 404.9
    assert detail["currency_symbol"] == "€"
    assert detail["condition"] == "New"
    assert detail["availability"] == "InStock"
    assert detail["shipping_price_value"] == 0.0
    assert detail["color"] == "Obsidian"
    assert detail["detail_enriched"] is True


def test_search_url_uses_mediamarkt_query_and_page_contract():
    assert build_search_url("mediamarkt.de", "Google Pixel", 1) == (
        "https://www.mediamarkt.de/de/search.html?query=Google+Pixel"
    )
    assert build_search_url("mediamarkt.de", "Google Pixel", 2).endswith(
        "query=Google+Pixel&page=2"
    )


def test_cookie_handler_prefers_reject_button():
    class Button:
        clicked = False

        def is_displayed(self):
            return not self.clicked

        def is_enabled(self):
            return True

        def click(self):
            self.clicked = True

    class Driver:
        button = Button()

        def find_elements(self, _by, xpath):
            return [self.button] if "Alle ablehnen" in xpath else []

        def execute_script(self, _script, labels):
            return {"button": None, "blocked": not self.button.clicked, "labels": []}

        def find_element(self, *_args):
            raise NoSuchElementException

    driver = Driver()

    assert _handle_cookie_consent(driver) == "rejected"
    assert driver.button.clicked is True
