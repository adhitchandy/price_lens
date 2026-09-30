"""Retry the storefronts that delivered nothing, resume a paused run, and merge the extra run
into the original research.

A storefront counts as *attempted* once it has a checkpoint (collected, maybe with 0 listings),
a failure marker, or appears in a collection report - in the research itself or in any retry /
resume run already merged into it. *Remaining* storefronts were never attempted: that is what
"Resume" collects. *Failed* storefronts were attempted without listings: that is what "Retry"
offers."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd

from price_lens.core import fx

from .analyst import CATALOG, compile_analyst_plan, upgrade_to_v2, write_run_outputs
from .health import storefront_check_table

GOOD = {"OK", "Partial"}


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scan_checkpoints(folder: Path, mapping: dict[int, int], found: dict) -> None:
    for path in folder.glob("search_*/*/*/checkpoints/*"):
        try:
            sid = mapping.get(int(path.parts[-5].split("_")[1]), int(path.parts[-5].split("_")[1]))
        except (IndexError, ValueError):
            continue
        if path.suffix == ".csv":
            try:
                rows = max(0, sum(1 for _ in path.open(encoding="utf-8-sig", errors="replace")) - 1)
            except OSError:
                rows = 0
            key = (sid, path.stem)
            found[key] = max(found.get(key, 0), rows)
        elif path.name.endswith(".failed.txt"):
            key = (sid, path.name[: -len(".failed.txt")])
            found.setdefault(key, 0)
            try:
                found.setdefault(("error",) + key, path.read_text(encoding="utf-8")[:300])
            except OSError:
                pass


def attempted_storefronts(run_dir: Path) -> dict:
    """{(search_id, domain): listings} for every storefront already tried, in this research
    and in retry/resume runs merged into it. Also holds ("error", sid, domain) -> message."""
    run_dir = Path(run_dir)
    found: dict = {}
    _scan_checkpoints(run_dir, {}, found)
    merged = [e.get("retry_run") for e in (_read_json(run_dir / "retries.json") or [])]
    for name in [n for n in merged if n]:
        extra = run_dir.parent / name
        plan = _read_json(extra / "analyst_plan.json") or {}
        mapping = {i: s.get("origin_search_id", i) for i, s in enumerate(plan.get("searches", []), start=1)}
        _scan_checkpoints(extra, mapping, found)
    report = _read_json(run_dir / "collection_report.json") or {}
    for rep in report.get("searches", []):
        sid = rep.get("search_id")
        for platform_report in ((rep.get("report") or {}).get("platform_reports") or {}).values():
            for event in platform_report.get("events", []):
                if event.get("marketplace") and "listings" in event:
                    key = (sid, event["marketplace"])
                    found[key] = max(found.get(key, 0), int(event.get("listings") or 0))
            for failure in platform_report.get("failures", []):
                if failure.get("marketplace"):
                    found.setdefault((sid, failure["marketplace"]), 0)
    return found


def _preview(run_dir: Path) -> list[dict]:
    plan = _read_json(Path(run_dir) / "analyst_plan.json")
    return compile_analyst_plan(plan)[1] if plan else []


def remaining_storefronts(run_dir: Path) -> list[dict]:
    """Storefronts of the plan that were never attempted (what "Resume" collects)."""
    run_dir = Path(run_dir)
    report = _read_json(run_dir / "collection_report.json") or {}
    # a search the research itself ran to the end tried all its storefronts
    finished = {r.get("search_id") for r in report.get("searches", [])
                if "report" in r and not r.get("retry_run")
                and r.get("status") not in {"paused", "cancelled"}}
    attempted = attempted_storefronts(run_dir)
    out, seen = [], set()
    for row in _preview(run_dir):
        key = (row["search_id"], row["domain"])
        if key in seen or key in attempted or row["search_id"] in finished:
            continue
        seen.add(key)
        out.append({"search_id": row["search_id"], "platform": row["platform"],
                    "domain": row["domain"], "country": row["country"]})
    return out


def failed_storefronts(run_dir: Path) -> list[dict]:
    """[{search_id, platform, domain, country, result, problem}] tried without products
    (storefronts not tried yet are "remaining" and are collected by Resume instead)."""
    run_dir = Path(run_dir)
    attempted = attempted_storefronts(run_dir)
    remaining = {(r["search_id"], r["domain"]) for r in remaining_storefronts(run_dir)}
    plan = _read_json(run_dir / "analyst_plan.json")
    report = _read_json(run_dir / "collection_report.json") or {}
    if not plan:
        return []
    _, preview = compile_analyst_plan(plan)
    by_search: dict[int, list[dict]] = {}
    for rep in report.get("searches", []):  # original + any merged retries
        by_search.setdefault(rep.get("search_id"), []).append(rep)
    failed = []
    for search_id in sorted({r["search_id"] for r in preview}):
        rows = [r for r in preview if r["search_id"] == search_id]
        reps = by_search.get(search_id, [])
        rep = reps[-1] if reps else None
        if any(r.get("report") for r in reps):
            table = storefront_check_table([r for r in reps if r.get("report")], rows)
            bad = table[~table["result"].isin(GOOD)].to_dict("records")
            items = [{"search_id": search_id, "platform": b["platform"], "domain": b["storefront"],
                      "country": b["country"], "result": b["result"], "problem": b["problem"]}
                     for b in bad]
        else:  # stopped / recovered: tried storefronts without listings
            items = [{"search_id": search_id, "platform": r["platform"], "domain": r["domain"],
                      "country": r["country"], "result": "No products", "problem": ""}
                     for r in rows if (search_id, r["domain"]) in attempted]
        seen = set()
        for item in items:
            key = (item["search_id"], item["domain"])
            if key in seen or key in remaining or attempted.get(key, 0) > 0:
                continue  # already collected somewhere, or not tried yet
            seen.add(key)
            if not item.get("problem") and ("error",) + key in attempted:
                item["problem"] = attempted[("error",) + key]
            failed.append(item)
    return failed


def build_retry_plan(plan: dict, storefronts: list[dict]) -> dict:
    """A plan with the same searches/settings, restricted to the given storefronts."""
    v2 = upgrade_to_v2(copy.deepcopy(plan))
    wanted: dict[int, dict[str, set[str]]] = {}
    for item in storefronts:
        wanted.setdefault(item["search_id"], {}).setdefault(item["platform"], set()).add(
            CATALOG[item["platform"]][item["domain"]]["country"])
    searches = []
    for index, search in enumerate(v2["searches"], start=1):
        if index not in wanted:
            continue
        retry = copy.deepcopy(search)
        retry["origin_search_id"] = index
        retry["targets"] = [
            {"platform": platform, "countries": sorted(countries), "platform_options": {}}
            for platform, countries in wanted[index].items()
        ]
        searches.append(retry)
    return {**v2, "searches": searches,
            "research_question": v2.get("research_question") or "Retry"}


def merge_retry(parent_dir: Path, retry_dir: Path) -> dict:
    """Add a finished retry run's listings and reports to the original run."""
    parent_dir, retry_dir = Path(parent_dir), Path(retry_dir)
    retry_plan = _read_json(retry_dir / "analyst_plan.json") or {}
    mapping = {i: s.get("origin_search_id", i)
               for i, s in enumerate(retry_plan.get("searches", []), start=1)}

    def read(folder: Path, name: str) -> pd.DataFrame:
        path = folder / name
        if not path.exists() or path.stat().st_size < 5:
            return pd.DataFrame()
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    cleaned_new, raw_new = read(retry_dir, "detailed_products.csv"), read(retry_dir, "raw_products.csv")
    parent_fx = fx.load_for_run(parent_dir)
    if parent_fx:  # one rate table per research
        cleaned_new, raw_new = fx.apply(cleaned_new, parent_fx["rates"]), fx.apply(raw_new, parent_fx["rates"])
    for frame in (cleaned_new, raw_new):
        if "search_id" in frame.columns:
            frame["search_id"] = frame["search_id"].map(mapping).fillna(frame["search_id"])
    cleaned = [f for f in (read(parent_dir, "detailed_products.csv"), cleaned_new) if not f.empty]
    raw = [f for f in (read(parent_dir, "raw_products.csv"), raw_new) if not f.empty]

    parent_reports = (_read_json(parent_dir / "collection_report.json") or {}).get("searches", [])
    retry_reports = (_read_json(retry_dir / "collection_report.json") or {}).get("searches", [])
    for rep in retry_reports:
        rep["search_id"] = mapping.get(rep.get("search_id"), rep.get("search_id"))
        rep["retry_run"] = retry_dir.name
    write_run_outputs(parent_dir, cleaned, raw, [*parent_reports, *retry_reports])
    added = len(cleaned_new)
    history_file = parent_dir / "retries.json"
    log = _read_json(history_file) or []
    log.append({"retry_run": retry_dir.name, "added_listings": added})
    history_file.write_text(json.dumps(log, indent=2), encoding="utf-8")
    outdated = (parent_dir / "ai_review" / "manifest.json").exists() and added > 0
    if outdated:
        from price_lens.agent.review import mark_review_outdated

        mark_review_outdated(parent_dir / "ai_review", f"retry {retry_dir.name}", added)
    return {"added": added, "review_outdated": outdated}


