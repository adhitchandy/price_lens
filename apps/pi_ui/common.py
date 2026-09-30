"""Shared helpers and constants for the Streamlit screens."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import streamlit as st

from price_lens.orchestrator import history

ROOT = Path(__file__).resolve().parents[2]
def output_dir() -> Path:
    """Where runs are stored (PI_OUTPUT_DIR overrides, e.g. for tests); read on every call."""
    return Path(os.environ.get("PI_OUTPUT_DIR") or ROOT / "output")
AUDIENCES = ["men", "women", "kids"]  # display order
FORCE_STOP_AFTER_SECONDS = 20


def _new_search(number: int) -> dict:
    return {
        "id": f"search_{number}",
        "product_type": "",
        "query": {
            "default": "",
            "translations": {},
            "filters": {"include": [], "exclude": [], "min_price": None, "max_price": None},
        },
        "targets": [{"platform": "mediamarkt", "countries": ["Germany"], "platform_options": {}}],
    }


def _default_plan() -> dict:
    first = _new_search(1)
    first["product_type"] = "Smartphones"
    first["query"]["default"] = "Smartphone"
    first["query"]["filters"]["exclude"] = ["case", "cover", "hülle"]
    return {
        "schema_version": "analyst-v2",
        "research_question": "Ad-hoc Price Lens Research",
        "execution": {
            "products_per_storefront": 100,
            "pages": 1,
            "retries": 2,
            "headless": False,
            "delay_seconds": [2.5, 4.5],
            "enrich_details": False,
            "max_detail_products": 30,
        },
        "searches": [first],
    }


def _bump() -> None:
    """Change every widget key so widgets re-read their values from the plan."""
    st.session_state.rev += 1


def _split_words(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def copy_button(text: str, label: str, done_hint: str = "") -> None:
    """A one-click 'copy to clipboard' button (Streamlit has none built in)."""
    from . import components

    components.copy_component()(
        key=f"pi_copy_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]}",
        data={"text": text, "label": label, "hint": done_hint or "Copied."}, height="content")


def _open_run(run_dir: Path | str) -> None:
    st.session_state.result = history.load_run(Path(run_dir))



def _report_rows(reports: list[dict]) -> list[dict]:
    rows = []
    for rep in reports:
        inner = rep.get("report") or {}
        platform_errors = [
            f"{name}: {info.get('error')}"
            for name, info in (inner.get("platform_reports") or {}).items()
            if info.get("error")
        ]
        for name, info in (inner.get("platform_reports") or {}).items():
            for failure in info.get("failures") or []:
                platform_errors.append(f"{name} {failure.get('marketplace', '')}: {failure.get('error', '')}")
        rows.append({
            "search_id": rep.get("search_id"),
            "status": rep.get("status"),
            "raw_rows": inner.get("raw_rows"),
            "cleaned_rows": inner.get("cleaned_rows"),
            "errors": "; ".join(filter(None, [rep.get("error"), *platform_errors]))[:500],
        })
    return rows

