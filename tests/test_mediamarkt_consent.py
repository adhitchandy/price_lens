from pathlib import Path
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException

from price_lens.marketplaces.mediamarkt import scraper as mm
from price_lens.marketplaces.mediamarkt.parser import parse_html


class QuickWait:
    def __init__(self, driver, *args, **kwargs):
        self.driver = driver

    def until(self, predicate):
        for _ in range(4):
            result = predicate(self.driver)
            if result:
                return result
        raise TimeoutException()


def test_cookie_dialog_must_disappear_not_just_its_reject_button(monkeypatch):
    monkeypatch.setattr(mm, "WebDriverWait", QuickWait)
    button = Mock()
    snapshots = iter([
        {"button": button, "blocked": True},
        {"button": None, "blocked": True},
        {"button": None, "blocked": False},
    ])
    monkeypatch.setattr(mm, "_consent_snapshot", lambda _: next(snapshots))
    monkeypatch.setattr(mm, "_visible_consent_button", lambda _: None)
    assert mm._handle_cookie_consent(Mock()) == "rejected"
    button.click.assert_called_once()


def test_unknown_cookie_controls_stop_before_pagination(monkeypatch):
    monkeypatch.setattr(mm, "WebDriverWait", QuickWait)
    monkeypatch.setattr(mm, "_consent_snapshot", lambda _: {
        "button": None, "blocked": True, "labels": ["Cookie settings"],
    })
    monkeypatch.setattr(mm, "_visible_consent_button", lambda _: None)
    driver = Mock()
    with pytest.raises(mm.StorefrontError, match="Cookie consent dialog did not close"):
        mm._advance_page(driver, "mediamarkt.at")
    driver.get.assert_not_called()


def test_supplied_austrian_pages_are_distinct_and_support_url_fallback(monkeypatch):
    folder = Path(__file__).parents[2] / "upload"
    files = [folder / "Suchergebnis für _smartphone_ _ MediaMarkt.html",
             folder / "Suchergebnis für _smartphone_ _ 2MediaMarkt.html"]
    if not all(f.exists() for f in files):
        pytest.skip("Full user snapshots are not distributed")
    first, second = [parse_html(f.read_text(), "mediamarkt.at", "smartphone", []) for f in files]
    assert len(first) == len(second) == 12
    assert not {r["product_id"] for r in first} & {r["product_id"] for r in second}
    driver = Mock(current_url="https://www.mediamarkt.at/de/search.html?query=smartphone",
                  page_source=files[0].read_text())
    assert mm._austrian_next_url(driver).endswith("query=smartphone&page=2")
    driver.current_url += "&page=2"
    driver.page_source = files[1].read_text()
    assert mm._austrian_next_url(driver).endswith("query=smartphone&page=3")


def test_austrian_fallback_preserves_filters_and_is_not_used_for_other_domains():
    html = '<span data-test="loading-test">12 von 3169</span>'
    driver = Mock(current_url="https://www.mediamarkt.at/de/search.html?query=phone&brand=Apple",
                  page_source=html)
    assert mm._austrian_next_url(driver).endswith("query=phone&brand=Apple&page=2")
    driver.current_url = driver.current_url.replace(".at/", ".es/")
    assert mm._austrian_next_url(driver) is None


def test_second_control_is_tried_when_first_click_does_not_close_dialog(monkeypatch):
    monkeypatch.setattr(mm.time, "sleep", lambda _s: None)
    clock = iter(range(0, 1000, 3))
    monkeypatch.setattr(mm.time, "monotonic", lambda: next(clock))
    save, accept = Mock(), Mock()
    blocked = {"value": True}
    accept.click.side_effect = lambda: blocked.update(value=False)
    calls = []

    def visible(_driver, exclude=()):
        calls.append(tuple(exclude))
        return ("saved", save) if "saved" not in exclude else ("accepted", accept)

    monkeypatch.setattr(mm, "_visible_consent_button", visible)
    monkeypatch.setattr(mm, "_consent_snapshot", lambda _d: {"button": None, "blocked": blocked["value"]})
    assert mm._handle_cookie_consent(Mock(), timeout=30) == "accepted"
    save.click.assert_called_once()
    accept.click.assert_called_once()


def test_counter_with_trailing_word_is_understood():
    from price_lens.marketplaces.mediamarkt.parser import listing_state

    state = listing_state('<span data-test="loading-test">12 / 518 termék</span>')
    assert (state["loaded"], state["total"]) == (12, 518)


def test_verification_page_that_clears_by_itself_is_waited_out(monkeypatch):
    monkeypatch.setattr(mm.time, "sleep", lambda _s: None)
    results = iter([mm.StorefrontError("Access restriction or verification challenge; stopped"), None])

    def check(_driver, _domain):
        outcome = next(results)
        if outcome:
            raise outcome

    monkeypatch.setattr(mm, "_check_storefront", check)
    mm._check_storefront_patiently(Mock(), "mediamarkt.be", grace=20)  # no error

    monkeypatch.setattr(mm, "_check_storefront", lambda *_: (_ for _ in ()).throw(
        mm.StorefrontError("Access restriction or verification challenge; stopped")))
    with pytest.raises(mm.StorefrontError, match="blocking automated browsing"):
        mm._check_storefront_patiently(Mock(), "mediamarkt.be", grace=0)


LANDING = """<html><body>
<a href="/nl/category/telefoonhoesjes-780.html">Telefoonhoesjes</a>
<a href="/nl/category/mobiele-telefoons-282.html">Mobiele telefoons</a>
<a href="/nl/category/smartphones-283.html">Smartphones</a>
<a href="/nl/category/samsung-smartphones-890.html">Samsung-smartphones</a>
<a href="https://other.example/nl/category/smartphones-1.html">Smartphones</a>
</body></html>"""


def test_landing_page_picks_best_matching_category():
    from price_lens.marketplaces.mediamarkt.parser import landing_category_link

    url = "https://www.mediamarkt.nl/nl/specials/mobiele-telefoons?query=Smartphone"
    assert landing_category_link(LANDING, url, "Smartphone").endswith("/nl/category/smartphones-283.html")
    assert landing_category_link(LANDING, url, "mobiele telefoon").endswith("mobiele-telefoons-282.html")
    assert landing_category_link(LANDING, url, "Waschmaschine") is None


def test_search_without_grid_follows_category(monkeypatch):
    driver = Mock(page_source=LANDING,
                  current_url="https://www.mediamarkt.nl/nl/specials/mobiele-telefoons?query=x")
    driver.find_elements.return_value = []
    monkeypatch.setattr(mm, "WebDriverWait", QuickWait)
    opened = []
    monkeypatch.setattr(mm, "_navigate", lambda d, url, domain: opened.append(url))
    assert mm._follow_category_if_landing(driver, "mediamarkt.nl", "Smartphone").endswith("smartphones-283.html")
    assert opened and opened[0].endswith("smartphones-283.html")
    driver.find_elements.return_value = [object()]  # grid present: nothing to do
    assert mm._follow_category_if_landing(driver, "mediamarkt.nl", "Smartphone") is None
