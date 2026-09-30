"""Live monitor of the background run, shown above the tabs."""
from __future__ import annotations

import functools
from pathlib import Path

import streamlit as st

from price_lens.orchestrator import (
    jobs,
)

from . import components
from .common import (
    FORCE_STOP_AFTER_SECONDS,
    _open_run,
)


@st.fragment(run_every="2s")
def job_monitor() -> None:
    run_dir = st.session_state.get("active_job")
    if not run_dir:
        return
    job = jobs.read_job(Path(run_dir), log_lines=0)
    state = job.get("status", "unknown")
    label = ("Retry of failed storefronts" if job.get("merge_into") else
             "Storefront check" if job.get("kind") == "check" else "Scrape")

    if not jobs.is_active(job):
        st.session_state.active_job = None
        parent = job.get("merge_into")
        if parent and state not in {"crashed", "failed"}:
            _open_run(parent)
            added = (job.get("summary") or {}).get("added_listings", 0)
            st.session_state.flash_done = (f"Retry finished ({state}): added {added} listing(s) "
                                           f"to {Path(parent).name}.")
        else:
            _open_run(run_dir)
            st.session_state.flash_done = f"{label} finished: {state}."
        st.rerun()
        return

    key = f"pi_run_{Path(run_dir).name}"
    components.run_component()(
        key=key, height="content",
        data=components.run_payload(Path(run_dir), job, force_after=FORCE_STOP_AFTER_SECONDS),
        on_action_change=functools.partial(_on_action, key, run_dir),
    )


def _on_action(key: str, run_dir: str) -> None:
    action = (st.session_state.get(key) or {}).get("action")
    if action == "cancel":
        jobs.request_cancel(Path(run_dir))
    elif action == "force":
        jobs.force_kill(Path(run_dir))



def render(status_area):
    with status_area:
        if st.session_state.active_job:
            job_monitor()
        if note := st.session_state.pop("flash_done", None):
            st.info(note + " See the ③ Results tab.")
