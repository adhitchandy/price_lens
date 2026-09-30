"""③ Results: price summary, chart, filters, exports, retries."""
from __future__ import annotations

import functools
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from price_lens.agent.review import review_outdated
from price_lens.core import fx
from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator import (
    history,
    jobs,
    price_report,
    retry,
)

from . import components
from .common import (
    _report_rows,
    output_dir,
)


def _load_products(out_path: Path, result: dict, source: str, labels: dict) -> pd.DataFrame:
    reviewed_csv = out_path / "ai_review" / "final_products.csv"
    frame = (pd.read_csv(reviewed_csv, encoding="utf-8-sig")
             if source == "reviewed" and reviewed_csv.exists() else result["final"])
    return price_report.prepare_products(frame, labels).reset_index(drop=True)


def _on_export(key: str, out_path: Path, result: dict, labels: dict, meta: dict,
               fx_info: dict | None) -> None:
    """Runs before the rerun that follows a download click; the file goes back to the screen."""
    state = st.session_state.get(key) or {}
    request = state.get("export")
    if not request:
        return
    source = state.get("source") or "all"
    try:
        products = _load_products(out_path, result, source, labels)
        data_label = ("AI-reviewed (accepted + uncertain)" if source == "reviewed"
                      else "All collected listings")
        st.session_state[f"{key}__export"] = components.export_file(
            products, request, {**meta, "data": data_label}, fx_info)
    except Exception as exc:  # noqa: BLE001 - show any problem on the screen
        st.session_state[f"{key}__export"] = {"nonce": uuid.uuid4().hex,
                                              "error": f"Could not build the file: {exc}"}


def render(result: dict | None, busy: bool):
    if not result:
        st.info("Run the scraper, or open a past run from History, to see prices here.")
    elif result.get("kind") == "check":
        st.info("This is a storefront check. Its table is on the ② Check & run tab.")
    else:
        out_path = Path(result["run_dir"])
        run_plan = history._read_json(out_path / "analyst_plan.json") or {}
        has_review = (out_path / "ai_review" / "final_products.csv").exists()
        outdated = review_outdated(out_path / "ai_review")
        labels = price_report.group_labels(run_plan)
        fx_info = fx.load_for_run(out_path)
        key = f"pi_results_{out_path.name}_{int(bool(outdated))}"
        default_source = "reviewed" if has_review and not outdated else "all"
        state = st.session_state.get(key) or {}
        source = (state.get("source") or default_source) if has_review else "all"
        products = _load_products(out_path, result, source, labels)
        meta = {"research_question": run_plan.get("research_question", ""), "run": out_path.name}

        present = list(dict.fromkeys(products["group"].dropna())) if "group" in products else []
        groups = [labels[k] for k in sorted(labels) if labels[k] in present]
        groups += [g for g in present if g not in groups]
        payload = {
            "run": out_path.name,
            "title": run_plan.get("research_question") or out_path.name,
            "status": result.get("status", ""),
            "source": source,
            "has_review": has_review,
            "outdated": outdated,
            "fx": components.short_fx(fx_info),
            "fx_title": fx.describe(fx_info),
            "groups": groups,
            "dataset": f"{out_path.name}:{source}:{len(products)}",
            "rows": components.product_rows(products),
            "export": st.session_state.pop(f"{key}__export", None),
            "note": "Check the search status and errors below.",
        }
        components.results_component()(
            key=key, data=payload, default={"source": default_source}, height="content",
            on_source_change=lambda: None,
            on_export_change=functools.partial(_on_export, key, out_path, result, labels, meta, fx_info),
        )

        # ---- storefronts that delivered nothing: offer a retry --------------------------
        try:
            failed_sf = retry.failed_storefronts(out_path) if out_path.name.startswith("analyst_") else []
        except (OSError, ValueError, KeyError, RequestValidationError):
            failed_sf = []
        if failed_sf:
            with st.expander(f"⚠️ {len(failed_sf)} storefront(s) returned no products — retry them",
                             expanded=False):
                st.dataframe(pd.DataFrame(failed_sf).rename(columns={
                    "search_id": "Search", "platform": "Platform", "domain": "Storefront",
                    "country": "Country", "result": "Result", "problem": "Details"}),
                    hide_index=True, width="stretch")
                retry_labels = {f"{f['domain']} (search {f['search_id']})": f for f in failed_sf}
                default = [k for k, f in retry_labels.items() if f["result"] != "Bot check"]
                picked_retry = st.multiselect(
                    "Storefronts to retry", list(retry_labels), default=default,
                    key=f"retry_pick_{out_path.name}",
                    help="Bot checks usually persist for a while, so they are not pre-selected.")
                if (out_path / "ai_review" / "manifest.json").exists():
                    st.caption("Note: this run has a relevance review. After the retry it is marked "
                               "out of date, and you can add just the new listings to it.")
                if st.button("🔁 Retry selected storefronts", disabled=busy or not picked_retry,
                             key=f"retry_go_{out_path.name}"):
                    retry_plan = retry.build_retry_plan(run_plan, [retry_labels[k] for k in picked_retry])
                    try:
                        run_dir = jobs.start_job(retry_plan, output_dir(), merge_into=out_path)
                        st.session_state.active_job = str(run_dir)
                        st.rerun()
                    except (OSError, ValueError) as exc:
                        st.error(f"Could not start the retry: {exc}")

        with st.expander("Search status, errors and raw files"):
            st.dataframe(pd.DataFrame(_report_rows(result["reports"])), hide_index=True, width="stretch")
            raw = [(name, out_path / name) for name in
                   ("final_products.csv", "detailed_products.csv", "raw_products.csv")
                   if (out_path / name).exists()]
            if raw:
                cols = st.columns(len(raw))
                for col, (name, path) in zip(cols, raw):
                    col.download_button(name, path.read_bytes(), name, "text/csv",
                                        key=f"raw_{out_path.name}_{name}", width="stretch")
            if result.get("log"):
                st.code("\n".join(result["log"][-300:]), language=None)

