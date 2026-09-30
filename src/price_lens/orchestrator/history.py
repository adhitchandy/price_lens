"""Browse, reopen and delete past runs in the output folder."""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .jobs import is_active, read_job

RUN_PREFIXES = ("analyst_", "check_", "retry_")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _count_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            return max(0, sum(1 for _ in handle) - 1)
    except OSError:
        return None


def _started(run_dir: Path) -> datetime | None:
    stamp = run_dir.name.split("_", 1)[1][:15] if "_" in run_dir.name else ""
    try:
        return datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def run_status(run_dir: Path) -> str:
    if (run_dir / "job.json").exists():
        return read_job(run_dir, log_lines=0).get("status", "unknown")
    report = _read_json(run_dir / "collection_report.json")
    if not report:
        return "incomplete"
    statuses = [s.get("status") for s in report.get("searches", [])]
    if statuses and all(s == "failed" for s in statuses):
        return "failed"
    if any(s in {"failed", "partial", "cancelled"} for s in statuses):
        return "partial"
    return "completed"


def list_runs(output_root: Path) -> pd.DataFrame:
    root = Path(output_root)
    rows = []
    purge_trash(root)
    if root.exists():
        for run_dir in root.iterdir():
            if not run_dir.is_dir() or not run_dir.name.startswith(RUN_PREFIXES):
                continue
            plan = _read_json(run_dir / "analyst_plan.json") or {}
            review = _read_json(run_dir / "ai_review" / "ai_review_report.json")
            started = _started(run_dir)
            rows.append({
                "_sort": started.isoformat() if started else "",
                "run": run_dir.name,
                "type": ("Storefront check" if run_dir.name.startswith("check_") else
                         "Retry" if run_dir.name.startswith("retry_") else "Scrape"),
                "started_utc": started.strftime("%Y-%m-%d %H:%M") if started else "",
                "status": run_status(run_dir),
                "searches": len(plan.get("searches", [])),
                "listings": _count_rows(run_dir / "final_products.csv"),
                "reviewed": (f"{review['accepted']} accepted / {review['candidates']} kept"
                             if review else ""),
                "goal": str(plan.get("research_question", ""))[:80],
                "path": str(run_dir),
            })
    frame = pd.DataFrame(rows, columns=["_sort", "run", "type", "started_utc", "status", "searches",
                                        "listings", "reviewed", "goal", "path"])
    frame = frame.sort_values(["_sort", "run"], ascending=False)
    return frame.drop(columns="_sort").reset_index(drop=True)


def recover_if_needed(run_dir: Path) -> dict | None:
    """Rebuild results for a run that stopped unexpectedly (crash, sleep, shutdown)."""
    run_dir = Path(run_dir)
    if not run_dir.name.startswith("analyst_") or not (run_dir / "analyst_plan.json").exists():
        return None
    job = read_job(run_dir, log_lines=0) if (run_dir / "job.json").exists() else {}
    if is_active(job):
        return None
    crashed = job.get("status") == "crashed"
    missing_results = not (run_dir / "final_products.csv").exists()
    if not (crashed or missing_results) or not any(run_dir.glob("search_*/*/*/checkpoints/*.csv")):
        return None
    from .analyst import recover_run

    result = recover_run(run_dir)
    if job:
        from .jobs import _now, _update

        _update(run_dir, status="recovered", finished_at=job.get("finished_at") or _now(),
                summary={"listings": result["listings"], "recovered": True})
    return result


def load_run(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    try:
        recovered = recover_if_needed(run_dir)
    except (OSError, ValueError, KeyError):
        recovered = None
    final_path = run_dir / "final_products.csv"
    final = pd.read_csv(final_path, encoding="utf-8-sig") if final_path.exists() else pd.DataFrame()
    report = _read_json(run_dir / "collection_report.json") or {"searches": []}
    job = read_job(run_dir, log_lines=300) if (run_dir / "job.json").exists() else {}
    log = job.get("log", "")
    return {"run_dir": str(run_dir), "final": final, "reports": report.get("searches", []),
            "recovered": recovered,
            "log": log.splitlines() if log else [], "status": run_status(run_dir),
            "kind": job.get("kind", "check" if run_dir.name.startswith("check_") else "scrape")}


def is_empty_failure(run_dir: Path) -> bool:
    status = run_status(run_dir)
    if any(Path(run_dir).glob("search_*/*/*/checkpoints/*.csv")) and status == "crashed":
        return False  # recoverable: open it first
    return status in {"failed", "incomplete", "crashed", "cancelled", "missing"} and not _count_rows(
        run_dir / "final_products.csv")


def delete_run(run_dir: Path, output_root: Path) -> None:
    run_dir, root = Path(run_dir).resolve(), Path(output_root).resolve()
    if run_dir.parent != root or not run_dir.name.startswith(RUN_PREFIXES):
        raise ValueError(f"Refusing to delete a folder outside the output directory: {run_dir}")
    if (run_dir / "job.json").exists() and is_active(read_job(run_dir, log_lines=0)):
        raise ValueError("This run is still in progress. Cancel it first.")
    try:
        _rmtree_retrying(run_dir)
        return
    except OSError:
        pass
    # OneDrive / Explorer / antivirus can hold a folder open for a while. Move it out of
    # the way so it disappears from the history now; purge_trash() retries later.
    trash = root / TRASH_DIR
    trash.mkdir(exist_ok=True)
    target = trash / f"{run_dir.name}_{int(time.time())}"
    try:
        os.replace(run_dir, target)
    except OSError as exc:
        raise OSError(
            f"Windows would not delete {run_dir.name} because another program is using it "
            "(often OneDrive syncing, an open Explorer window, or an open CSV/Excel file). "
            "Close it, wait a moment and try again."
        ) from exc
    try:
        _rmtree_retrying(target, attempts=2)
    except OSError:
        pass  # left in output/.trash; purge_trash() removes it on a later visit


TRASH_DIR = ".trash"


def _rmtree_retrying(path: Path, attempts: int = 8) -> None:
    """rmtree that clears read-only flags and retries files/folders locked for a moment."""

    def retry(func, target, _exc):
        for attempt in range(attempts):
            try:  # clear a read-only flag without removing other permissions
                os.chmod(target, os.stat(target).st_mode | stat.S_IWRITE)
            except OSError:
                pass
            try:
                func(target)
                return
            except FileNotFoundError:
                return
            except OSError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.25 * (attempt + 1))

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:  # pragma: no cover - Python 3.10/3.11
        shutil.rmtree(path, onerror=lambda func, target, info: retry(func, target, info[1]))


def purge_trash(output_root: Path) -> None:
    """Quietly finish deleting runs that were locked when the user deleted them."""
    trash = Path(output_root) / TRASH_DIR
    if not trash.exists():
        return
    for leftover in trash.iterdir():
        try:
            _rmtree_retrying(leftover, attempts=1) if leftover.is_dir() else leftover.unlink()
        except OSError:
            pass
