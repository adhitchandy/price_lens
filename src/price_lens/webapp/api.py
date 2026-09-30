"""What the web app can ask for. Plain functions: data in, data out.

``server.py`` maps URLs to these functions; tests call them directly. Everything reads and
writes the same output folder as the command line and the Streamlit app.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from price_lens import __version__
from price_lens.agent import assist
from price_lens.agent import review as rv
from price_lens.core import fx
from price_lens.core.term_translations import suggest_translations
from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator import (
    history,
    jobs,
    planning,
    price_report,
    retry,
    screens,
    storefront_status,
)
from price_lens.orchestrator.analyst import (
    CATALOG,
    compile_analyst_plan,
    load_analyst_text,
    upgrade_to_v2,
)
from price_lens.orchestrator.audiences import audience_query, search_audiences
from price_lens.orchestrator.health import storefront_check_table

ROOT = Path(__file__).resolve().parents[3]
AUDIENCES = ["men", "women", "kids"]
FORCE_STOP_AFTER_SECONDS = 20
DRAFTS_DIR = "drafts"
SETTINGS_FILE = "app_settings.json"
META_FILE = "research_meta.json"
DEFAULT_EXECUTION = {
    "products_per_storefront": 100, "pages": 1, "retries": 2, "headless": False,
    "delay_seconds": [2.5, 4.5], "enrich_details": False, "max_detail_products": 30,
}
RAW_FILES = {
    "final_products.csv": "text/csv", "detailed_products.csv": "text/csv",
    "raw_products.csv": "text/csv", "analyst_plan.json": "application/json",
    "log.txt": "text/plain", "storefront_check.csv": "text/csv",
    "ai_review/final_products.csv": "text/csv",
    "ai_review/final_products.xlsx": screens.XLSX_MIME,
    "ai_review/ai_classified_products.csv": "text/csv",
}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class FileResult:
    data: bytes
    name: str
    mime: str


def output_dir() -> Path:
    """PI_OUTPUT_DIR overrides the folder (tests); read on every call."""
    path = Path(os.environ.get("PI_OUTPUT_DIR") or ROOT / "output")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(20):  # OneDrive / antivirus can hold the file for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    raise ApiError("Could not save (the file is in use by another program). Try again.", 423)


def _clean_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number or number in (float("inf"), float("-inf")) else round(number, 2)


# ---------------------------------------------------------------------------------------
# Catalogue and settings
# ---------------------------------------------------------------------------------------
def settings() -> dict:
    stored = _read_json(output_dir() / SETTINGS_FILE, {}) or {}
    return {"execution": {**DEFAULT_EXECUTION, **(stored.get("execution") or {})}}


def save_settings(body: dict) -> dict:
    execution = {**DEFAULT_EXECUTION, **((body or {}).get("execution") or {})}
    _write_json(output_dir() / SETTINGS_FILE, {"execution": execution})
    return settings()


def meta() -> dict:
    platforms = {
        platform: sorted(({"domain": d, "country": i["country"], "language": i["language"]}
                          for d, i in domains.items()), key=lambda x: x["country"])
        for platform, domains in CATALOG.items()
    }
    return {
        "platforms": platforms,
        "country_groups": planning.COUNTRY_GROUPS,
        "product_presets": planning.PRODUCT_PRESETS,
        "audiences": AUDIENCES,
        "languages": planning.LANGUAGE_NAMES,
        "claude_api": assist.api_available(),
        "output_dir": str(output_dir()),
        "settings": settings(),
        "version": __version__,
    }


# ---------------------------------------------------------------------------------------
# Drafts (plans that have not run yet)
# ---------------------------------------------------------------------------------------
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


def _draft_path(draft_id: str) -> Path:
    if not _ID.match(draft_id or ""):
        raise ApiError("Unknown draft", 404)
    return output_dir() / DRAFTS_DIR / f"{draft_id}.json"


def _new_search(number: int) -> dict:
    return {"id": f"search_{number}", "product_type": "",
            "query": {"default": "", "translations": {},
                      "filters": {"include": [], "exclude": [], "min_price": None, "max_price": None}},
            "targets": []}


def new_plan() -> dict:
    return {"schema_version": "analyst-v2", "research_question": "",
            "execution": copy.deepcopy(settings()["execution"]), "searches": [_new_search(1)]}


def list_drafts() -> list[dict]:
    folder = output_dir() / DRAFTS_DIR
    drafts = []
    for path in sorted(folder.glob("*.json"), reverse=True) if folder.exists() else []:
        data = _read_json(path)
        if isinstance(data, dict) and data.get("id"):
            drafts.append(data)
    return drafts


def get_draft(draft_id: str) -> dict:
    data = _read_json(_draft_path(draft_id))
    if not data:
        raise ApiError("This draft no longer exists.", 404)
    return data


def create_draft(body: dict | None = None) -> dict:
    body = body or {}
    plan = body.get("plan")
    goal = body.get("goal", "")
    if body.get("from_run"):
        run_dir = _run_dir(body["from_run"])
        plan = _read_json(run_dir / jobs.PLAN_FILE) or new_plan()
        goal = (_read_json(run_dir / META_FILE, {}) or {}).get("goal", "")
        plan["research_question"] = f"{plan.get('research_question') or 'Research'} (copy)"
    plan = upgrade_to_v2(plan) if plan else new_plan()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    draft = {"id": f"draft_{stamp}_{uuid.uuid4().hex[:4]}", "plan": plan, "goal": goal,
             "created": _now(), "updated": _now(), "checks": []}
    _write_json(_draft_path(draft["id"]), draft)
    return draft


def save_draft(draft_id: str, body: dict) -> dict:
    draft = get_draft(draft_id)
    if "plan" in body:
        if not isinstance(body["plan"], dict):
            raise ApiError("The plan must be an object.")
        draft["plan"] = body["plan"]
    if "goal" in body:
        draft["goal"] = str(body["goal"] or "")
    draft["updated"] = _now()
    _write_json(_draft_path(draft_id), draft)
    return draft


def delete_draft(draft_id: str) -> dict:
    path = _draft_path(draft_id)
    path.unlink(missing_ok=True)
    return {"deleted": draft_id}


# ---------------------------------------------------------------------------------------
# Plan tools
# ---------------------------------------------------------------------------------------
def _search_languages(search: dict) -> list[dict]:
    """Every language this search needs, the storefronts using it and the term typed."""
    translations = (search.get("query") or {}).get("translations") or {}
    overrides = (search.get("query") or {}).get("audience_queries") or {}
    languages: dict[str, dict] = {}
    for platform, domain, country, language in planning.storefronts(search):
        entry = languages.setdefault(language, {
            "lang": language, "name": planning.LANGUAGE_NAMES.get(language, language),
            "domains": [], "countries": [], "platforms": set()})
        entry["domains"].append(domain)
        entry["platforms"].add(platform)
        if country not in entry["countries"]:
            entry["countries"].append(country)
    audiences = search_audiences(search)
    base_default = (search.get("query") or {}).get("default") or ""
    out = []
    for language in sorted(languages):
        entry = languages[language]
        value = translations.get(language, "")
        if isinstance(value, dict):
            value = value.get("search_term", "")
        term = (value or base_default).strip()
        non_zalando = entry["platforms"] - {"zalando"}
        entry["platforms"] = sorted(entry["platforms"])
        entry["term"] = value or ""
        entry["needed"] = language != "en" and not (value or "").strip()
        entry["audience_phrases"] = (
            {a: (overrides.get(language) or {}).get(a) or audience_query(term or "…", a, language)
             for a in audiences}
            if audiences and non_zalando and search.get("split_audiences", True) else {})
        out.append(entry)
    return out


def validate_plan(plan: dict) -> dict:
    """Check a plan and describe what it will do (the Plan screen's summary)."""
    result: dict[str, Any] = {"ok": False, "error": None, "preview": [], "storefronts": 0,
                              "queries": 0, "estimate_minutes": 0, "problems": {}, "searches": []}
    plan = plan or {}
    searches = plan.get("searches") or []
    status = storefront_status.load(output_dir())
    for search in searches:
        domains = [d for _, d, _, _ in planning.storefronts(search)]
        result["searches"].append({
            "languages": _search_languages(search),
            "problems": storefront_status.problems(status, domains),
            "storefronts": len(set(domains)),
        })
    if not searches:
        result["error"] = "Add at least one search."
        return result
    try:
        _, preview = compile_analyst_plan(plan)
    except RequestValidationError as exc:
        result["error"] = str(exc)
        return result
    except (KeyError, TypeError, ValueError) as exc:
        result["error"] = f"The plan is incomplete: {exc}"
        return result
    domains = sorted({row["domain"] for row in preview})
    result.update(
        ok=bool(preview), preview=preview, storefronts=len(domains), queries=len(preview),
        estimate_minutes=planning.estimate_minutes(preview, plan.get("execution") or {}),
        problems=storefront_status.problems(status, domains))
    if not preview:
        result["error"] = "Pick at least one platform and country."
    return result


def apply_quick_setup(body: dict) -> dict:
    search = copy.deepcopy(body.get("search") or {})
    notes: list[str] = []
    if body.get("preset"):
        if body["preset"] not in planning.PRODUCT_PRESETS:
            raise ApiError("Unknown product type preset.")
        notes += planning.apply_product_preset(search, body["preset"])
    if body.get("group"):
        if body["group"] not in planning.COUNTRY_GROUPS:
            raise ApiError("Unknown country group.")
        if not search.get("targets"):
            raise ApiError("Pick a platform first, then a country group.")
        notes += planning.apply_country_group(search, body["group"])
    return {"search": search, "notes": notes}


def suggest_excludes(body: dict) -> dict:
    found, unknown = suggest_translations(list(body.get("words") or []), list(body.get("languages") or []))
    existing = {w.lower() for w in body.get("words") or []}
    words = [w for values in found.values() for w in values if w.lower() not in existing]
    return {"words": list(dict.fromkeys(words)), "unknown": unknown}


def planning_prompt(body: dict) -> dict:
    request = str((body or {}).get("request") or "").strip()
    if not request:
        raise ApiError("Describe your research first.")
    skill = ROOT / "agent" / "llmskill.md"
    text = skill.read_text(encoding="utf-8") if skill.exists() else ""
    return {"prompt": f"{text}\n\n## Research request\n\n{request}\n"}


def import_plan(body: dict) -> dict:
    text = str((body or {}).get("text") or "")
    if not text.strip():
        raise ApiError("Paste a plan or choose a file first.")
    try:
        return {"plan": upgrade_to_v2(load_analyst_text(text))}
    except RequestValidationError as exc:
        raise ApiError(f"The plan is not valid: {exc}") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise ApiError(f"Could not read the plan: {exc}") from exc


def start(body: dict) -> dict:
    """Start collecting (kind 'scrape') or a storefront check (kind 'check') for a draft."""
    kind = body.get("kind", "scrape")
    draft = get_draft(body.get("draft", ""))
    check = validate_plan(draft["plan"])
    if not check["ok"]:
        raise ApiError(check["error"] or "The plan is not ready yet.")
    if kind == "scrape" and jobs.find_active_jobs(output_dir()):
        raise ApiError("Another collection is still running. Wait for it or stop it first.", 409)
    try:
        run_dir = jobs.start_job(copy.deepcopy(draft["plan"]), output_dir(), kind=kind)
    except (OSError, ValueError) as exc:
        raise ApiError(f"Could not start: {exc}", 500) from exc
    if kind == "check":
        draft.setdefault("checks", []).append(run_dir.name)
        _write_json(_draft_path(draft["id"]), draft)
    else:
        _write_json(run_dir / META_FILE, {"goal": draft.get("goal", ""), "draft": draft["id"],
                                          "checks": draft.get("checks", [])})
        _draft_path(draft["id"]).unlink(missing_ok=True)
    return {"run": run_dir.name, "kind": kind}


# ---------------------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------------------
def _run_dir(name: str) -> Path:
    if not _ID.match(name or "") or not name.startswith(history.RUN_PREFIXES):
        raise ApiError("Unknown research", 404)
    path = output_dir() / name
    if not path.is_dir():
        raise ApiError("This research no longer exists.", 404)
    return path


_stats_cache: dict[tuple[str, float], dict] = {}


def _price_stats(csv_path: Path) -> dict:
    try:
        key = (str(csv_path), csv_path.stat().st_mtime)
    except OSError:
        return {"listings": 0, "median": None, "lo": None, "hi": None}
    if key not in _stats_cache:
        try:
            frame = pd.read_csv(csv_path, encoding="utf-8-sig", usecols=lambda c: c in {"price_usd"})
            usd = pd.to_numeric(frame.get("price_usd", pd.Series(dtype=float)), errors="coerce").dropna()
            rows = len(frame)
        except (OSError, ValueError, pd.errors.EmptyDataError):
            usd, rows = pd.Series(dtype=float), 0
        _stats_cache[key] = {
            "listings": rows,
            "median": _clean_number(usd.median()) if len(usd) else None,
            "lo": _clean_number(usd.quantile(0.05)) if len(usd) else None,
            "hi": _clean_number(usd.quantile(0.95)) if len(usd) else None,
        }
    return _stats_cache[key]


def _v2(plan: dict) -> dict:
    """Researches made with the first plan format are shown in the current one."""
    try:
        return upgrade_to_v2(plan) if plan else plan
    except (KeyError, TypeError, ValueError, AttributeError):
        return plan


def _plan_summary(plan: dict) -> dict:
    plan = _v2(plan)
    platforms, countries, domains = [], set(), set()
    for search in (plan or {}).get("searches") or []:
        for platform, domain, country, _ in planning.storefronts(search):
            if platform not in platforms:
                platforms.append(platform)
            countries.add(country)
            domains.add(domain)
    return {"platforms": platforms, "countries": len(countries), "storefronts": len(domains),
            "searches": len((plan or {}).get("searches") or [])}


_remaining_cache: dict[str, tuple[tuple, list[dict]]] = {}


def _remaining(run_dir: Path) -> list[dict]:
    """Storefronts not collected yet (cached until the research's files change)."""
    def stamp(name: str) -> tuple:
        try:
            info = (run_dir / name).stat()
            return info.st_mtime_ns, info.st_size  # size too: timestamps can be coarse
        except OSError:
            return (0, 0)
    key = tuple(stamp(n) for n in (jobs.JOB_FILE, "collection_report.json", "retries.json",
                                   jobs.PLAN_FILE, "detailed_products.csv"))
    cached = _remaining_cache.get(str(run_dir))
    if not cached or cached[0] != key:
        try:
            value = retry.remaining_storefronts(run_dir)
        except (OSError, ValueError, KeyError, RequestValidationError):
            value = []
        _remaining_cache[str(run_dir)] = (key, value)
        cached = _remaining_cache[str(run_dir)]
    return cached[1]


def _remaining_count(run_dir: Path) -> int:
    return len(_remaining(run_dir))


def _active_merges() -> dict[str, str]:
    """research name -> active retry/resume run adding to it."""
    out = {}
    for other in jobs.find_active_jobs(output_dir()):
        merge_into = jobs.read_job(other, log_lines=0).get("merge_into")
        if merge_into:
            out[Path(merge_into).name] = other.name
    return out


def _status(run_dir: Path, job: dict | None = None) -> tuple[str, str]:
    """(key, label) for lists and headers."""
    job = job if job is not None else (jobs.read_job(run_dir, log_lines=0)
                                       if (run_dir / jobs.JOB_FILE).exists() else {})
    if jobs.is_active(job):
        return "running", "Collecting"
    if run_dir.name.startswith("analyst_") and _remaining_count(run_dir):
        return "paused", {"paused": "Paused", "cancelled": "Stopped"}.get(job.get("status"), "Interrupted")
    state = history.run_status(run_dir)
    review_dir = run_dir / "ai_review"
    if state in {"crashed", "failed", "incomplete"}:
        return "attention", "Needs attention" if state != "failed" else "Failed"
    if state in {"partial", "cancelled"}:
        return "attention", "Needs attention" if state == "partial" else "Stopped"
    if (review_dir / "ai_review_report.json").exists() and not rv.review_outdated(review_dir):
        return "reviewed", "Reviewed"
    return "completed", "Completed"


def research_list() -> dict:
    """Home screen: researches (runs) and drafts, newest first."""
    items = []
    root = output_dir()
    merging = _active_merges()
    for path in root.iterdir() if root.exists() else []:
        if not (path.is_dir() and path.name.startswith("analyst_")):
            continue
        plan = _read_json(path / jobs.PLAN_FILE, {}) or {}
        key, label = ("running", "Collecting") if path.name in merging else _status(path)
        reviewed = path / "ai_review" / "final_products.csv"
        stats = _price_stats(reviewed if key == "reviewed" and reviewed.exists()
                             else path / "final_products.csv")
        if key == "running" and path.name not in merging:
            stats = {**stats, "listings": screens.run_payload(
                path, jobs.read_job(path, log_lines=0))["listings"]}
        extra = {"left": _remaining_count(path) if key == "paused" else 0,
                 "searches_total": _plan_summary(plan)["searches"]}
        started = history._started(path)
        items.append({
            "id": path.name, "kind": "run", "title": plan.get("research_question") or path.name,
            "status": key, "label": label, **stats, **_plan_summary(plan), **extra,
            "updated": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "started": started.isoformat() if started else None,
        })
    for draft in list_drafts():
        items.append({
            "id": draft["id"], "kind": "draft",
            "title": draft["plan"].get("research_question") or "Untitled research",
            "status": "draft", "label": "Draft", "listings": None, "median": None, "lo": None,
            "hi": None, **_plan_summary(draft["plan"]), "updated": draft.get("updated"),
            "started": None,
        })
    items.sort(key=lambda i: i.get("updated") or "", reverse=True)
    return {"items": items, "active": [p.name for p in jobs.find_active_jobs(root)]}


def _count(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _steps(run_dir: Path, job: dict, key: str, meta_info: dict) -> list[dict]:
    review_dir = run_dir / "ai_review"
    report = _read_json(review_dir / "ai_review_report.json")
    outdated = rv.review_outdated(review_dir)
    collected = _price_stats(run_dir / "final_products.csv")["listings"]
    checks = [c for c in meta_info.get("checks", []) if (output_dir() / c).exists()]
    check_sub, check_state = "Skipped", "done"
    if checks:
        table = output_dir() / checks[-1] / "storefront_check.csv"
        if table.exists():
            frame = pd.read_csv(table, encoding="utf-8-sig")
            ok = int(frame["result"].isin(["OK", "Partial"]).sum()) if "result" in frame else 0
            check_sub = f"{ok} of {len(frame)} OK"
    collect_state = "current" if key == "running" else "done"
    if key == "running":
        collect_sub = "Collecting…"
    elif key == "paused":
        collect_sub = f"Paused · {_count(_remaining_count(run_dir), 'storefront')} left"
    else:
        collect_sub = _count(collected, "listing")
    if (review_dir / "manifest.json").exists():
        if report and not outdated:
            review_sub, review_state = f"{report['candidates']:,} kept", "done"
        elif outdated:
            review_sub, review_state = f"{outdated['added']} new to check", "todo"
        else:
            review_sub, review_state = "In progress", "todo"
    else:
        review_sub, review_state = "Optional", "todo"
    return [
        {"key": "plan", "label": "Plan", "sub": _count(_plan_summary(_read_json(run_dir / jobs.PLAN_FILE, {}))["storefronts"], "storefront"), "state": "done"},
        {"key": "check", "label": "Storefront check", "sub": check_sub, "state": check_state},
        {"key": "collect", "label": "Collect", "sub": collect_sub, "state": collect_state},
        {"key": "review", "label": "Review", "sub": review_sub,
         "state": "locked" if key == "running" else review_state},
        {"key": "results", "label": "Results", "sub": "Compare prices",
         "state": "locked" if key == "running" or not collected else "todo"},
    ]


def run_detail(name: str) -> dict:
    run_dir = _run_dir(name)
    job = jobs.read_job(run_dir, log_lines=0) if (run_dir / jobs.JOB_FILE).exists() else {}
    recovered = None
    if not jobs.is_active(job):
        try:
            recovered = history.recover_if_needed(run_dir)
        except (OSError, ValueError, KeyError):
            recovered = None
        if name.startswith("analyst_"):
            try:  # a resume/retry that stopped without adding its listings (shutdown, crash)
                if retry.recover_unmerged(run_dir) and not recovered:
                    recovered = {"merged": True}
            except (OSError, ValueError, KeyError):
                pass
        job = jobs.read_job(run_dir, log_lines=0) if (run_dir / jobs.JOB_FILE).exists() else {}
    plan = _read_json(run_dir / jobs.PLAN_FILE, {}) or {}
    meta_info = _read_json(run_dir / META_FILE, {}) or {}
    key, label = _status(run_dir, job)
    report = _read_json(run_dir / "collection_report.json", {"searches": []}) or {"searches": []}
    failed = []
    if key != "running" and name.startswith("analyst_"):
        try:
            failed = retry.failed_storefronts(run_dir)
        except (OSError, ValueError, KeyError, RequestValidationError):
            failed = []
    active_retry, active_resume = None, False
    for other in jobs.find_active_jobs(output_dir()):
        other_job = jobs.read_job(other, log_lines=0)
        merge_into = other_job.get("merge_into")
        if merge_into and Path(merge_into).name == name:
            active_retry, active_resume = other.name, bool(other_job.get("resume"))
    if active_retry:
        key, label = "running", "Collecting"
    return {
        "active_retry": active_retry, "active_retry_resume": active_resume,
        "checks": [c for c in meta_info.get("checks", []) if (output_dir() / c).exists()],
        "id": name, "kind": job.get("kind", "check" if name.startswith("check_") else "scrape"),
        "title": plan.get("research_question") or name, "goal": meta_info.get("goal", ""),
        "status": key, "label": label, "plan": _v2(plan), "summary": _plan_summary(plan),
        "job": {k: job.get(k) for k in ("status", "started_at", "finished_at", "error", "merge_into")},
        "active": jobs.is_active(job), "recovered": recovered,
        "steps": _steps(run_dir, job, key, meta_info),
        "fx": screens.short_fx(fx.load_for_run(run_dir)), "fx_title": fx.describe(fx.load_for_run(run_dir)),
        "failed_storefronts": failed,
        "searches": [_report_row(rep) for rep in report.get("searches", [])],
        "retries": _read_json(run_dir / "retries.json", []) or [],
        "files": [f for f in RAW_FILES if (run_dir / f).exists()],
        "collected": _price_stats(run_dir / "final_products.csv")["listings"],
        **_resume_info(run_dir, plan, key),
    }


def _resume_info(run_dir: Path, plan: dict, key: str) -> dict:
    left = _remaining(run_dir) if key == "paused" else []
    try:
        preview = compile_analyst_plan(plan)[1] if plan else []
    except (RequestValidationError, KeyError, ValueError):
        preview = []
    keys = {(r["search_id"], r["domain"]) for r in left}
    todo = [r for r in preview if (r["search_id"], r["domain"]) in keys]
    minutes = planning.estimate_minutes(todo, (_v2(plan) or {}).get("execution") or {}) if todo else 0
    return {"remaining": len(left), "remaining_minutes": minutes,
            "total_storefronts": len({(r["search_id"], r["domain"]) for r in preview})}


def _report_row(rep: dict) -> dict:
    inner = rep.get("report") or {}
    errors = [f"{name}: {info.get('error')}" for name, info in (inner.get("platform_reports") or {}).items()
              if info.get("error")]
    for name, info in (inner.get("platform_reports") or {}).items():
        for failure in info.get("failures") or []:
            errors.append(f"{name} {failure.get('marketplace', '')}: {failure.get('error', '')}")
    return {"search_id": rep.get("search_id"), "status": rep.get("status"),
            "raw_rows": inner.get("raw_rows"), "cleaned_rows": inner.get("cleaned_rows"),
            "retry_run": rep.get("retry_run"),
            "errors": "; ".join(filter(None, [rep.get("error"), *errors]))[:600]}


def _products(run_dir: Path, source: str) -> tuple[pd.DataFrame, dict]:
    plan = _read_json(run_dir / jobs.PLAN_FILE, {}) or {}
    labels = price_report.group_labels(plan)
    reviewed_csv = run_dir / "ai_review" / "final_products.csv"
    path = reviewed_csv if source == "reviewed" and reviewed_csv.exists() else run_dir / "final_products.csv"
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, pd.errors.EmptyDataError):
        frame = pd.DataFrame()
    return price_report.prepare_products(frame, labels).reset_index(drop=True), labels


def products(name: str, source: str | None = None) -> dict:
    run_dir = _run_dir(name)
    review_dir = run_dir / "ai_review"
    has_review = (review_dir / "final_products.csv").exists()
    outdated = rv.review_outdated(review_dir)
    default = "reviewed" if has_review and not outdated else "all"
    source = source if source in {"reviewed", "all"} and (source == "all" or has_review) else default
    frame, labels = _products(run_dir, source)
    present = list(dict.fromkeys(frame["group"].dropna())) if "group" in frame else []
    groups = [labels[k] for k in sorted(labels) if labels[k] in present]
    groups += [g for g in present if g not in groups]
    report = _read_json(review_dir / "ai_review_report.json") if has_review else None
    return {"source": source, "has_review": has_review, "outdated": outdated, "groups": groups,
            "rows": screens.product_rows(frame), "dataset": f"{name}:{source}:{len(frame)}",
            "collected": _price_stats(run_dir / "final_products.csv")["listings"],
            "removed": (report or {}).get("excluded")}


def export(name: str, body: dict) -> FileResult:
    run_dir = _run_dir(name)
    source = body.get("source") if body.get("source") in {"reviewed", "all"} else "all"
    frame, _ = _products(run_dir, source)
    plan = _read_json(run_dir / jobs.PLAN_FILE, {}) or {}
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ApiError("Nothing to export.")
    meta_info = {"research_question": plan.get("research_question", ""), "run": name,
                 "data": "AI-reviewed (accepted + uncertain)" if source == "reviewed" else "All collected listings"}
    try:
        data, filename, mime, _ = screens.export_bytes(frame, body, meta_info, fx.load_for_run(run_dir))
    except (TypeError, ValueError) as exc:
        raise ApiError(f"Could not build the file: {exc}") from exc
    return FileResult(data, filename, mime)


def raw_file(name: str, file: str) -> FileResult:
    run_dir = _run_dir(name)
    if file not in RAW_FILES or not (run_dir / file).exists():
        raise ApiError("File not found", 404)
    return FileResult((run_dir / file).read_bytes(), f"{name}_{file.replace('/', '_')}", RAW_FILES[file])


def live(name: str) -> dict:
    run_dir = _run_dir(name)
    job = jobs.read_job(run_dir, log_lines=0)
    payload = screens.run_payload(run_dir, job, force_after=FORCE_STOP_AFTER_SECONDS)
    payload["active"] = jobs.is_active(job)
    payload["summary"] = job.get("summary") or {}
    payload["error"] = job.get("error")
    payload["merge_into"] = Path(job["merge_into"]).name if job.get("merge_into") else None
    if not payload["active"]:
        reports = (_read_json(run_dir / "collection_report.json", {}) or {}).get("searches", [])
        if reports:
            try:
                preview = compile_analyst_plan(jobs.check_plan(_read_json(run_dir / jobs.PLAN_FILE, {}))
                                               if job.get("kind") == "check"
                                               else _read_json(run_dir / jobs.PLAN_FILE, {}))[1]
            except (RequestValidationError, KeyError, TypeError, ValueError):
                preview = []
            table = storefront_check_table(reports, preview)
            payload["table"] = table.fillna("").to_dict("records")
            if name.startswith("analyst_") and job.get("kind", "scrape") == "scrape":
                _with_progress(run_dir, payload["table"])
    return payload


_STOP_NOTES = ("Paused during", "Stopped during", "Not started", "Cancelled by user")


def _with_progress(run_dir: Path, table: list[dict]) -> None:
    """For a paused or stopped research: storefronts collected so far (also in resumed parts)
    count as OK, and the ones not reached yet say so instead of showing an error."""
    attempted = retry.attempted_storefronts(run_dir)
    got: dict[str, int] = {}
    tried = set()
    for key, rows in attempted.items():
        if len(key) == 2:
            got[key[1]] = got.get(key[1], 0) + rows
            tried.add(key[1])
    for row in table:
        domain = row["storefront"]
        pause_note = str(row.get("problem") or "").startswith(_STOP_NOTES)
        if got.get(domain, 0) > int(row.get("products_found") or 0):
            row["products_found"] = got[domain]
        if row["products_found"] and (pause_note or row["result"] not in retry.GOOD):
            row["result"], row["problem"] = "OK", ""
        elif not row["products_found"] and domain not in tried and pause_note:
            row["result"], row["problem"] = "Not collected yet", ""


def cancel(name: str) -> dict:
    run_dir = _run_dir(name)
    if not jobs.is_active(jobs.read_job(run_dir, log_lines=0)):
        return {"state": "finished"}
    jobs.request_cancel(run_dir)
    return {"state": "cancelling"}


def force_stop(name: str) -> dict:
    run_dir = _run_dir(name)
    job = jobs.read_job(run_dir, log_lines=0)
    jobs.force_kill(run_dir)
    # the process could not tidy up: rebuild results from the storefronts that finished
    if job.get("kind", "scrape") == "scrape" and any(run_dir.glob("search_*/*/*/checkpoints/*.csv")):
        from price_lens.orchestrator.analyst import recover_run

        try:
            recover_run(run_dir, reason="Stopped by user")
            if job.get("merge_into"):
                retry.finish_merge(run_dir, paused=True)
        except (OSError, ValueError, KeyError) as exc:
            raise ApiError(f"Stopped, but the results could not be rebuilt: {exc}", 500) from exc
    return {"state": "cancelled"}


def pause(name: str) -> dict:
    """Finish the storefront in progress, then stop; the rest can be resumed later."""
    run_dir = _run_dir(name)
    job = jobs.read_job(run_dir, log_lines=0)
    if not jobs.is_active(job):
        return {"state": "finished"}
    if job.get("kind", "scrape") != "scrape":
        raise ApiError("A storefront check cannot be paused; stop it instead.")
    jobs.request_pause(run_dir)
    return {"state": "pausing"}


def resume(name: str) -> dict:
    """Collect every storefront not collected yet, adding the listings to this research."""
    run_dir = _run_dir(name)
    if not name.startswith("analyst_"):
        raise ApiError("Only a research can be resumed.")
    if jobs.find_active_jobs(output_dir()):
        raise ApiError("Another collection is still running. Wait for it or pause it first.", 409)
    retry.recover_unmerged(run_dir)
    left = retry.remaining_storefronts(run_dir)
    if not left:
        raise ApiError("Every storefront of this research has already been collected.")
    plan = retry.build_retry_plan(_read_json(run_dir / jobs.PLAN_FILE, {}), left)
    extra = jobs.start_job(plan, output_dir(), merge_into=run_dir, resume=True)
    jobs._update(extra, remaining_at_start=len(left))
    return {"run": extra.name, "storefronts": len(left)}


def start_retry(name: str, body: dict) -> dict:
    run_dir = _run_dir(name)
    if jobs.find_active_jobs(output_dir()):
        raise ApiError("Another collection is still running. Wait for it or stop it first.", 409)
    wanted = {(int(s["search_id"]), s["domain"]) for s in body.get("storefronts") or []}
    failed = [f for f in retry.failed_storefronts(run_dir) if (f["search_id"], f["domain"]) in wanted]
    if not failed:
        raise ApiError("Pick at least one storefront to retry.")
    plan = retry.build_retry_plan(_read_json(run_dir / jobs.PLAN_FILE, {}), failed)
    retry_dir = jobs.start_job(plan, output_dir(), merge_into=run_dir)
    return {"run": retry_dir.name}


def delete_run(name: str) -> dict:
    run_dir = _run_dir(name)
    try:
        history.delete_run(run_dir, output_dir())
    except ValueError as exc:
        raise ApiError(str(exc), 409) from exc
    except OSError as exc:
        raise ApiError(str(exc), 423) from exc
    return {"deleted": name}


def cleanup() -> dict:
    removed, locked = [], []
    root = output_dir()
    for path in root.iterdir() if root.exists() else []:
        if path.is_dir() and path.name.startswith(history.RUN_PREFIXES) and history.is_empty_failure(path):
            try:
                history.delete_run(path, root)
                removed.append(path.name)
            except (ValueError, OSError):
                locked.append(path.name)
    return {"removed": removed, "locked": locked}


def cleanup_candidates() -> dict:
    root = output_dir()
    return {"runs": [p.name for p in root.iterdir()
                     if p.is_dir() and p.name.startswith(history.RUN_PREFIXES) and history.is_empty_failure(p)]
            if root.exists() else []}


# ---------------------------------------------------------------------------------------
# Storefront health
# ---------------------------------------------------------------------------------------
def storefront_health() -> dict:
    status = storefront_status.load(output_dir())
    rows = [{"storefront": domain, **info} for domain, info in status.items()]
    rows.sort(key=lambda r: (r.get("result") in storefront_status.GOOD, r["storefront"]))
    checks = []
    for path in sorted(output_dir().glob("check_*"), reverse=True)[:10]:
        job = jobs.read_job(path, log_lines=0) if (path / jobs.JOB_FILE).exists() else {}
        table = path / "storefront_check.csv"
        ok = total = 0
        if table.exists():
            frame = pd.read_csv(table, encoding="utf-8-sig")
            total = len(frame)
            ok = int(frame["result"].isin(["OK", "Partial"]).sum()) if "result" in frame else 0
        started = history._started(path)
        checks.append({"id": path.name, "status": job.get("status", "unknown"), "ok": ok, "total": total,
                       "started": started.isoformat() if started else None})
    good = sum(1 for r in rows if r.get("result") in storefront_status.GOOD)
    return {"storefronts": rows, "working": good, "total": len(rows), "checks": checks}


# ---------------------------------------------------------------------------------------
# Relevance review
# ---------------------------------------------------------------------------------------
_claude_jobs: dict[str, dict] = {}
_claude_lock = threading.Lock()


def _review_dir(name: str) -> tuple[Path, Path]:
    run_dir = _run_dir(name)
    return run_dir, run_dir / "ai_review"


def review_state(name: str) -> dict:
    run_dir, review_dir = _review_dir(name)
    plan = _read_json(run_dir / jobs.PLAN_FILE, {}) or {}
    meta_info = _read_json(run_dir / META_FILE, {}) or {}
    prepared = (review_dir / "manifest.json").exists()
    kinds = [s.get("product_type", "") for s in plan.get("searches", [])]
    instruction = assist.default_instruction(kinds, plan.get("research_question", ""))
    state: dict[str, Any] = {
        "prepared": prepared, "api": assist.api_available(),
        "outdated": rv.review_outdated(review_dir),
        "applied": _read_json(review_dir / "ai_review_report.json") if prepared else None,
        "claude": _claude_jobs.get(name),
        "default_instruction": (f"Goal: {meta_info['goal']}\n{instruction}"
                                if meta_info.get("goal") else instruction),
        "batch_size": assist.RECOMMENDED_BATCH_API if assist.api_available() else assist.RECOMMENDED_BATCH_CHAT,
        "listings": _price_stats(run_dir / "detailed_products.csv")["listings"],
    }
    if prepared:
        progress = rv.review_status(review_dir)
        manifest = _read_json(review_dir / "manifest.json", {}) or {}
        state["progress"] = {
            "done": len(progress["completed_batches"]), "total": progress["total_batches"],
            "pending": progress["pending_batches"],
            "remaining": assist.pending_products(review_dir) if progress["pending_batches"] else 0,
        }
        state["instruction"] = manifest.get("instruction") or ""
        table = rv.decision_table(review_dir)
        counts = table["review_status"].value_counts().to_dict()
        state["counts"] = {k: int(counts.get(k, 0)) for k in ("accepted", "uncertain", "excluded", "pending")}
        state["overrides"] = int((table["review_override"] != "").sum())
    return state


def review_prepare(name: str, body: dict) -> dict:
    run_dir, review_dir = _review_dir(name)
    plan = _read_json(run_dir / jobs.PLAN_FILE, {}) or {}
    source = run_dir / "detailed_products.csv"
    if not source.exists():
        raise ApiError("This research has no collected listings to review.")
    brands = tuple(b.strip().lower() for b in str(body.get("brands") or "").split(",") if b.strip())
    try:
        rv.prepare_review_batches(
            source, review_dir, research_question=plan.get("research_question") or "Product research",
            instruction=str(body.get("instruction") or "").strip(),
            batch_size=max(1, min(500, int(body.get("batch_size") or assist.RECOMMENDED_BATCH_CHAT))),
            minimum_keep_confidence=float(body.get("min_confidence") or 0.8), allowed_brands=brands)
    except RequestValidationError as exc:
        raise ApiError(str(exc)) from exc
    return review_state(name)


def review_prompt(name: str, batch: str | None = None) -> dict:
    _, review_dir = _review_dir(name)
    pending = assist.pending_batches(review_dir)
    if not pending:
        raise ApiError("Every batch has been answered.")
    chosen = [batch] if batch in pending else pending
    files = assist.batch_files(review_dir)
    count = sum(len(assist.load_batch(files[n])["products"]) for n in chosen)
    return {"prompt": assist.compact_prompt([files[n] for n in chosen]), "batches": chosen,
            "count": count, "pending": pending}


def review_answer(name: str, body: dict) -> dict:
    _, review_dir = _review_dir(name)
    batches = [b for b in body.get("batches") or [] if b in assist.pending_batches(review_dir)]
    if not batches:
        raise ApiError("These batches were already answered. Copy the prompt again.")
    try:
        result = assist.save_answer(review_dir, batches, str(body.get("text") or ""))
    except RequestValidationError as exc:
        raise ApiError(str(exc)) from exc
    return {**result, "state": review_state(name)}


def review_with_claude(name: str) -> dict:
    _, review_dir = _review_dir(name)
    if not assist.api_available():
        raise ApiError("Set an ANTHROPIC_API_KEY environment variable and restart the app first.")
    with _claude_lock:
        current = _claude_jobs.get(name)
        if current and current.get("running"):
            return current
        state = {"running": True, "log": [], "started": _now(), "error": None, "saved": 0}
        _claude_jobs[name] = state

    def work() -> None:
        try:
            outcome = assist.review_with_claude(review_dir, workers=5,
                                                progress=lambda m: state["log"].append(str(m)))
            state["saved"] = outcome.get("saved", 0)
            if outcome.get("pending"):
                state["error"] = f"{len(outcome['pending'])} batch(es) are still open."
        except Exception as exc:  # noqa: BLE001 - shown on the review screen
            state["error"] = str(exc)
        finally:
            state["running"] = False
            state["finished"] = _now()

    threading.Thread(target=work, daemon=True).start()
    return state


def review_apply(name: str) -> dict:
    _, review_dir = _review_dir(name)
    try:
        rv.apply_review_decisions(review_dir)
    except RequestValidationError as exc:
        raise ApiError(str(exc)) from exc
    return review_state(name)


def review_reset(name: str) -> dict:
    _, review_dir = _review_dir(name)
    if review_dir.exists():
        try:
            history._rmtree_retrying(review_dir)
        except OSError as exc:
            raise ApiError(f"Could not delete the review files (in use by another program?): {exc}", 423) from exc
    _claude_jobs.pop(name, None)
    return review_state(name)


def review_extend(name: str) -> dict:
    run_dir, review_dir = _review_dir(name)
    result = rv.extend_review_batches(review_dir, run_dir / "detailed_products.csv")
    return {**result, "state": review_state(name)}


def review_decisions(name: str) -> dict:
    _, review_dir = _review_dir(name)
    if not (review_dir / "manifest.json").exists():
        return {"rows": []}
    table = rv.decision_table(review_dir)
    rows = []
    for record in table.to_dict("records"):
        rows.append({
            "id": str(record.get("row_id")), "n": screens._clean(record.get("product_name"), False),
            "u": screens._clean(record.get("product_url"), False), "m": screens._clean(record.get("marketplace"), False),
            "v": _clean_number(record.get("price_value")), "cur": screens._clean(record.get("currency_code"), False),
            "keep": None if pd.isna(record.get("ai_keep")) else bool(record.get("ai_keep")),
            "conf": _clean_number(record.get("ai_confidence")),
            "reason": screens._clean(record.get("ai_reason"), False),
            "category": screens._clean(record.get("ai_category"), False),
            "status": record.get("review_status"), "override": record.get("review_override") or "",
        })
    return {"rows": rows}


def review_override(name: str, body: dict) -> dict:
    _, review_dir = _review_dir(name)
    keep = body.get("keep")
    try:
        rv.set_override(review_dir, str(body.get("id")), None if keep is None else bool(keep))
    except RequestValidationError as exc:
        raise ApiError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise ApiError("Prepare the review first.") from exc
    reapplied = False
    if (review_dir / "ai_review_report.json").exists():
        try:
            rv.apply_review_decisions(review_dir)
            reapplied = True
        except RequestValidationError:
            reapplied = False
    return {"reapplied": reapplied}


# ---------------------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------------------
FX_REFRESH_SECONDS = 600
_fx_lock = threading.Lock()
_fx_cache: dict[str, Any] = {}
PRICE_FILES = ("final_products.csv", "detailed_products.csv", "raw_products.csv",
               "ai_review/review_source.csv", "ai_review/ai_classified_products.csv",
               "ai_review/final_products.csv")
EXCEL_COPIES = {"final_products.csv": "final_products.xlsx",
                "ai_review/final_products.csv": "ai_review/final_products.xlsx"}


def _current_rates(refresh: bool = False) -> dict:
    """ECB rates (or the cached copy / built-in table), fetched at most every 10 minutes."""
    with _fx_lock:
        folder = str(output_dir())
        if refresh or not _fx_cache or _fx_cache["dir"] != folder \
                or time.time() - _fx_cache["at"] > FX_REFRESH_SECONDS:
            _fx_cache.update(at=time.time(), dir=folder, info=fx.get_rates(output_dir()), checked=_now())
        return _fx_cache["info"]


def _fx_state(info: dict) -> str:
    if info.get("source") == fx.ECB_SOURCE:
        return "live"
    return "cached" if info.get("date") else "none"


def _rate_source(info: dict, code: str) -> str:
    if code in (info.get("manual") or {}):
        return "yours"
    if not info.get("date") or code in (info.get("static_currencies") or []):
        return "builtin"
    return "ecb"


def exchange_rates(refresh: bool = False) -> dict:
    info = _current_rates(refresh)
    ecb = {c: r for c, r in info["rates"].items()
           if info.get("date") and c not in (info.get("static_currencies") or [])}
    manual = fx.load_manual(output_dir())
    rows = []
    for code in sorted((set(fx.STATIC_TO_USD) | set(ecb) | set(manual["rates"])) - {"USD"}):
        own = manual["rates"].get(code)
        live, builtin = ecb.get(code), fx.STATIC_TO_USD.get(code)
        if own:
            used, source = own["usd_per_unit"], "yours" if own["keep"] else "once"
        elif live:
            used, source = live, "ecb"
        else:
            used, source = builtin, "builtin"
        reference = live or builtin
        rows.append({"code": code, "live": live, "builtin": builtin, "own": own, "used": used,
                     "source": source, "storefront": code in fx.STATIC_TO_USD,
                     "diff_pct": round((own["usd_per_unit"] / reference - 1) * 100, 1)
                     if own and reference else None})
    return {"state": _fx_state(info), "date": info.get("date"), "source": info.get("source"),
            "retrieved": info.get("retrieved"), "checked": _fx_cache.get("checked"), "rows": rows,
            "history": manual["history"][-40:][::-1],
            "running": [p.name for p in jobs.find_active_jobs(output_dir())]}


def set_exchange_rate(code: str, body: dict) -> dict:
    body = body or {}
    try:
        if body.get("per_usd") not in (None, ""):
            per_usd = float(body["per_usd"])
            if not per_usd > 0:
                raise ValueError("The rate must be a positive number.")
            usd_per_unit = 1 / per_usd
        else:
            usd_per_unit = float(body.get("usd_per_unit"))
        fx.set_manual(output_dir(), code, usd_per_unit, keep=bool(body.get("keep", True)),
                      note=str(body.get("note") or ""))
    except (TypeError, ValueError) as exc:
        raise ApiError(str(exc) if "rate" in str(exc) or "currency" in str(exc) else
                       "Type the rate as a number, for example 34.25.") from exc
    except OSError as exc:
        raise ApiError(str(exc), 423) from exc
    return exchange_rates()


def remove_exchange_rate(code: str) -> dict:
    try:
        fx.set_manual(output_dir(), code, None)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    except OSError as exc:
        raise ApiError(str(exc), 423) from exc
    return exchange_rates()


def _run_busy(run_dir: Path) -> bool:
    job = jobs.read_job(run_dir, log_lines=0) if (run_dir / jobs.JOB_FILE).exists() else {}
    if jobs.is_active(job):
        return True
    return any(Path(jobs.read_job(o, log_lines=0).get("merge_into") or "").name == run_dir.name
               for o in jobs.find_active_jobs(output_dir()))


def _run_rates(run_dir: Path) -> dict:
    return fx.load_for_run(run_dir) or {"date": None, "source": fx.STATIC_SOURCE, "retrieved": None,
                                        "rates": dict(fx.STATIC_TO_USD),
                                        "static_currencies": sorted(fx.STATIC_TO_USD)}


def run_rates(name: str) -> dict:
    """The rates a research used, per currency in its listings, next to today's rates."""
    run_dir = _run_dir(name)
    used = _run_rates(run_dir)
    current = fx.with_manual(_current_rates(), output_dir())
    try:
        codes = pd.read_csv(run_dir / "detailed_products.csv", encoding="utf-8-sig",
                            usecols=lambda c: c == "currency_code")["currency_code"]
        counts = codes.dropna().astype(str).str.upper().value_counts()
    except (OSError, ValueError, KeyError, pd.errors.EmptyDataError):
        counts = pd.Series(dtype=int)
    rows = []
    for code, listings in counts.items():
        if code == "USD":
            continue
        was, now = used["rates"].get(code), current["rates"].get(code)
        rows.append({"code": code, "listings": int(listings), "was": was, "was_source": _rate_source(used, code),
                     "was_note": ((used.get("manual") or {}).get(code) or {}).get("note", ""),
                     "now": now, "now_source": _rate_source(current, code),
                     "changed": bool(now and (not was or abs(now / was - 1) > 1e-9))})
    return {"date": used.get("date"), "fx": screens.short_fx(used), "rows": rows,
            "current_date": current.get("date"), "current_state": _fx_state(current),
            "repriced": used.get("repriced") or [], "busy": _run_busy(run_dir)}


def _reprice_csv(path: Path, rates: dict[str, float]) -> None:
    # read as text so product ids, dates and every other column are written back unchanged
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    if frame.empty or not {"currency_code", "price_value"} <= set(frame.columns):
        return
    rate = frame["currency_code"].str.upper().map(rates)
    mask = rate.notna()
    if not mask.any():
        return
    price = pd.to_numeric(frame["price_value"], errors="coerce")
    usd = (price * rate).round(2)
    if "price_usd" not in frame.columns:
        frame["price_usd"] = ""
    frame.loc[mask, "price_usd"] = [("" if v != v else f"{v:.2f}") for v in usd[mask]]
    tmp = path.with_suffix(".reprice.tmp")
    frame.to_csv(tmp, index=False, encoding="utf-8-sig")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    raise ApiError(f"{path.name} is open in another program (Excel?). Close it and try again.", 423)


def reprice_run(name: str, body: dict) -> dict:
    """Recalculate a research's USD prices with today's rates for the chosen currencies."""
    from price_lens.core.export import write_excel

    run_dir = _run_dir(name)
    if _run_busy(run_dir):
        raise ApiError("This research is still collecting. Update its prices when it has finished.", 409)
    state = run_rates(name)
    wanted = {str(c).upper() for c in (body or {}).get("currencies") or []}
    rows = [r for r in state["rows"] if r["code"] in wanted and r["now"]]
    if not rows:
        raise ApiError("Choose at least one currency to update.")
    rates = {r["code"]: r["now"] for r in rows}
    for file in PRICE_FILES:
        if (run_dir / file).exists():
            _reprice_csv(run_dir / file, rates)
    for source, workbook in EXCEL_COPIES.items():
        if (run_dir / workbook).exists() and (run_dir / source).exists():
            try:
                write_excel(pd.read_csv(run_dir / source, encoding="utf-8-sig"), run_dir / workbook)
            except PermissionError as exc:
                raise ApiError(f"{workbook} is open in Excel. Close it and try again.", 423) from exc
    used = _run_rates(run_dir)
    current_manual = fx.load_manual(output_dir())["rates"]
    manual = dict(used.get("manual") or {})
    static = set(used.get("static_currencies") or [])
    for row in rows:
        code = row["code"]
        manual.pop(code, None)
        static.discard(code)
        if row["now_source"] == "yours" and code in current_manual:
            manual[code] = current_manual[code]
        elif row["now_source"] == "builtin" and used.get("date"):
            static.add(code)
    used.update(rates={**used["rates"], **rates}, static_currencies=sorted(static))
    if manual:
        used["manual"] = manual
    else:
        used.pop("manual", None)
    used["repriced"] = [*(used.get("repriced") or []), {"at": _now(), "currencies": {
        r["code"]: {"from": r["was"], "to": r["now"], "source": r["now_source"]} for r in rows}}]
    fx.save_for_run(run_dir, used)
    return {**run_rates(name), "updated": sorted(rates)}


def wait_for(predicate, timeout: float = 5.0) -> bool:
    """Small helper for tests."""
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False
