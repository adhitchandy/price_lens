"""Custom screens built with Streamlit components v2 (no build step, no iframe).

The markup, styles and scripts live in ``apps/pi_ui/web``; this module registers them once
and turns run data into the JSON the screens draw.
"""
from __future__ import annotations

import base64
import functools
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from price_lens.orchestrator import screens

WEB = Path(__file__).with_name("web")

XLSX_MIME = screens.XLSX_MIME


@functools.lru_cache(maxsize=None)
def _asset(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def _register(name: str, css_files: tuple[str, ...], js_file: str):
    # Registered on every run: cheap, and each Streamlit runtime (also the test harness)
    # has its own registry. Re-registering an identical definition is silent.
    return st.components.v2.component(
        f"pi_{name}",
        html=f"<div class='pi pi-{name}'></div>",
        css="\n".join(_asset(f) for f in css_files),
        js=_asset(js_file),
    )


def results_component():
    return _register("results", ("base.css", "results.css"), "results.js")


def run_component():
    return _register("run", ("base.css", "run.css"), "run.js")


def copy_component():
    return _register("copy", ("copy.css",), "copy.js")


# ---------------------------------------------------------------------------------------
# Data (shared with the web app: price_lens.orchestrator.screens)
# ---------------------------------------------------------------------------------------
ROW_FIELDS = screens.ROW_FIELDS
product_rows = screens.product_rows
short_fx = screens.short_fx
run_payload = screens.run_payload


def export_file(products: pd.DataFrame, request: dict, meta: dict, fx_info: dict | None) -> dict:
    """The requested download, base64-encoded for the Results screen."""
    data, name, mime, rows = screens.export_bytes(products, request, meta, fx_info)
    return {"nonce": uuid.uuid4().hex, "name": name, "mime": mime,
            "b64": base64.b64encode(data).decode("ascii"), "rows": rows}
