"""Pause / resume of long collections, and nothing lost when a run stops early."""
import json

import pandas as pd
import pytest

from price_lens.orchestrator import jobs, registry, retry
from price_lens.orchestrator.analyst import CATALOG
from price_lens.orchestrator.registry import MarketplaceAdapter
from price_lens.webapp import api
from test_new_features import adapter

COUNTRIES = sorted({i["country"] for i in CATALOG["mediamarkt"].values()})[:5]


def long_plan():
    return {
        "schema_version": "analyst-v2", "research_question": "Phones and laptops",
        "execution": {"pages": 1, "retries": 0, "headless": True, "delay_seconds": [0.5, 0.5]},
        "searches": [
            {"id": "s1", "product_type": "Smartphones",
             "query": {"default": "Smartphone", "translations": {}, "filters": {}},
             "targets": [{"platform": "mediamarkt", "countries": COUNTRIES, "platform_options": {}}]},
            {"id": "s2", "product_type": "Laptops",
             "query": {"default": "Laptop", "translations": {}, "filters": {}},
             "targets": [{"platform": "mediamarkt", "countries": COUNTRIES[:3], "platform_options": {}}]},
        ],
    }


@pytest.fixture()
def out(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_OUTPUT_DIR", str(tmp_path))
    # start_job launches a background process; run the worker in this process instead
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *a, **k: type("P", (), {"pid": 0})())
    return tmp_path


def counting_adapter(monkeypatch, on_store=None, fail=()):
    """Fake scraper: 3 listings per storefront; calls on_store(n, domain) before each."""
    base = adapter(fail=fail)
    seen = []

    def collect(plan, log):
        seen.append(plan.marketplaces[0])
        if on_store:
            on_store(len(seen), plan.marketplaces[0])
        outcome = base.collect(plan, log)
        frame = outcome.raw_products  # different products per storefront (not duplicates)
        frame["product_name"] = frame["product_name"] + " " + plan.marketplaces[0]
        frame["origin_country"] = plan.marketplaces[0]
        return outcome

    monkeypatch.setitem(registry.MARKETPLACE_REGISTRY, "mediamarkt", MarketplaceAdapter("mediamarkt", collect))
    return seen


def start(out):
    run = jobs.start_job(long_plan(), out)
    return run


def listings(run):
    return len(pd.read_csv(run / "final_products.csv"))


def test_pause_keeps_everything_and_resume_collects_only_the_rest(out, monkeypatch):
    run = start(out)
    total = len(COUNTRIES) + 3
    # pause while the 3rd storefront of search 1 is being collected
    seen = counting_adapter(monkeypatch, on_store=lambda n, d: n == 3 and jobs.request_pause(run))
    assert jobs.run_worker(run) == 0
    job = jobs.read_job(run)
    assert job["status"] == "paused" and not (run / jobs.PAUSE_FILE).exists()
    assert len(seen) == 3  # stopped after the storefront in progress
    first = set(seen)
    assert listings(run) == 9  # all 3 finished storefronts are in the results
    left = retry.remaining_storefronts(run)
    assert len(left) == total - 3
    detail = api.run_detail(run.name)
    assert detail["status"] == "paused" and detail["label"] == "Paused"
    assert detail["remaining"] == total - 3 and detail["total_storefronts"] == total
    assert api.research_list()["items"][0]["left"] == total - 3
    assert retry.failed_storefronts(run) == []  # nothing failed; the rest is "remaining"
    table = {r["storefront"]: r["result"] for r in api.live(run.name)["table"]}
    assert list(table.values()).count("OK") == 3 and "Error" not in table.values()
    assert list(table.values()).count("Not collected yet") == len(COUNTRIES) - 3

    # resume; pause again after 2 more storefronts
    res = api.resume(run.name)
    extra = out / res["run"]
    assert res["storefronts"] == total - 3 and jobs.read_job(extra)["resume"]
    assert api.research_list()["items"][0]["status"] == "running"  # shown as collecting
    seen = counting_adapter(monkeypatch, on_store=lambda n, d: n == 2 and jobs.request_pause(extra))
    jobs.run_worker(extra)
    assert jobs.read_job(extra)["status"] == "paused" and jobs.read_job(extra)["merged"]
    assert listings(run) == 15 and jobs.read_job(run)["status"] == "paused"
    assert len(retry.remaining_storefronts(run)) == total - 5
    assert len(seen) == 2 and not set(seen) & first  # only storefronts not collected before

    # resume to the end
    extra2 = out / api.resume(run.name)["run"]
    counting_adapter(monkeypatch)
    jobs.run_worker(extra2)
    assert listings(run) == total * 3
    assert retry.remaining_storefronts(run) == []
    assert jobs.read_job(run)["status"] == "completed"
    assert api.run_detail(run.name)["status"] == "completed"
    ids = pd.read_csv(run / "final_products.csv")["product_id"]
    assert ids.is_unique  # no storefront collected twice
    with pytest.raises(api.ApiError):
        api.resume(run.name)