# ---------------------------------------------------------------------------------------
# Finishing a retry / resume run
# ---------------------------------------------------------------------------------------
def _already_merged(parent_dir: Path, retry_dir: Path) -> bool:
    return any(e.get("retry_run") == Path(retry_dir).name
               for e in (_read_json(Path(parent_dir) / "retries.json") or []))


def update_parent_status(parent_dir: Path, paused: bool = False) -> str:
    """After extra listings were merged in: paused while storefronts remain, otherwise
    completed (or partial when some storefronts returned nothing)."""
    from .jobs import _now, _update

    parent_dir = Path(parent_dir)
    if paused or remaining_storefronts(parent_dir):
        status = "paused"
    else:
        status = "partial" if failed_storefronts(parent_dir) else "completed"
    _update(parent_dir, status=status, updated_at=_now())
    return status


def finish_merge(retry_dir: Path, paused: bool = False) -> dict:
    """Merge a retry/resume run into its research once (safe to call again)."""
    from .jobs import _update, read_job

    retry_dir = Path(retry_dir)
    job = read_job(retry_dir, log_lines=0)
    parent = Path(job["merge_into"])
    parent = retry_dir.parent / parent.name  # the project folder may have moved
    if job.get("merged") or _already_merged(parent, retry_dir):
        return {"added": 0, "review_outdated": False, "already": True}
    merged = merge_retry(parent, retry_dir)
    _update(retry_dir, merged=True)
    update_parent_status(parent, paused=paused)
    return merged


def recover_unmerged(parent_dir: Path) -> list[str]:
    """A retry/resume run that stopped without merging (computer shut down, crash, force stop):
    rebuild it from its checkpoints and merge it, so nothing collected is lost."""
    from .analyst import recover_run
    from .jobs import JOB_FILE, _update, is_active, read_job

    parent_dir = Path(parent_dir)
    done = []
    for job_file in parent_dir.parent.glob(f"retry_*/{JOB_FILE}"):
        extra = job_file.parent
        job = read_job(extra, log_lines=0)
        if (job.get("merged") or is_active(job) or not job.get("merge_into")
                or Path(job["merge_into"]).name != parent_dir.name
                or _already_merged(parent_dir, extra)):
            continue
        if job.get("status") not in {"crashed", "cancelled", "failed", "recovered"}:
            continue
        if not any(extra.glob("search_*/*/*/checkpoints/*.csv")):
            _update(extra, merged=True)  # nothing to add
            continue
        recover_run(extra, reason="Stopped before the end")
        _update(extra, status="recovered")
        finish_merge(extra, paused=True)
        done.append(extra.name)
    return done
