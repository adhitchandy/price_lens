"""Data for the app screens (both the web app and the Streamlit app): result rows, exports
and the live-run status. Pure functions of the run folder, easy to test."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

# Short keys keep the payload small (a run can have thousands of listings).
ROW_FIELDS = {
    "n": "product_name", "u": "product_url", "b": "brand", "g": "group", "c": "country",
    "p": "platform", "m": "marketplace", "a": "audience", "v": "price_value",
    "cur": "currency_code", "usd": "price_usd", "conf": "relevance_confidence_pct",
    "st": "review_status",
}
NUMERIC = {"v", "usd", "conf"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------------------
def _clean(value: Any, numeric: bool) -> Any:
    if value is None:
        return None
    if numeric:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(number) or math.isinf(number) else round(number, 4)
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def product_rows(products: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows for the Results screen; ``i`` is the row position in ``products``."""
    rows = []
    columns = {short: column for short, column in ROW_FIELDS.items() if column in products.columns}
    records = products.to_dict("records")
    for position, record in enumerate(records):
        row: dict[str, Any] = {"i": position}
        for short in ROW_FIELDS:
            column = columns.get(short)
            row[short] = _clean(record.get(column), short in NUMERIC) if column else None
        rows.append(row)
    return rows


def short_fx(fx_info: dict | None) -> str:
    if not fx_info:
        return "USD at static rates"
    own = f" + your rates for {', '.join(sorted(fx_info['manual']))}" if fx_info.get("manual") else ""
    if not fx_info.get("date"):
        return f"USD at static rates{own}"
    try:
        stamp = pd.Timestamp(fx_info["date"])
        day = f"{stamp.day} {stamp.strftime('%b %Y')}"  # no %-d: not supported on Windows
    except ValueError:
        day = str(fx_info["date"])
    return f"USD at ECB rates of {day}{own}"


def export_bytes(products: pd.DataFrame, request: dict, meta: dict,
                 fx_info: dict | None) -> tuple[bytes, str, str, int]:
    """Build the file a Results screen asked for, from the rows it had on screen.
    Returns (data, file name, mime type, number of rows)."""
    from price_lens.orchestrator import price_report

    picked = sorted({int(i) for i in request.get("rows", []) if 0 <= int(i) < len(products)})
    view = products.iloc[picked]
    run = meta.get("run", "run")
    meta = {**meta, "filters": str(request.get("filters") or "none"),
            "group": str(request.get("group") or meta.get("group", ""))}
    if request.get("kind") == "csv":
        data = (price_report.product_view(view, export=True).rename(columns=price_report.COLUMN_LABELS)
                .to_csv(index=False).encode("utf-8-sig"))
        name, mime = f"products_{run}.csv", "text/csv"
    else:
        data = price_report.price_report_xlsx(price_report.price_summary(view), view, meta, fx_info)
        name, mime = f"price_report_{run}.xlsx", XLSX_MIME
    return data, name, mime, len(view)


# ---------------------------------------------------------------------------------------
# Live run
# ---------------------------------------------------------------------------------------
LOG_TAIL_BYTES = 400_000
_WAITING = ("connection lost", "still down", "still offline", "waiting for connection",
            "waiting before this storefront")


def _log_tone(line: str) -> str:
    low = line.lower()
    if line.lstrip().startswith("#####") or line.lstrip().startswith("==="):
        return "head"
    if any(w in low for w in ("traceback", "failed", "bot check", "blocked", "error", "captcha")):
        return "bad"
    if any(w in low for w in ("partial", "⚠", "connection", "offline", "timeout", "stopped", "retry")):
        return "warn"
    if any(w in low for w in ("cookie", "enriching", "detail ", "scroll")):
        return "dim"
    return "plain"


