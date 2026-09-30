"""Unified Price Lens workspace.

Run with:  python -m streamlit run apps/unified_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # works even without `pip install -e .`
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:  # for the apps.pi_ui screen modules
    sys.path.insert(0, str(ROOT))


from apps.pi_ui import (  # noqa: E402
    history_tab,
    io_tab,
    monitor,
    plan_tab,
    results_tab,
    review_tab,
    run_tab,
    sidebar,
)
from apps.pi_ui.common import _default_plan, output_dir  # noqa: E402
from price_lens.orchestrator import jobs, storefront_status  # noqa: E402

st.set_page_config(page_title="Price Lens", page_icon="🔎", layout="wide")
# Dark text on the lime primary buttons (the theme alone would use white text).
st.html("""<style>
[data-testid="stBaseButton-primary"]:not(:disabled), [data-testid="stBaseButton-primary"]:not(:disabled) p,
[data-testid="stBaseButton-primaryFormSubmit"]:not(:disabled),
[data-testid="stBaseButton-primaryFormSubmit"]:not(:disabled) p { color: #0E1013 !important; font-weight: 600; }
[data-baseweb="tag"] span, [data-baseweb="tag"] svg { color: #0E1013 !important; }
</style>""")

# ==========================================
# 1. STATE
# ==========================================
st.session_state.setdefault("plan", _default_plan())
st.session_state.setdefault("rev", 0)
plan: dict = st.session_state.plan
rev: int = st.session_state.rev
plan.setdefault("searches", [])

sf_status = storefront_status.load(output_dir())

# Reattach to a run that is still going (after a refresh or reopening the app).
if "active_job" not in st.session_state:
    running = jobs.find_active_jobs(output_dir())
    st.session_state.active_job = str(running[0]) if running else None

exec_cfg, sidebar_run_area = sidebar.render_settings(plan, rev)

# ==========================================
# 3. HEADER + LIVE STATUS (always visible, above the tabs)
# ==========================================
st.title("🔎 Price Lens")
status_area = st.container()

tab_builder, tab_run, tab_results, tab_review, tab_history, tab_io = st.tabs([
    "① Plan", "② Check & run", "③ Results", "④ Relevance review", "🗂️ History",
    "⇄ Import / export",
])

with tab_builder:
    plan_tab.render(plan, rev, sf_status)
with tab_io:
    io_tab.render(plan)

ctx = run_tab.render(plan, exec_cfg, sf_status, sidebar_run_area, tab_run, status_area)
monitor.render(status_area)

result = st.session_state.get("result")
if result and not st.session_state.active_job:
    with status_area:
        reports = result.get("reports", [])
        failed = [r for r in reports if r.get("status") == "failed"]
        if result.get("kind") == "check":
            pass
        elif failed and len(failed) == len(reports):
            st.error("All searches failed. See the Results tab for the errors.")
        elif failed:
            st.warning(f"{len(failed)} of {len(reports)} search(es) failed. See the Results tab.")
        elif result.get("recovered"):
            st.info(f"This run stopped unexpectedly (crash, sleep or shutdown). "
                    f"{result['recovered']['listings']} listing(s) from the storefronts that had "
                    "finished were recovered.")
        elif result.get("status") == "cancelled":
            st.warning(f"Run cancelled — {len(result['final'])} listings from finished searches were kept.")

with tab_results:
    results_tab.render(result, ctx["busy"])
with tab_review:
    review_tab.render(result)
with tab_history:
    history_tab.render(result)
