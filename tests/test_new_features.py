import json
import re
import time

import pandas as pd
import pytest

from price_lens.core.budget import collected_count, per_audience_target
from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ScrapeReport
from price_lens.core.term_translations import suggest_translations
from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator import history, jobs, registry
from price_lens.orchestrator.analyst import compile_analyst_plan
from price_lens.orchestrator.health import classify_problem, storefront_check_table
from price_lens.orchestrator.registry import MarketplaceAdapter


def plan_v2(countries=("Germany",), target=None, pages=1):
    execution = {"pages": pages, "retries": 0, "headless": True, "delay_seconds": [0.5, 0.5]}
    if target:
        execution["products_per_storefront"] = target
    return {
        "schema_version": "analyst-v2", "research_question": "Phones",
        "execution": execution,
        "searches": [
            {"id": "s1", "product_type": "Smartphones",
             "query": {"default": "Smartphone", "translations": {},
                       "filters": {"include": [], "exclude": ["case"], "min_price": None, "max_price": None}},
             "targets": [{"platform": "mediamarkt", "countries": list(countries), "platform_options": {}}]},
            {"id": "s2", "product_type": "Laptops",
             "query": {"default": "Laptop", "translations": {}, "filters": {}},
             "targets": [{"platform": "mediamarkt", "countries": ["Austria"], "platform_options": {}}]},
        ],
    }


def adapter(rows_per_domain=3, fail=()):
    def collect(plan, log):
        domain = plan.marketplaces[0]
        log(f"collecting {domain}")
        if domain in fail:
            raise RuntimeError("Cookie consent dialog did not close")
        term = plan.searches[0].search_term
        frame = pd.DataFrame([
            {"platform": "mediamarkt", "marketplace": domain, "product_name": f"{term} {i}",
             "search_term": term, "price_value": 100.0 + i, "price_usd": 100.0 + i,
             "currency_code": "EUR", "product_id": f"{domain}-{term}-{i}", "sponsored": False,
             "rating": 4.0, "origin_country": "X"} for i in range(rows_per_domain)
        ])
        report = ScrapeReport(platform="mediamarkt", status="completed", pages_succeeded=1)
        report.events.append({"marketplace": domain, "page": 1, "listings": rows_per_domain,
                              "status": "succeeded", "final_url": f"https://www.{domain}/x"})
        return ScrapeOutcome(frame, report)
    return MarketplaceAdapter("mediamarkt", collect)


