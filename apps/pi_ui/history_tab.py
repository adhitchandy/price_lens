"""🗂️ History: past runs, open, delete, clean up."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from price_lens.orchestrator import (
    history,
)

from .common import (
    _open_run,
    output_dir,
)


def render(result: dict | None):
    st.subheader("Past runs and checks")
    runs = history.list_runs(output_dir())
    if runs.empty:
        st.info(f"No runs yet in `{output_dir()}`.")
    else:
        st.dataframe(runs.drop(columns=["path"]), hide_index=True, width="stretch")
        h1, h2 = st.columns([3, 2])
        picked = h1.selectbox("Select a run", runs["run"].tolist(), key="hist_pick")
        picked_path = Path(runs.loc[runs["run"] == picked, "path"].iloc[0])
        b1, b2 = h1.columns(2)
        if b1.button("📂 Open in Results", width="stretch"):
            _open_run(picked_path)
            st.session_state.flash = f"Opened {picked}. See the ③ Results and ④ Relevance review tabs."
            st.rerun()
        confirm = b2.checkbox("Confirm delete", key=f"hist_confirm_{picked}")
        if b2.button("🗑️ Delete run", disabled=not confirm, width="stretch"):
            try:
                history.delete_run(picked_path, output_dir())
                if result and Path(result["run_dir"]) == picked_path:
                    st.session_state.pop("result", None)
                st.session_state.flash = f"Deleted {picked}."
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))

        empty_failed = [Path(p) for p in runs["path"] if history.is_empty_failure(Path(p))]
        with h2.container(border=True):
            st.markdown(f"**Clean up:** {len(empty_failed)} failed or empty run(s)")
            sure = st.checkbox("I understand these folders are deleted", key="hist_bulk_confirm",
                               disabled=not empty_failed)
            if st.button("Delete failed / empty runs", disabled=not (empty_failed and sure)):
                removed, locked = 0, []
                for path in empty_failed:
                    try:
                        history.delete_run(path, output_dir())
                        removed += 1
                    except (ValueError, OSError):
                        locked.append(path.name)
                st.session_state.flash = f"Deleted {removed} failed or empty run(s)." + (
                    f" Could not delete (in use by another program): {', '.join(locked)}" if locked else "")
                st.rerun()
