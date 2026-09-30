"""Remember how each storefront behaved last time (OK, bot check, cookie wall, ...)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .health import storefront_check_table

STATUS_FILE = "storefront_status.json"
GOOD = {"OK", "Partial"}


def load(output_root: Path) -> dict[str, dict]:
    try:
        return json.loads((Path(output_root) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(output_root: Path, reports: list[dict], preview: list[dict], run_name: str) -> dict:
    """Update the status file from a finished run; storefronts the run never reached
    (e.g. after a cancel) keep their previous status."""
    table = storefront_check_table(reports, preview)
    status = load(output_root)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in table.to_dict("records"):
        if not row["products_found"] and not row["problem"]:
            continue  # no evidence either way
        if row["result"] == "Network":
            continue  # our connection dropped; says nothing about the shop
        status[row["storefront"]] = {
            "platform": row["platform"], "result": row["result"],
            "problem": str(row["problem"])[:200], "when": now, "run": run_name,
        }
    path = Path(output_root) / STATUS_FILE
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
    return status


def problems(status: dict[str, dict], domains: list[str]) -> dict[str, dict]:
    return {d: status[d] for d in domains if d in status and status[d].get("result") not in GOOD}