def test_stop_mid_search_keeps_finished_storefronts(out, monkeypatch):
    run = start(out)
    counting_adapter(monkeypatch, on_store=lambda n, d: n == 3 and jobs.request_cancel(run))
    jobs.run_worker(run)
    assert jobs.read_job(run)["status"] == "cancelled"
    assert listings(run) == 6  # the 2 storefronts that finished before Stop (3rd was cut off)
    assert api.run_detail(run.name)["label"] == "Stopped"
    assert len(retry.remaining_storefronts(run)) == len(COUNTRIES) + 3 - 2


def test_shutdown_during_resume_loses_nothing(out, monkeypatch):
    run = start(out)
    counting_adapter(monkeypatch, on_store=lambda n, d: n == 2 and jobs.request_pause(run))
    jobs.run_worker(run)
    extra = out / api.resume(run.name)["run"]

    class PowerOff(BaseException):
        pass

    def die(n, d):
        if n == 3:
            raise PowerOff()  # the computer shuts down while the 3rd storefront loads
    counting_adapter(monkeypatch, on_store=die)
    jobs.run_worker(extra)  # records "failed"; as with a real shutdown nothing is merged
    jobs._update(extra, status="running", heartbeat="2020-01-01T00:00:00+00:00", pid=None)
    assert jobs.read_job(extra)["status"] == "crashed"
    assert listings(run) == 6
    detail = api.run_detail(run.name)  # opening the research recovers and adds them
    assert listings(run) == 12 and detail["status"] == "paused"
    assert len(retry.remaining_storefronts(run)) == len(COUNTRIES) + 3 - 4
    api.run_detail(run.name)  # a second look does not add them twice
    assert listings(run) == 12


def test_failed_storefronts_go_to_retry_not_resume(out, monkeypatch):
    run = start(out)
    bad = sorted(d for d, i in CATALOG["mediamarkt"].items() if i["country"] == COUNTRIES[1])[0]
    counting_adapter(monkeypatch, fail=(bad,), on_store=lambda n, d: n == 3 and jobs.request_pause(run))
    jobs.run_worker(run)
    failed = retry.failed_storefronts(run)
    assert [f["domain"] for f in failed] == [bad] and "Cookie" in failed[0]["problem"]
    assert (1, bad) not in {(r["search_id"], r["domain"]) for r in retry.remaining_storefronts(run)}


def test_pause_request_while_running(out):
    run = start(out)
    jobs._update(run, status="running", heartbeat=jobs._now())
    assert api.pause(run.name)["state"] == "pausing"
    assert (run / jobs.PAUSE_FILE).exists() and jobs.read_job(run)["status"] == "pausing"
    assert jobs.is_active(jobs.read_job(run))
    live = api.live(run.name)
    assert live["state"] == "pausing" and not live["can_pause"]


def test_sleeping_computer_is_not_a_crash(out):
    import os
    run = start(out)
    jobs._update(run, status="running", heartbeat="2020-01-01T00:00:00+00:00", pid=os.getpid())
    assert jobs.read_job(run)["status"] == "running"  # process still exists
    jobs._update(run, pid=999999)
    assert jobs.read_job(run)["status"] == "crashed"
    assert jobs.pid_alive(os.getpid()) and not jobs.pid_alive(None)


def test_old_runs_are_not_offered_a_resume(out):
    """Finished runs made before this change keep their status."""
    run = out / "analyst_20260101_000000"
    run.mkdir()
    (run / "analyst_plan.json").write_text(json.dumps(long_plan()), encoding="utf-8")
    pd.DataFrame([{"search_id": 1, "product_id": "a", "price_usd": 1}]).to_csv(run / "final_products.csv", index=False)
    (run / "collection_report.json").write_text(json.dumps({"searches": [
        {"search_id": 1, "status": "completed", "report": {"platform_reports": {}}},
        {"search_id": 2, "status": "failed", "report": {"platform_reports": {}}}]}), encoding="utf-8")
    assert retry.remaining_storefronts(run) == []
    assert api.run_detail(run.name)["status"] != "paused"
