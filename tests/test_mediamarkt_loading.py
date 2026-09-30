from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException
from test_mediamarkt_pagination import RULES, FakeDriver, grid

from price_lens.marketplaces.mediamarkt import scraper as mm
from price_lens.marketplaces.mediamarkt.parser import listing_state


def listing(count, expected=12, total=120):
    return ('<div data-test="mms-search-srp-productlist">' + grid(count) + '</div>'
            f'<span data-test="loading-test">{expected} von {total}</span>')


def clock_wait(monkeypatch):
    clock = SimpleNamespace(now=0)

    class Wait:
        def __init__(self, driver, timeout, **kw):
            self.driver, self.timeout = driver, timeout

        def until(self, predicate):
            for _ in range(int(self.timeout)):
                clock.now += 1
                result = predicate(self.driver)
                if result:
                    return result
            raise TimeoutException()

    monkeypatch.setattr(mm, "WebDriverWait", Wait)
    monkeypatch.setattr(mm.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(mm, "_check_storefront", lambda *a: None)
    monkeypatch.setattr(mm, "_scroll_listing", lambda d, reset=False: not reset)
    return clock


def test_lazy_grid_three_six_twelve_is_one_complete_batch(monkeypatch):
    clock = clock_wait(monkeypatch)
    driver = Mock()
    sources = iter([listing(3), listing(6), listing(12)])
    # Every poll reads a new snapshot, then the full grid remains stable.
    class Driver:
        current_url = 'https://www.mediamarkt.at/de/search.html?query=phone'

        @property
        def page_source(self):
            return next(sources, listing(12))

    driver = Driver()
    rows = mm._wait_for_new_rows(driver, "mediamarkt.at", "phone", RULES, set())
    assert len(rows) == 12 and rows.complete
    assert clock.now >= 6


def test_stalled_partial_grid_is_preserved_not_success(monkeypatch):
    clock_wait(monkeypatch)
    driver = Mock(page_source=listing(3))
    rows = mm._wait_for_new_rows(driver, "mediamarkt.es", "phone", RULES, set(), timeout=8)
    assert len(rows) == 3 and not rows.complete
    assert rows.state["loaded"] == 12


def test_legitimate_three_result_catalogue_is_complete(monkeypatch):
    clock_wait(monkeypatch)
    driver = Mock(page_source=listing(3, expected=3, total=3))
    rows = mm._wait_for_new_rows(driver, "mediamarkt.es", "phone", RULES, set(), timeout=8)
    assert len(rows) == 3 and rows.complete


def test_homepage_recommendations_are_not_search_results(monkeypatch):
    clock_wait(monkeypatch)
    driver = Mock(page_source=grid(3), current_url="https://www.mediamarkt.be/nl/")
    with pytest.raises(TimeoutException, match="grid_present=False"):
        mm._wait_for_new_rows(driver, "mediamarkt.be", "phone", RULES, set(), timeout=8)


def test_counter_parses_large_localized_total():
    state = listing_state(listing(12).replace("12 von 120", "12 van 4.272"))
    assert (state["loaded"], state["total"]) == (12, 4272)


def test_missing_next_control_is_logged(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(mm, "_start_search", lambda *a: None)
    monkeypatch.setattr(mm, "_advance_page", lambda *a: None)
    monkeypatch.setattr(mm, "_wait_for_new_rows", lambda *a: [{
        "product_id": "1", "product_url": "https://www.mediamarkt.at/de/product/1.html",
        "product_name": "Phone", "price_value": 20,
    }])
    monkeypatch.setattr(mm.time, "sleep", lambda *a: None)
    logs = []
    result = mm.MediaMarktScraper(lambda **kw: driver).search_with_report(
        {"phone": RULES}, ["mediamarkt.at"], pages=3, retries=0, log=logs.append,
    )
    assert result.report.pages_succeeded == 1
    assert result.report.status == "completed_with_errors"
    assert any("No usable next-page control" in entry for entry in logs)


def test_visible_cloudflare_check_is_not_grid_timeout():
    driver = Mock(current_url="https://www.mediamarkt.be/nl/")
    driver.find_element.return_value.text = "Verifying you are human"
    driver.find_elements.return_value = []
    with pytest.raises(mm.StorefrontError, match="verification challenge"):
        mm._check_storefront(driver, "mediamarkt.be")


def test_diagnostics_names_are_short_and_unique(tmp_path):
    driver = Mock(page_source="<html>failure</html>")
    driver.save_screenshot.return_value = False
    first = mm._save_diagnostics(driver, tmp_path, "mediamarkt.be", "phone", 1)
    second = mm._save_diagnostics(driver, tmp_path, "mediamarkt.be", "phone", 2)
    assert first["html"] != second["html"]
    from pathlib import Path
    assert len(Path(first["html"]).name) == 17


def test_reached_counter_completes_even_if_scroll_target_is_unreachable(monkeypatch):
    clock_wait(monkeypatch)
    monkeypatch.setattr(mm, "_scroll_listing", lambda *a, **kw: False)
    driver = Mock(page_source=listing(12, expected=12, total=3169))
    rows = mm._wait_for_new_rows(driver, "mediamarkt.at", "Smartphone", RULES, set(), timeout=8)
    assert len(rows) == 12 and rows.complete
    assert rows.state["counter_reached"]
    assert not rows.state["scroll_bottom"]


def test_diagnostics_deep_path_uses_short_fallback(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr(mm.tempfile, "gettempdir", lambda: str(tmp_path))
    driver = Mock(page_source="<html>Just a moment...</html>")
    driver.save_screenshot.return_value = False
    result = mm._save_diagnostics(driver, tmp_path / ("deep/" * 60), "mediamarkt.be", "phone", 1)
    assert Path(result["html"]).parent == tmp_path / "pi-diagnostics"
    assert Path(result["html"]).read_text() == driver.page_source


def test_partial_grid_does_not_increment_successful_page_count(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(mm, "_start_search", lambda *a: None)
    monkeypatch.setattr(mm, "_wait_for_new_rows", lambda *a: mm.BatchRows([{
        "product_id": "1", "product_url": "https://www.mediamarkt.at/de/product/1.html",
        "product_name": "Phone", "price_value": 20,
    }], complete=False, state={"loaded": 12}))
    monkeypatch.setattr(mm.time, "sleep", lambda *a: None)
    result = mm.MediaMarktScraper(lambda **kw: driver).search_with_report(
        {"phone": RULES}, ["mediamarkt.at"], pages=3, retries=0,
    )
    assert len(result.raw_products) == 1
    assert result.report.pages_succeeded == 0
    assert result.report.status == "completed_with_errors"
    assert not result.raw_products.iloc[0].collection_complete
