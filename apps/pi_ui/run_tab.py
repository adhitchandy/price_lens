"""② Check & run: validation, estimate, run buttons, latest storefront check."""
from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import streamlit as st

from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator import (
    history,
    jobs,
    planning,
    storefront_status,
)
from price_lens.orchestrator.analyst import (
    compile_analyst_plan,
)

from .common import (
    output_dir,
)


def render(plan: dict, exec_cfg: dict, sf_status: dict, sidebar_run_area, tab_run, status_area):
    validation_error = None
    preview_rows: list[dict] = []
    if not plan["searches"]:
        validation_error = "Add at least one search."
    else:
        try:
            _, preview_rows = compile_analyst_plan(plan)
        except RequestValidationError as exc:
            validation_error = str(exc)
    valid_plan = validation_error is None and bool(preview_rows)
    busy = bool(st.session_state.active_job)

    estimate = planning.estimate_minutes(preview_rows, exec_cfg) if preview_rows else 0
    all_domains = sorted({r["domain"] for r in preview_rows})
    plan_problems = storefront_status.problems(sf_status, all_domains)


    def _estimate_text() -> str:
        hours, minutes = divmod(estimate, 60)
        return f"~{hours} h {minutes} min" if hours else f"~{minutes} min"


    with sidebar_run_area:
        if validation_error:
            st.error(validation_error)
        else:
            st.success(f"{len(plan['searches'])} search(es) · {len(preview_rows)} storefront "
                       f"query(ies) · {_estimate_text()}")
        run_clicked = st.button("🚀 Run scraper", type="primary", width="stretch",
                                disabled=not valid_plan or busy)
        check_clicked = st.button(
            "🩺 Test storefronts first", width="stretch", disabled=not valid_plan or busy,
            help="Opens one result page per storefront to spot cookie walls, redirects or bot "
                 "checks before a big run.",
        )
        if plan_problems and not busy:
            st.caption(f"⚠️ {len(plan_problems)} storefront(s) failed last time — see ② Check & run.")
        if busy:
            st.caption("A run is in progress — see the status panel.")

    with tab_run:
        if validation_error:
            st.error(f"The plan is not ready yet: {validation_error}")
        elif preview_rows:
            m1, m2, m3 = st.columns(3)
            m1.metric("Searches", len(plan["searches"]))
            m2.metric("Storefront queries", len(preview_rows))
            m3.metric("Estimated time", _estimate_text(),
                      help="Rough guide from typical page load times and your pause settings.")
            b1, b2, _ = st.columns([1, 1, 2])
            run_clicked |= b1.button("🚀 Run scraper", type="primary", width="stretch",
                                     disabled=busy, key="run_tab")
            check_clicked |= b2.button("🩺 Test storefronts", width="stretch", disabled=busy,
                                       key="check_tab")
            if plan_problems:
                st.warning("These storefronts failed last time. Consider testing them first or "
                           "leaving them out on the Plan tab:  \n" + "  \n".join(
                               f"**{d}** — {info['result']}: {info['problem'][:140] or '—'}"
                               for d, info in plan_problems.items()))
            st.subheader("What will be searched")
            st.dataframe(
                pd.DataFrame(preview_rows).rename(columns={
                    "search_id": "Search", "category": "Category", "platform": "Platform",
                    "country": "Country", "domain": "Storefront", "language": "Language",
                    "audience": "Audience", "query": "Search term", "exclude": "Excluded words"}),
                hide_index=True, width="stretch")

        checks = history.list_runs(output_dir())
        checks = checks[checks["type"] == "Storefront check"] if not checks.empty else checks
        if not checks.empty:
            latest = Path(checks.iloc[0]["path"])
            check_csv = latest / "storefront_check.csv"
            if check_csv.exists():
                st.subheader("Latest storefront check")
                st.caption(f"{checks.iloc[0]['started_utc']} UTC · `{latest.name}`")
                table = pd.read_csv(check_csv, encoding="utf-8-sig").fillna("")

                def _colour(value: str) -> str:
                    return ("background-color: rgba(34,197,94,.18)" if value == "OK" else
                            "background-color: rgba(234,179,8,.22)" if value == "Partial" else
                            "background-color: rgba(239,68,68,.18)")

                st.dataframe(table.style.map(_colour, subset=["result"]), hide_index=True,
                             width="stretch")

    if (run_clicked or check_clicked) and valid_plan and not busy:
        kind = "scrape" if run_clicked else "check"
        try:
            run_dir = jobs.start_job(copy.deepcopy(plan), output_dir(), kind=kind)
            st.session_state.active_job = str(run_dir)
            st.session_state.pop("result", None)
        except (OSError, ValueError) as exc:
            status_area.error(f"Could not start the background run: {exc}")

    if msg := st.session_state.pop("flash", None):
        status_area.success(msg)
    return {"valid_plan": valid_plan, "preview_rows": preview_rows, "busy": busy,
            "validation_error": validation_error}
