"""The custom screens (apps/pi_ui/web): live-run data, the copy button, assets."""
import json
from pathlib import Path

import pandas as pd

from apps.pi_ui import components
from price_lens.orchestrator import jobs

ROOT = Path(__file__).parents[1]

PLAN = {
    "schema_version": "analyst-v2", "research_question": "Phones",
    "execution": {"products_per_storefront": 50, "retries": 0, "headless": True},
    "searches": [
        {"id": "s1", "product_type": "Smartphones",
         "query": {"default": "Smartphone", "translations": {}, "filters": {}},
         "targets": [{"platform": "mediamarkt", "countries": ["Germany", "Austria", "Netherlands"]}]},
        {"id": "s2", "product_type": "Laptops",
         "query": {"default": "Laptop", "translations": {}, "filters": {}},
         "targets": [{"platform": "mediamarkt", "countries": ["Germany", "Austria"]}]},
    ],
}


def running_job(tmp_path, log, searches_done=1):
    run = tmp_path / "analyst_20260929_181204"
    run.mkdir()
    (run / jobs.PLAN_FILE).write_text(json.dumps(PLAN), encoding="utf-8")
    (run / jobs.LOG_FILE).write_text(log, encoding="utf-8")
    jobs._update(run, kind="scrape", status="running", started_at=jobs._now(), heartbeat=jobs._now(),
                 searches_total=2, searches_done=searches_done)
    return run


def checkpoint(run, search, domain, rows):
    folder = run / f"search_{search:03}" / "research_x" / "mediamarkt" / "checkpoints"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"product_name": [f"p{i}" for i in range(rows)]}).to_csv(folder / f"{domain}.csv", index=False)


def test_run_payload_reports_each_storefront(tmp_path):
    run = running_job(tmp_path, "\n".join([
        "##### Search 1/2: Smartphone #####",
        "mediamarkt.de | Smartphone: target reached (50/50 products)",
        "##### Search 2/2: Laptop #####",
        "mediamarkt.de | Laptop | batch 1: 20 new products",
        "mediamarkt.de | Laptop: target reached (50/50 products)",
        "⚠️ mediamarkt.at: internet connection lost — pausing and checking every 30 s",
    ]))
    checkpoint(run, 1, "mediamarkt.de", 50)
    checkpoint(run, 1, "mediamarkt.at", 0)
    checkpoint(run, 2, "mediamarkt.de", 48)
    data = components.run_payload(run, jobs.read_job(run, log_lines=0))
    status = {(s["search"], s["store"]): (s["status"], s["count"]) for s in data["stores"]}
    assert status[(1, "mediamarkt.de")] == ("Done", 50)
    assert status[(1, "mediamarkt.at")] == ("No products", 0)
    assert status[(1, "mediamarkt.nl")] == ("No result", None)  # search 1 is over
    assert status[(2, "mediamarkt.de")] == ("Done", 48)
    assert status[(2, "mediamarkt.at")] == ("Waiting for network", None)
    assert data["listings"] == 98 and data["stores_done"] == 4 and data["progress"] == 80
    assert data["search"] == {"current": 2, "total": 2, "term": "Laptop"}
    assert data["log"][-1]["k"] == "warn" and data["log"][0]["k"] == "head"
    assert data["time_left"] and not data["can_force"]


def test_run_payload_survives_a_broken_plan(tmp_path):
    run = running_job(tmp_path, "")
    (run / jobs.PLAN_FILE).write_text("{not json", encoding="utf-8")
    data = components.run_payload(run, jobs.read_job(run, log_lines=0))
    assert data["stores"] == [] and data["progress"] == 50  # falls back to searches done


def test_live_run_and_copy_button_render(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_price_research_ui import component_data

    running_job(tmp_path, "##### Search 1/2: Smartphone #####\n")
    monkeypatch.setenv("PI_OUTPUT_DIR", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "apps/unified_app.py"), default_timeout=60).run()
    assert not app.exception
    live = component_data(app, "pi_run")
    assert live["state"] == "running" and len(live["stores"]) == 5
    app.text_area(key="describe_request").input("Sneaker prices in Germany").run()
    copy = component_data(app, "pi_copy")
    assert copy["label"] == "Copy prompt" and len(copy["text"]) > 100


def test_screen_assets_exist_and_escape_text():
    for name in ("base.css", "results.css", "results.js", "run.css", "run.js", "copy.css", "copy.js"):
        assert (components.WEB / name).read_text(encoding="utf-8").strip()
    for script in ("results.js", "run.js"):
        source = (components.WEB / script).read_text(encoding="utf-8")
        assert "innerHTML" not in source  # scraped titles are only ever set as text


def test_product_rows_are_json_safe():
    frame = pd.DataFrame({"product_name": ["A", None], "price_value": [1.5, float("nan")],
                          "price_usd": [float("inf"), 2], "marketplace": ["x.de", "y.de"]})
    rows = components.product_rows(frame)
    assert rows[0] == {**{k: None for k in components.ROW_FIELDS}, "i": 0, "n": "A", "v": 1.5, "m": "x.de"}
    assert rows[1]["n"] is None and rows[1]["v"] is None and rows[1]["usd"] == 2
    json.dumps(rows, allow_nan=False)
    assert components.short_fx({"date": "2026-09-08"}) == "USD at ECB rates of 8 Sep 2026"
    assert components.short_fx(None) == "USD at static rates"
