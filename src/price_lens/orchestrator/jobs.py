"""Background runs: scraping happens in a separate process so the UI can refresh,
reconnect, and cancel.

Each job lives in its own run folder::

    job.json       status, pid, heartbeat, progress, summary
    log.txt        full live log
    cancel.flag    present once the user asked to stop

Start a worker with ``python -m price_lens.orchestrator.jobs <run_dir>``.
"""
from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from price_lens.core.export import create_run_directory, write_json

JOB_FILE = "job.json"
LOG_FILE = "log.txt"
CANCEL_FILE = "cancel.flag"
PAUSE_FILE = "pause.flag"
PLAN_FILE = "analyst_plan.json"
HEARTBEAT_SECONDS = 5
STALE_AFTER_SECONDS = 60
ACTIVE_STATES = {"queued", "running", "cancelling", "pausing"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_seconds(stamp: str | None) -> float:
    if not stamp:
        return float("inf")
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        return float("inf")


_lock = threading.Lock()


def _update(run_dir: Path, **changes: Any) -> dict:
    with _lock:
        path = run_dir / JOB_FILE
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            job = {}
        job.update(changes)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
        for attempt in range(20):  # Windows refuses replace while a reader has it open
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        return job


# ---------------------------------------------------------------------------
# UI side
# ---------------------------------------------------------------------------
def start_job(plan: dict, output_root: Path, kind: str = "scrape",
              merge_into: Path | None = None, resume: bool = False) -> Path:
    """Create the run folder and launch the worker process. Returns the run folder.

    ``merge_into``: a previous run; this job's results are added to it when finished
    (used by "Retry failed storefronts")."""
    if kind not in {"scrape", "check"}:
        raise ValueError(f"Unknown job kind: {kind}")
    prefix = "retry" if merge_into else ("analyst" if kind == "scrape" else "check")
    run_dir = create_run_directory(Path(output_root), prefix)
    write_json(run_dir / PLAN_FILE, plan)
    if merge_into and (Path(merge_into) / "fx_rates.json").exists():
        # a retry converts prices with the rates of the research it is added to
        shutil.copyfile(Path(merge_into) / "fx_rates.json", run_dir / "fx_rates.json")
    (run_dir / LOG_FILE).write_text("", encoding="utf-8")
    _update(run_dir, kind=kind, status="queued", created_at=_now(), heartbeat=_now(),
            searches_total=len(plan.get("searches", [])), searches_done=0,
            merge_into=str(merge_into) if merge_into else None, resume=bool(resume))

    src_dir = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(src_dir), env.get("PYTHONPATH")]))
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    with open(run_dir / "worker_output.txt", "wb") as worker_out:
        process = subprocess.Popen(
            [sys.executable, "-m", "price_lens.orchestrator.jobs", str(run_dir)],
            stdout=worker_out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env=env, cwd=str(Path(output_root).resolve().parent), **kwargs,
        )
    _update(run_dir, pid=process.pid)
    return run_dir


def read_job(run_dir: Path, log_lines: int = 60) -> dict:
    """Current job state. A job whose heartbeat stopped is reported as 'crashed'."""
    run_dir = Path(run_dir)
    job = None
    for attempt in range(5):
        try:
            job = json.loads((run_dir / JOB_FILE).read_text(encoding="utf-8"))
            break
        except FileNotFoundError:
            return {"status": "missing", "log": "", "run_dir": str(run_dir)}
        except (OSError, ValueError):
            time.sleep(0.05 * (attempt + 1))
    if job is None:
        return {"status": "unknown", "log": "", "run_dir": str(run_dir)}
    if (job.get("status") in ACTIVE_STATES and _age_seconds(job.get("heartbeat")) > STALE_AFTER_SECONDS
            and not pid_alive(job.get("pid"))):  # a sleeping computer is not a crash
        job["status"] = "crashed"
        job.setdefault("error", "The background process stopped responding (closed or crashed).")
    try:
        lines = (run_dir / LOG_FILE).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    job["log"] = "\n".join(lines[-log_lines:])
    job["run_dir"] = str(run_dir)
    return job


