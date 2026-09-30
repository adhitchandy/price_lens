import json

import pandas as pd

from price_lens.core import network
from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport
from price_lens.orchestrator.localization import collect_localized
from price_lens.orchestrator.registry import MarketplaceAdapter
from price_lens.orchestrator.validation import parse_research_plan

NET_ERROR = ("WebDriverException: Message: Reached error page: about:neterror?e=dnsNotFound"
             "&u=https%3A//www.mediamarkt.de/")


def plan(domains=("mediamarkt.de", "mediamarkt.at"), output_dir=None):
    data = {"research_question": "Phones", "marketplaces": {"mediamarkt": list(domains)},
            "require_localized_queries": True,
            "searches": [{"search_term": "phone", "product_type": "Phone",
                          "localized_queries": {d: {"search_term": "Handy", "language": "de"}
                                                for d in domains}}]}
    if output_dir:
        data["output_dir"] = str(output_dir)
    return parse_research_plan(data).platform_plan("mediamarkt")


def ok(domain, rows=3):
    frame = pd.DataFrame([{"marketplace": domain, "search_term": "Handy", "product_name": f"p{i}",
                           "product_id": f"{domain}-{i}"} for i in range(rows)])
    return ScrapeOutcome(frame, ScrapeReport(platform="mediamarkt", status="completed"))


def offline_outcome():
    report = ScrapeReport(platform="mediamarkt", status="failed")
    report.failures.append({"marketplace": "x", "error": NET_ERROR})
    return ScrapeOutcome(pd.DataFrame(), report)


def test_classifier():
    assert network.is_network_error(NET_ERROR)
    assert not network.is_network_error("Cookie consent dialog did not close")
    assert network.mostly_network_errors([NET_ERROR, NET_ERROR, "timeout"])
    assert not network.mostly_network_errors([])


def test_outage_pauses_then_redoes_the_storefront(monkeypatch, tmp_path):
    monkeypatch.setattr(network, "_sleep", lambda _s: None)
    probes = iter([False, False, True])          # offline, still offline, back
    monkeypatch.setattr(network, "probe", lambda hosts, timeout=4.0: next(probes))
    calls, logs = [], []

    def collect(subplan, _log):
        domain = subplan.marketplaces[0]
        calls.append(domain)
        return offline_outcome() if len(calls) == 1 else ok(domain)

    outcome = collect_localized(MarketplaceAdapter("mediamarkt", collect),
                                plan(output_dir=tmp_path), logs.append)
    assert calls == ["mediamarkt.de", "mediamarkt.de", "mediamarkt.at"]
    assert len(outcome.raw_products) == 6
    assert any("connection lost" in m for m in logs) and any("connection is back" in m for m in logs)
    # every finished storefront is checkpointed immediately
    assert sorted(p.name for p in (tmp_path / "checkpoints").iterdir()) == [
        "mediamarkt.at.csv", "mediamarkt.de.csv"]


def test_long_outage_skips_remaining_storefronts_quickly(monkeypatch):
    monkeypatch.setattr(network, "_sleep", lambda _s: None)
    monkeypatch.setattr(network, "probe", lambda hosts, timeout=4.0: False)
    calls = []

    def collect(subplan, _log):
        calls.append(subplan.marketplaces[0])
        return offline_outcome()

    outcome = collect_localized(MarketplaceAdapter("mediamarkt", collect), plan(), lambda _m: None)
    assert calls == ["mediamarkt.de"]  # second storefront not even attempted
    errors = [f["error"] for f in outcome.report.failures if f.get("marketplace") == "mediamarkt.at"]
    assert errors and errors[0].startswith("Network")


def test_site_errors_with_working_internet_do_not_pause(monkeypatch):
    monkeypatch.setattr(network, "probe", lambda hosts, timeout=4.0: True)
    waited = []
    monkeypatch.setattr(network, "wait_for_connection", lambda *a, **k: waited.append(1) or True)
    collect = lambda subplan, _log: offline_outcome()  # noqa: E731
    collect_localized(MarketplaceAdapter("mediamarkt", collect), plan(), lambda _m: None)
    assert not waited


def test_wait_is_cancellable(monkeypatch):
    monkeypatch.setattr(network, "_sleep", lambda _s: None)

    class Stop(BaseException):
        pass

    def log(_m):
        raise Stop()

    try:
        network.wait_for_connection("mediamarkt.de", log, check=lambda hosts: False)
    except Stop:
        pass
    else:
        raise AssertionError("cancel was ignored")


def test_network_failures_are_not_blamed_on_the_shop(tmp_path):
    from price_lens.orchestrator import storefront_status
    from price_lens.orchestrator.health import classify_problem

    assert classify_problem(NET_ERROR) == "Network"
    assert classify_problem("Network: offline — storefront skipped") == "Network"
    reports = [{"search_id": 1, "report": {"platform_reports": {"mediamarkt": {
        "events": [], "failures": [{"marketplace": "mediamarkt.de", "error": NET_ERROR},
                                   {"marketplace": "mediamarkt.be",
                                    "error": "Access restriction or verification challenge"}]}}}}]
    preview = [{"platform": "mediamarkt", "domain": d, "country": c}
               for d, c in (("mediamarkt.de", "Germany"), ("mediamarkt.be", "Belgium"))]
    status = storefront_status.record(tmp_path, reports, preview, "run")
    assert "mediamarkt.de" not in status and status["mediamarkt.be"]["result"] == "Bot check"