def _read_tail(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


_rows_cache: dict[tuple[str, float], int] = {}


def _csv_rows(path: Path) -> int:
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return 0
    if key not in _rows_cache:
        try:
            _rows_cache[key] = len(pd.read_csv(path, encoding="utf-8-sig", usecols=[0]))
        except (OSError, ValueError, pd.errors.EmptyDataError):
            _rows_cache[key] = 0
    return _rows_cache[key]


def _checkpoints(run_dir: Path) -> dict[tuple[int, str], Path]:
    found = {}
    for path in run_dir.glob("search_*/*/*/checkpoints/*.csv"):
        try:
            found[(int(path.parts[-5].split("_", 1)[1]), path.stem)] = path
        except (IndexError, ValueError):
            continue
    return found


_preview_cache: dict[tuple[str, float, str], tuple[list[dict], int | None]] = {}


def _plan_info(run_dir: Path, kind: str) -> tuple[list[dict], int | None]:
    """Planned storefronts of a run in plan order (search_id, domain, country, platform) and
    the estimated run time in minutes. Cached per plan file."""
    from price_lens.orchestrator import jobs, planning
    from price_lens.orchestrator.analyst import compile_analyst_plan

    plan_path = run_dir / jobs.PLAN_FILE
    try:
        cache_key = (str(plan_path), plan_path.stat().st_mtime, kind)
    except OSError:
        return [], None
    if cache_key not in _preview_cache:
        import json

        estimate = None
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if kind == "check":
                plan = jobs.check_plan(plan)
            preview = compile_analyst_plan(plan)[1]
            estimate = planning.estimate_minutes(preview, plan.get("execution") or {})
        except Exception:  # noqa: BLE001 - the monitor must never fail because of the plan
            preview = []
        seen, stores = set(), []
        for row in preview:
            ident = (int(row["search_id"]), row["domain"])
            if ident not in seen:
                seen.add(ident)
                stores.append({"search_id": ident[0], "domain": row["domain"],
                               "country": row.get("country") or "", "platform": row.get("platform") or "",
                               "product": row.get("category") or ""})
        _preview_cache[cache_key] = (stores, estimate)
    return _preview_cache[cache_key]


def run_payload(run_dir: Path, job: dict, *, force_after: int = 20) -> dict[str, Any]:
    """What the live-run screen shows: progress, one line per storefront, the log tail."""
    from datetime import datetime

    from price_lens.orchestrator import jobs

    run_dir = Path(run_dir)
    kind = job.get("kind", "scrape")
    state = job.get("status", "unknown")
    total_searches = max(1, int(job.get("searches_total") or 1))
    done_searches = min(total_searches, int(job.get("searches_done") or 0))
    current = min(total_searches, done_searches + 1)

    text = _read_tail(run_dir / jobs.LOG_FILE)
    lines = [line for line in text.splitlines() if line.strip()]
    marker = f"##### Search {current}/"
    start = max((i for i, line in enumerate(lines) if line.lstrip().startswith(marker)), default=None)
    current_lines = lines[start:] if start is not None else []

    stores, estimate = _plan_info(run_dir, kind)
    saved = _checkpoints(run_dir)
    rows, listings, finished = [], 0, 0
    for store in stores:
        sid, domain = store["search_id"], store["domain"]
        checkpoint = saved.get((sid, domain))
        count = _csv_rows(checkpoint) if checkpoint else None
        mentions = [line for line in current_lines if domain in line] if sid == current else []
        if checkpoint is not None:
            status = ("Done", "ok") if count else ("No products", "warn")
            listings += count or 0
            finished += 1
        elif sid < current:
            status = ("No result", "bad")
            finished += 1
        elif mentions:
            last = mentions[-1].lower()
            status = (("Waiting for network", "warn") if any(w in last for w in _WAITING)
                      and "is back" not in last else ("Collecting", "info"))
        else:
            status = ("Queued", "idle")
        rows.append({"country": store["country"], "store": domain, "platform": store["platform"],
                     "search": sid, "product": store.get("product", ""),
                     "count": count, "status": status[0], "tone": status[1]})
    # a storefront mentioned earlier in this search but not current any more has finished
    collecting = [r for r in rows if r["status"] in {"Collecting", "Waiting for network"}]
    if len(collecting) > 1:
        latest = max(collecting, key=lambda r: max(
            (i for i, line in enumerate(current_lines) if r["store"] in line), default=-1))
        for r in collecting:
            if r is not latest:
                r["status"], r["tone"] = "No result", "bad"
                finished += 1

    started = job.get("started_at") or job.get("created_at")
    elapsed = jobs._age_seconds(started) if started else 0
    try:
        started_local = datetime.fromisoformat(started).astimezone().strftime("%H:%M") if started else ""
    except ValueError:
        started_local = ""
    progress = round(100 * finished / len(rows)) if rows else round(100 * done_searches / total_searches)
    if estimate is None:
        left = ""
    else:
        remaining = estimate - elapsed / 60
        left = f"~{max(1, round(remaining))} min" if remaining > 1 else "almost done"
    waited = jobs._age_seconds(job.get("cancel_requested_at")) if state == "cancelling" else 0
    title_line = next((line for line in reversed(lines) if line.lstrip().startswith("#####")), "")
    current_term = title_line.split(":", 1)[1].strip(" #") if ":" in title_line else ""
    return {
        "run": run_dir.name,
        "label": ("Resuming the collection" if job.get("resume") else
                  "Retrying failed storefronts" if job.get("merge_into") else
                  "Testing storefronts" if kind == "check" else "Collecting listings"),
        "state": state,
        "kind": kind,
        "can_pause": kind == "scrape" and state == "running",
        "search": {"current": current, "total": total_searches, "term": current_term},
        "stores": rows,
        "stores_done": finished,
        "listings": listings,
        "progress": max(0, min(100, progress)),
        "time_left": left,
        "started": started_local,
        "log": [{"m": line[:400], "k": _log_tone(line)} for line in lines[-14:]],
        "can_force": state == "cancelling" and waited > force_after,
        "stamp": job.get("heartbeat"),
    }