def pid_alive(pid: Any) -> bool:
    """True if the worker process still exists (e.g. the computer was only asleep)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) would terminate the process on Windows
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_active(job: dict) -> bool:
    return job.get("status") in ACTIVE_STATES


def request_cancel(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    (run_dir / CANCEL_FILE).write_text(_now(), encoding="utf-8")
    _update(run_dir, status="cancelling", cancel_requested_at=_now())


def request_pause(run_dir: Path) -> None:
    """Stop after the storefront in progress; everything collected so far is kept."""
    run_dir = Path(run_dir)
    (run_dir / PAUSE_FILE).write_text(_now(), encoding="utf-8")
    _update(run_dir, status="pausing", pause_requested_at=_now())


def force_kill(run_dir: Path) -> None:
    """Kill the worker and its browser processes (used if it ignores the cancel flag)."""
    run_dir = Path(run_dir)
    job = read_job(run_dir)
    pid = job.get("pid")
    if pid:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, check=False)
            else:
                os.killpg(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass
    _update(run_dir, status="cancelled", finished_at=_now(),
            error="Stopped by user (process terminated).")


def find_active_jobs(output_root: Path) -> list[Path]:
    root = Path(output_root)
    if not root.exists():
        return []
    active = []
    for job_file in sorted(root.glob(f"*/{JOB_FILE}"), reverse=True):
        if is_active(read_job(job_file.parent, log_lines=0)):
            active.append(job_file.parent)
    return active


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------
def check_plan(plan: dict) -> dict:
    """One quick page per storefront: one search per platform, all its countries merged."""
    execution = dict(plan.get("execution") or plan.get("settings") or {})
    execution.update(pages=1, retries=min(int(execution.get("retries", 1)), 1),
                     enrich_details=False)
    execution.pop("products_per_storefront", None)
    from .analyst import upgrade_to_v2

    v2 = upgrade_to_v2(plan)
    by_platform: dict[str, dict] = {}
    for search in v2.get("searches", []):
        for target in search.get("targets", []):
            platform = target.get("platform")
            if platform not in by_platform:
                probe = json.loads(json.dumps(search))
                probe["id"] = f"check_{platform}"
                probe["split_audiences"] = False  # one page per storefront is enough
                probe["targets"] = [json.loads(json.dumps(target))]
                probe["query"]["filters"] = {"include": [], "exclude": [],
                                             "min_price": None, "max_price": None}
                by_platform[platform] = probe
            else:
                existing = by_platform[platform]["targets"][0]
                merged = list(dict.fromkeys([*existing.get("countries", []),
                                             *target.get("countries", [])]))
                existing["countries"] = ["all"] if "all" in merged else merged
    return {"schema_version": "analyst-v2",
            "research_question": "Storefront check",
            "execution": execution,
            "searches": list(by_platform.values())}


def run_worker(run_dir: Path) -> int:
    from . import localization
    from .analyst import RunCancelled, compile_analyst_plan, run_analyst_plan
    from .health import storefront_check_table

    run_dir = Path(run_dir)
    job = read_job(run_dir, log_lines=0)
    plan = json.loads((run_dir / PLAN_FILE).read_text(encoding="utf-8"))
    kind = job.get("kind", "scrape")
    if kind == "check":
        plan = check_plan(plan)
    log_path = run_dir / LOG_FILE
    cancel_path = run_dir / CANCEL_FILE
    pause_path = run_dir / PAUSE_FILE
    localization.PAUSE_CHECK = pause_path.exists
    stop_heartbeat = threading.Event()

    def heartbeat() -> None:
        while not stop_heartbeat.wait(HEARTBEAT_SECONDS):
            _update(run_dir, heartbeat=_now())

    def log(message: object) -> None:
        text = str(message)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
        if text.lstrip().startswith("##### Search "):
            try:
                done = int(text.split("Search ", 1)[1].split("/", 1)[0]) - 1
                _update(run_dir, searches_done=done, current=text.strip("# \n"))
            except (IndexError, ValueError):
                pass
        if cancel_path.exists():
            raise RunCancelled()

    _update(run_dir, status="running", started_at=_now(), heartbeat=_now(), pid=os.getpid(),
            searches_total=len(plan.get("searches", [])))
    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        _, final, reports = run_analyst_plan(plan, log=log, root=run_dir)
        statuses = [r.get("status") for r in reports]
        if "paused" in statuses:
            status = "paused"
        elif "cancelled" in statuses or cancel_path.exists():
            status = "cancelled"
        elif statuses and all(s == "failed" for s in statuses):
            status = "failed"
        elif any(s in {"failed", "partial"} for s in statuses):
            status = "partial"
        else:
            status = "completed"
        summary: dict[str, Any] = {"listings": len(final),
                                   "searches": {str(r["search_id"]): r.get("status") for r in reports}}
        preview = compile_analyst_plan(plan)[1]
        try:
            from .storefront_status import record

            record(run_dir.parent, reports, preview, run_dir.name)
        except Exception:  # noqa: BLE001 - status memory must never fail a run
            pass
        if job.get("merge_into"):
            from .retry import finish_merge

            merged = finish_merge(run_dir, paused=status == "paused")
            summary["merged_into"] = Path(job["merge_into"]).name
            summary["added_listings"] = merged["added"]
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\nAdded {merged['added']} listing(s) to {Path(job['merge_into']).name}\n")
        if kind == "check":
            table = storefront_check_table(reports, preview)
            table.to_csv(run_dir / "storefront_check.csv", index=False, encoding="utf-8-sig")
            summary["storefronts_ok"] = int((table["result"] == "OK").sum()) if not table.empty else 0
            summary["storefronts_total"] = len(table)
        _update(run_dir, status=status, finished_at=_now(), searches_done=len(reports),
                summary=summary, heartbeat=_now())
        pause_path.unlink(missing_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            if status == "paused":
                handle.write("\nPaused. Everything collected so far is saved; resume any time.\n")
            handle.write(f"\n=== Finished: {status} — {len(final)} listing(s) ===\n")
        return 0
    except RunCancelled:
        _update(run_dir, status="cancelled", finished_at=_now(), heartbeat=_now())
        return 0
    except BaseException as exc:  # noqa: BLE001 - record every crash for the UI
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc())
        _update(run_dir, status="failed", finished_at=_now(), heartbeat=_now(),
                error=f"{exc.__class__.__name__}: {exc}")
        return 1
    finally:
        stop_heartbeat.set()


if __name__ == "__main__":
    sys.exit(run_worker(Path(sys.argv[1])))
