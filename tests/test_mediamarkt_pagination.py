import json
from pathlib import Path

import pytest
from selenium.common.exceptions import TimeoutException

from price_lens.marketplaces.mediamarkt import scraper as mm
from price_lens.marketplaces.mediamarkt.constants import (
    DOMAIN_TO_CURRENCY,
    DOMAIN_TO_LANGUAGE_PATH,
    MEDIAMARKT_MARKETPLACES,
)
from price_lens.marketplaces.mediamarkt.parser import next_page_url, parse_html

RULES = [{"type": "Phone", "include": [], "exclude": []}]


def test_advance_clicks_visible_load_more(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(mm, "_handle_cookie_consent", lambda *a, **kw: None)
    button = Mock()
    button.is_displayed.return_value = True
    button.is_enabled.return_value = True
    button.get_attribute.return_value = None
    driver = Mock()
    driver.find_elements.return_value = [button]
    assert mm._advance_page(driver, "mediamarkt.de") == "load_more"
    button.click.assert_called_once()
    driver.get.assert_not_called()


@pytest.mark.parametrize("label", [
    "12 weitere Produkte anzeigen", "Afficher plus de produits", "Meer producten tonen",
    "Mostrar más productos", "Mostra altri prodotti", "Pokaż więcej produktów",
    "További termékek", "Daha fazla ürün", "Suivant", "Siguiente",
])
def test_localized_pagination_control_without_german_test_id(label):
    from unittest.mock import Mock
    button = Mock(text=label)
    button.is_displayed.return_value = True
    button.is_enabled.return_value = True
    button.get_attribute.return_value = None
    driver = Mock()
    driver.find_elements.side_effect = [[], [button]]
    assert mm._pagination_control(driver) is button


def test_next_page_variant_preserves_query_and_filters():
    base = "https://www.mediamarkt.es/es/search.html?query=lavadora&brand=LG&p=2"
    html = '<a href="?query=lavadora&amp;brand=LG&amp;p=3">Siguiente</a>'
    assert next_page_url(html, base) == base.replace("p=2", "p=3")
    assert next_page_url(html.replace("LG", "BOSCH"), base) is None


def test_international_stalled_click_uses_site_next_link(monkeypatch):
    driver = FakeDriver()
    driver.current_url = "https://www.mediamarkt.at/de/category/phones.html"
    monkeypatch.setattr(mm, "_start_search", lambda *a: None)
    monkeypatch.setattr(mm, "_advance_page", lambda *a: "load_more")
    monkeypatch.setattr(mm, "_check_storefront", lambda *a: None)
    monkeypatch.setattr(mm.time, "sleep", lambda *a: None)
    monkeypatch.setattr(mm, "next_page_url", lambda html, url: url + "?page=2")
    navigated = []

    def navigate(d, url, domain):
        navigated.append(url)
        d.count = 24

    def wait(d, domain, term, rules, seen):
        fresh = [r for r in parse_html(d.page_source, domain, term, rules) if mm._row_key(r) not in seen]
        if not fresh:
            raise TimeoutException("Client handler stalled")
        return fresh

    monkeypatch.setattr(mm, "_navigate", navigate)
    monkeypatch.setattr(mm, "_wait_for_new_rows", wait)
    result = mm.MediaMarktScraper(lambda **kw: driver).search_with_report(
        {"phone": RULES}, ["mediamarkt.at"], pages=2, retries=0
    )
    assert len(result.raw_products) == 24
    assert len(navigated) == 1
    assert result.report.events[-1]["pagination_method"] == "next_link_after_stalled_click"


def grid(count, start=1):
    stale = json.dumps({"@type": "ItemList", "itemListElement": [{
        "item": {"@type": "Product", "name": "Stale phone",
                 "url": "/de/product/_phone-1.html",
                 "offers": {"price": 1, "priceCurrency": "EUR"}}}]})
    cards = "".join(
        f'<article data-test="mms-product-card">'
        f'<a href="/de/product/_phone-{i}.html"><h3 data-test="product-title">Phone {i}</h3></a>'
        '<div data-test="mms-price"><div data-test="mms-strike-price-type-rrp">999 €</div>'
        f'<span>{100+i},99 €</span></div></article>' for i in range(start, start+count)
    )
    return f'<script type="application/ld+json">{stale}</script>{cards}'


def test_cumulative_cards_override_stale_first_page_jsonld():
    rows = parse_html(grid(36), "mediamarkt.de", "phone", RULES)
    assert len(rows) == 36
    assert rows[0]["price_value"] == 101.99
    assert rows[-1]["product_id"] == "36"
    assert len(parse_html(grid(12, 13), "mediamarkt.de", "phone", RULES)) == 12


def test_next_link_keeps_redirected_category_and_filters():
    base = "https://www.mediamarkt.de/de/category/phones.html?brand=GOOGLE"
    html = '<link rel="next" href="?brand=GOOGLE&amp;page=2">'
    assert next_page_url(html, base) == base + "&page=2"
    assert next_page_url('<link rel="next" href="https://other.example/page2">', base) is None


class FakeDriver:
    current_url = "https://www.mediamarkt.de/de/category/phones.html"
    title = "Phones"
    count = 12
    closed = False

    @property
    def page_source(self):
        return grid(self.count)

    def set_page_load_timeout(self, _timeout):
        pass

    def find_elements(self, *args):
        return []

    def quit(self):
        self.closed = True


def test_three_batches_collect_36_not_12(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(mm, "_start_search", lambda *a: "rejected")
    monkeypatch.setattr(mm, "_check_storefront", lambda *a: None)
    monkeypatch.setattr(mm.time, "sleep", lambda *a: None)
    monkeypatch.setattr(mm, "_wait_for_new_rows", lambda d, domain, term, rules, seen:
                        [r for r in parse_html(d.page_source, domain, term, rules)
                         if mm._row_key(r) not in seen])

    def advance(*args):
        driver.count += 12
        return "load_more"

    monkeypatch.setattr(mm, "_advance_page", advance)
    outcome = mm.MediaMarktScraper(lambda **kw: driver).search_with_report(
        {"phone": RULES}, ["mediamarkt.de"], pages=3, retries=0
    )
    assert len(outcome.raw_products) == 36
    assert outcome.report.pages_succeeded == 3
    assert [e["new_products"] for e in outcome.report.events] == [12, 12, 12]
    assert driver.closed


def test_stalled_second_page_is_failure_not_success(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(mm, "_start_search", lambda *a: None)
    monkeypatch.setattr(mm, "_advance_page", lambda *a: "load_more")
    monkeypatch.setattr(mm, "_check_storefront", lambda *a: None)
    monkeypatch.setattr(mm.time, "sleep", lambda *a: None)

    def wait(d, domain, term, rules, seen):
        if seen:
            raise TimeoutException("No new product IDs")
        return parse_html(d.page_source, domain, term, rules)

    monkeypatch.setattr(mm, "_wait_for_new_rows", wait)
    result = mm.MediaMarktScraper(lambda **kw: driver).search_with_report(
        {"phone": RULES}, ["mediamarkt.de"], pages=3, retries=1
    )
    assert len(result.raw_products) == 12
    assert result.report.pages_succeeded == 1
    assert result.report.status == "completed_with_errors"
    assert result.report.failures[0]["stage"] == "pagination"
    assert driver.closed


def test_portugal_not_silently_scraped_as_darty():
    def forbidden(**kwargs):
        raise AssertionError("No browser should start for unavailable domains")
    outcome = mm.MediaMarktScraper(forbidden).search_with_report(
        {"phone": RULES}, ["mediamarkt.pt"]
    )
    assert outcome.report.status == "failed"
    assert outcome.report.failures[0]["status"] == "unavailable"


@pytest.mark.parametrize("domain", MEDIAMARKT_MARKETPLACES)
def test_all_country_configs_have_route_and_currency(domain):
    assert domain in DOMAIN_TO_CURRENCY
    assert domain in DOMAIN_TO_LANGUAGE_PATH
    assert f"www.{domain}/" in mm.build_search_url(domain, "phone", 1)


def test_original_saved_page_if_present():
    path = Path(__file__).parents[2] / "upload/Smartphones online kaufen bei MediaMarkt.htm"
    if not path.exists():
        pytest.skip("User's full saved page is not distributed")
    rows = parse_html(path.read_text(encoding="utf-8"), "mediamarkt.de", "phone", RULES)
    assert len(rows) == 12
    pixel = next(r for r in rows if r["product_id"] == "3032640")
    assert pixel["price_value"] == 404.9