def test_crashed_run_is_recovered_from_checkpoints(tmp_path, monkeypatch):
    from price_lens.orchestrator import history, jobs

    plan_data = {"schema_version": "analyst-v2", "research_question": "Phones",
                 "execution": {"products_per_storefront": 10},
                 "searches": [{"id": "s", "product_type": "Phones",
                               "query": {"default": "phone", "filters": {"max_price": 500}},
                               "targets": [{"platform": "mediamarkt",
                                            "countries": ["Germany", "Austria"]}]}]}
    run = tmp_path / "analyst_20260929_160000"
    run.mkdir()
    (run / "analyst_plan.json").write_text(json.dumps(plan_data))
    jobs._update(run, kind="scrape", status="running", heartbeat="2020-01-01T00:00:00+00:00")
    ckpt = run / "search_001" / "research_x" / "mediamarkt" / "checkpoints"
    ckpt.mkdir(parents=True)
    pd.DataFrame([{"platform": "mediamarkt", "marketplace": "mediamarkt.de", "product_name": n,
                   "product_id": n, "price_value": p, "price_usd": p, "currency_code": "EUR",
                   "sponsored": False, "origin_country": "Germany", "search_term": "phone"}
                  for n, p in (("A", 200.0), ("B", 900.0), ("C", 300.0))]
                 ).to_csv(ckpt / "mediamarkt.de.csv", index=False)
    assert history.run_status(run) == "crashed" and not history.is_empty_failure(run)
    loaded = history.load_run(run)
    assert loaded["recovered"]["listings"] == 2          # price filter (max 500 USD) applied
    assert sorted(loaded["final"]["product_name"]) == ["A", "C"]
    assert history.run_status(run) == "recovered"
    assert history.load_run(run)["recovered"] is None     # only once


def test_retry_failed_storefronts_merges_into_original_run(tmp_path, monkeypatch):
    from price_lens.orchestrator import history, jobs, registry, retry

    broken = {"mediamarkt.at": "Cookie consent dialog did not close",
              "mediamarkt.ch": "Access restriction or verification challenge; stopped"}

    def collect(subplan, _log):
        domain = subplan.marketplaces[0]
        if domain in broken:
            report = ScrapeReport(platform="mediamarkt", status="failed")
            report.failures.append({"marketplace": domain, "error": broken[domain]})
            return ScrapeOutcome(pd.DataFrame(), report)
        frame = ok(domain).raw_products.assign(
            platform="mediamarkt", price_value=100.0, price_usd=116.7, currency_code="EUR",
            sponsored=False, origin_country="X", search_term=subplan.searches[0].search_term)
        report = ScrapeReport(platform="mediamarkt", status="completed")
        report.events.append({"marketplace": domain, "listings": len(frame), "status": "succeeded"})
        return ScrapeOutcome(frame, report)

    monkeypatch.setitem(registry.MARKETPLACE_REGISTRY, "mediamarkt", MarketplaceAdapter("mediamarkt", collect))
    plan_data = {"schema_version": "analyst-v2", "research_question": "Phones",
                 "execution": {"products_per_storefront": 10, "delay_seconds": [0.5, 0.5]},
                 "searches": [
                     {"id": "a", "product_type": "TV", "query": {"default": "tv"},
                      "targets": [{"platform": "mediamarkt", "countries": ["Germany"]}]},
                     {"id": "b", "product_type": "Phones", "query": {"default": "phone"},
                      "targets": [{"platform": "mediamarkt",
                                   "countries": ["Germany", "Austria", "Switzerland"]}]}]}
    parent = tmp_path / "analyst_20260929_170000"
    parent.mkdir()
    (parent / "analyst_plan.json").write_text(json.dumps(plan_data))
    jobs._update(parent, kind="scrape", status="queued", heartbeat=jobs._now())
    jobs.run_worker(parent)
    failed = retry.failed_storefronts(parent)
    assert sorted((f["search_id"], f["domain"], f["result"]) for f in failed) == [
        (2, "mediamarkt.at", "Cookie wall"), (2, "mediamarkt.ch", "Bot check")]

    retry_plan = retry.build_retry_plan(plan_data, [f for f in failed if f["domain"] == "mediamarkt.at"])
    assert [(s["origin_search_id"], s["targets"][0]["countries"]) for s in retry_plan["searches"]] == [
        (2, ["Austria"])]
    del broken["mediamarkt.at"]  # the cookie wall is fixed now
    child = tmp_path / "retry_20260929_171000"
    child.mkdir()
    (child / "analyst_plan.json").write_text(json.dumps(retry_plan))
    jobs._update(child, kind="scrape", status="queued", heartbeat=jobs._now(), merge_into=str(parent))
    jobs.run_worker(child)

    merged = history.load_run(parent)
    assert len(merged["final"]) == 9  # 3 (DE tv) + 3 (DE phone) + 3 recovered AT phones
    assert sorted(merged["final"].loc[merged["final"]["marketplace"] == "mediamarkt.at", "search_id"]
                  .unique()) == [2]
    assert [f["domain"] for f in retry.failed_storefronts(parent)] == ["mediamarkt.ch"]
    assert jobs.read_job(child)["summary"]["added_listings"] == 3
    assert "Retry" in set(history.list_runs(tmp_path)["type"])