def make_job(tmp_path, plan, kind="scrape"):
    run_dir = tmp_path / f"{'analyst' if kind == 'scrape' else 'check'}_20260929_120000"
    run_dir.mkdir()
    (run_dir / "analyst_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (run_dir / "log.txt").write_text("", encoding="utf-8")
    jobs._update(run_dir, kind=kind, status="queued", heartbeat=jobs._now())
    return run_dir


# --- product target ---------------------------------------------------------
def test_products_per_storefront_sets_target_and_max_pages():
    plans, _ = compile_analyst_plan(plan_v2(target=40))
    assert plans[0].max_products == 40 and plans[0].pages == 20
    assert plans[0].platform_plan("mediamarkt").max_products == 40
    plans, _ = compile_analyst_plan(plan_v2(pages=3))
    assert plans[0].max_products is None and plans[0].pages == 3


def test_bad_target_is_rejected():
    with pytest.raises(RequestValidationError):
        compile_analyst_plan(plan_v2(target=-5))


def test_budget_helpers_and_truncation():
    rows = [{"marketplace": "a", "search_term": "t", "product_id": str(i)} for i in range(5)]
    rows.append({"marketplace": "a", "search_term": "t", "product_id": "1"})
    assert collected_count(rows, "a", "t") == 5
    assert collected_count(rows, "b", "t") == 0
    assert per_audience_target(100, 3) == 34 and per_audience_target(None, 3) is None


def test_mediamarkt_scraper_stops_at_target(monkeypatch):
    from price_lens.marketplaces.mediamarkt import scraper as mm
    from price_lens.marketplaces.mediamarkt.scraper import BatchRows

    driver = type("D", (), {"quit": lambda self: None, "set_page_load_timeout": lambda self, _: None,
                            "current_url": "https://www.mediamarkt.de/x", "page_source": ""})()
    calls = {"n": 0}

    def fresh(*_a, **_k):
        calls["n"] += 1
        return BatchRows([{"product_id": f"{calls['n']}-{i}", "product_name": "p", "marketplace":
                           "mediamarkt.de", "search_term": "phone", "price_value": 1.0}
                          for i in range(12)])

    monkeypatch.setattr(mm, "_start_search", lambda *a: None)
    monkeypatch.setattr(mm, "_advance_page", lambda *a: "click")
    monkeypatch.setattr(mm, "_wait_for_new_rows", fresh)
    monkeypatch.setattr(mm, "listing_state", lambda _h: {"total": 999, "loaded": 1, "counter": ""})
    monkeypatch.setattr(mm.time, "sleep", lambda _s: None)
    outcome = mm.MediaMarktScraper(driver_factory=lambda options: driver).search_with_report(
        {"phone": [{"type": "Phone", "include": [], "exclude": []}]}, ["mediamarkt.de"],
        pages=20, delay=(0, 0), max_products=30)
    assert calls["n"] == 3 and len(outcome.raw_products) == 36


# --- background jobs --------------------------------------------------------
def test_worker_runs_plan_and_records_status(tmp_path, monkeypatch):
    monkeypatch.setitem(registry.MARKETPLACE_REGISTRY, "mediamarkt", adapter())
    run_dir = make_job(tmp_path, plan_v2())
    assert jobs.run_worker(run_dir) == 0
    job = jobs.read_job(run_dir)
    assert job["status"] == "completed" and job["summary"]["listings"] == 6
    assert "collecting mediamarkt.de" in job["log"]
    assert (run_dir / "final_products.csv").exists()


def test_cancel_keeps_finished_searches(tmp_path, monkeypatch):
    run_dir = make_job(tmp_path, plan_v2())
    base = adapter()

    def collect(plan, log):
        if plan.marketplaces[0] == "mediamarkt.at":
            jobs.request_cancel(run_dir)
        return base.collect(plan, log)

    monkeypatch.setitem(registry.MARKETPLACE_REGISTRY, "mediamarkt", MarketplaceAdapter("mediamarkt", collect))
    jobs.run_worker(run_dir)
    job = jobs.read_job(run_dir)
    assert job["status"] == "cancelled"
    report = json.loads((run_dir / "collection_report.json").read_text(encoding="utf-8"))
    assert [s["status"] for s in report["searches"]] == ["completed", "cancelled"]
    assert len(pd.read_csv(run_dir / "final_products.csv")) == 3


def test_stale_heartbeat_is_reported_as_crashed(tmp_path):
    run_dir = make_job(tmp_path, plan_v2())
    jobs._update(run_dir, status="running", heartbeat="2020-01-01T00:00:00+00:00")
    assert jobs.read_job(run_dir)["status"] == "crashed"
    assert jobs.find_active_jobs(tmp_path) == []


def test_real_subprocess_worker_starts_and_finishes(tmp_path):
    """Spawns the real worker process; without a browser the scrape fails fast but cleanly."""
    run_dir = jobs.start_job(plan_v2(), tmp_path / "output")
    deadline = time.time() + 120
    while jobs.is_active(jobs.read_job(run_dir)) and time.time() < deadline:
        time.sleep(0.5)
    job = jobs.read_job(run_dir)
    assert job["status"] in {"completed", "partial", "failed"}, job
    assert (run_dir / "collection_report.json").exists()


# --- storefront check -------------------------------------------------------
def test_storefront_check_table(tmp_path, monkeypatch):
    monkeypatch.setitem(registry.MARKETPLACE_REGISTRY, "mediamarkt",
                        adapter(fail=("mediamarkt.at",)))
    run_dir = make_job(tmp_path, plan_v2(countries=("Germany", "Austria"), target=50), kind="check")
    jobs.run_worker(run_dir)
    table = pd.read_csv(run_dir / "storefront_check.csv").set_index("storefront")
    assert table.loc["mediamarkt.de", "result"] == "OK"
    assert table.loc["mediamarkt.at", "result"] == "Cookie wall"
    # one probe per platform, countries merged, one page only
    probe = jobs.check_plan(plan_v2(countries=("Germany",)))
    assert len(probe["searches"]) == 1 and probe["execution"]["pages"] == 1
    assert set(probe["searches"][0]["targets"][0]["countries"]) == {"Germany", "Austria"}
    assert classify_problem("verify you are human") == "Bot check"
    assert storefront_check_table([], []).empty


# --- review helpers ---------------------------------------------------------
def _review(tmp_path, names, batch_size=5):
    from price_lens.agent.review import prepare_review_batches

    source = tmp_path / "detailed_products.csv"
    pd.DataFrame([{"search_id": 1, "platform": "mediamarkt", "marketplace": "mediamarkt.de",
                   "product_name": n, "price_value": 100.0 + i, "currency_code": "EUR",
                   "product_url": f"https://x/{i}"} for i, n in enumerate(names)]).to_csv(source, index=False)
    prepare_review_batches(source, tmp_path / "ai_review", research_question="Phones",
                           instruction="Keep phones", batch_size=batch_size)
    return tmp_path / "ai_review"


def test_compact_prompt_and_line_answers(tmp_path):
    from price_lens.agent import assist
    from price_lens.agent.review import apply_review_decisions

    review_dir = _review(tmp_path, ["iPhone 17", "iPhone 17 Hülle"])
    prompt = assist.compact_prompt(list(assist.batch_files(review_dir).values()))
    assert "p001 | iPhone 17 | - | 100.00 EUR | mediamarkt.de" in prompt
    assert "https://" not in prompt and "product_" not in prompt  # no URLs / long ids
    answer = "Sure!\n```\np001|keep|0.95|smartphone|complete phone\np002|drop|97%|case|accessory\n```"
    result = assist.save_answer(review_dir, assist.pending_batches(review_dir), answer)
    assert result == {"saved": 2, "missing": 0, "followups": [], "unanswered_batches": []}
    report = apply_review_decisions(review_dir)
    assert report["accepted"] == 1 and report["excluded"] == 1
    final = pd.read_csv(review_dir / "final_products.csv")
    assert list(final["search_id"]) == [1]


def test_partial_answer_creates_followup_batch(tmp_path):
    from price_lens.agent import assist
    from price_lens.agent.review import apply_review_decisions

    review_dir = _review(tmp_path, [f"Phone {i}" for i in range(7)], batch_size=4)
    assert assist.pending_batches(review_dir) == ["batch_001", "batch_002"]
    # one prompt for everything; the chat "ran out" after four products
    answer = "\n".join(f"p00{i}|keep|0.9|phone|ok" for i in range(1, 5))
    result = assist.save_answer(review_dir, ["batch_001", "batch_002"], answer)
    assert result["saved"] == 4 and result["unanswered_batches"] == ["batch_002"]
    assert assist.pending_batches(review_dir) == ["batch_002"]
    # batch_002 answered partly -> skipped rows move to a follow-up batch
    result = assist.save_answer(review_dir, ["batch_002"], "p005|keep|0.9|phone|ok")
    assert result["missing"] == 2 and result["followups"] == ["batch_002_rest1"]
    assert assist.pending_batches(review_dir) == ["batch_002_rest1"]
    assert assist.pending_products(review_dir) == 2
    with pytest.raises(RequestValidationError, match="No usable decisions"):
        assist.save_answer(review_dir, ["batch_002_rest1"], "I could not do this")
    assist.save_answer(review_dir, ["batch_002_rest1"],
                       '{"decisions": [{"ref": "p006", "keep": false, "confidence": 0.9, '
                       '"category": "x", "reason": "y"}, {"ref": "p007", "keep": "yes", '
                       '"confidence": "0.8", "category": "phone", "reason": "ok"}]}')
    report = apply_review_decisions(review_dir)
    assert report["reviewed"] == 7 and report["excluded"] == 1


def test_parallel_claude_review_with_retry_round(tmp_path):
    from price_lens.agent import assist

    review_dir = _review(tmp_path, [f"Phone {i}" for i in range(9)], batch_size=3)
    calls = []

    def fake_call(prompt):
        refs = re.findall(r"^(p\d{3}) \|", prompt, re.M)
        calls.append(refs)
        answered = refs if len(calls) > 1 else refs[:-1]   # first reply skips one row
        return "\n".join(f"{r}|keep|0.9|phone|ok" for r in answered)

    outcome = assist.review_with_claude(review_dir, workers=3, call=fake_call)
    assert outcome["pending"] == [] and outcome["saved"] == 9 and not outcome["errors"]
    assert len(calls) == 4  # 3 batches in parallel + 1 follow-up for the skipped row


# --- translations -----------------------------------------------------------
def test_exclude_word_suggestions():
    found, unknown = suggest_translations(["case", "hülle", "xyz"], ["de", "pl"])
    assert "etui" in found["case"] and "schutzhülle" in found["case"]
    assert "hülle" not in sum(found.values(), [])  # already present
    assert unknown == ["xyz"]


# --- history ----------------------------------------------------------------
def test_history_lists_opens_and_deletes(tmp_path, monkeypatch):
    monkeypatch.setitem(registry.MARKETPLACE_REGISTRY, "mediamarkt", adapter())
    good = make_job(tmp_path, plan_v2())
    jobs.run_worker(good)
    bad = tmp_path / "analyst_20250101_000000"
    bad.mkdir()
    (bad / "collection_report.json").write_text(json.dumps({"searches": [{"search_id": 1, "status": "failed"}]}))
    runs = history.list_runs(tmp_path)
    assert list(runs["status"]) == ["completed", "failed"]
    assert runs.loc[0, "listings"] == 6
    assert history.load_run(good)["final"].shape[0] == 6
    assert history.is_empty_failure(bad) and not history.is_empty_failure(good)
    history.delete_run(bad, tmp_path)
    assert not bad.exists()
    with pytest.raises(ValueError):
        history.delete_run(tmp_path, tmp_path.parent)


def test_delete_retries_locked_folders_and_falls_back_to_trash(tmp_path, monkeypatch):
    import os as _os
    import shutil as _shutil

    run = tmp_path / "analyst_20260101_000000"
    (run / "search_001" / "mediamarkt").mkdir(parents=True)
    (run / "search_001" / "mediamarkt" / "x.csv").write_text("a")
    real_rmdir = _os.rmdir
    fails = {"n": 2}

    def flaky_rmdir(path, *a, **k):  # OneDrive-style: locked for a moment, then fine
        if fails["n"] > 0 and str(path).endswith("mediamarkt"):
            fails["n"] -= 1
            raise PermissionError(5, "Access is denied")
        return real_rmdir(path, *a, **k)

    monkeypatch.setattr(_os, "rmdir", flaky_rmdir)
    monkeypatch.setattr(history.time, "sleep", lambda _s: None)
    history.delete_run(run, tmp_path)
    assert not run.exists()

    # permanently locked: the run is moved to output/.trash and hidden from the history
    run2 = tmp_path / "analyst_20260102_000000"
    (run2 / "locked").mkdir(parents=True)
    monkeypatch.setattr(_os, "rmdir", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied")))
    history.delete_run(run2, tmp_path)
    assert not run2.exists()
    assert any((tmp_path / ".trash").iterdir())
    assert history.list_runs(tmp_path).empty
    monkeypatch.setattr(_os, "rmdir", real_rmdir)
    history.purge_trash(tmp_path)
    assert not any((tmp_path / ".trash").iterdir())
    assert _shutil  # keep import used
