"""Sidebar: collection size and advanced crawler settings."""
from __future__ import annotations

import streamlit as st


def render_settings(plan: dict, rev: int):
    with st.sidebar:
        st.header("🔎 Price research")
        exec_cfg = plan.setdefault("execution", {})
        size_slot = st.container()
        with st.expander("Advanced settings"):
            pages_mode = st.toggle(
                "Use a fixed number of result pages instead", key=f"pagesmode_{rev}",
                value=not exec_cfg.get("products_per_storefront"),
                help="Default: keep paging until each storefront has delivered the number of "
                     "products you ask for (max 20 pages).",
            )
            if pages_mode:
                exec_cfg.pop("products_per_storefront", None)
                exec_cfg["pages"] = int(st.number_input(
                    "Pages per query", min_value=1, max_value=20, step=1,
                    value=int(exec_cfg.get("pages", 1)), key=f"pages_{rev}",
                ))
            exec_cfg["retries"] = int(st.number_input(
                "Retries on failure", min_value=0, max_value=5, step=1,
                value=int(exec_cfg.get("retries", 2)), key=f"retries_{rev}",
            ))
            exec_cfg["headless"] = st.toggle(
                "Hide browser window (headless)", value=bool(exec_cfg.get("headless", False)),
                key=f"headless_{rev}", help="Visible browsers are blocked less often by bot checks.",
            )
            delays = list(exec_cfg.get("delay_seconds") or [2.5, 4.5]) + [4.5]
            low_d = st.number_input("Min pause between pages (s)", min_value=0.5, max_value=60.0,
                                    step=0.5, value=float(delays[0]), key=f"dlow_{rev}")
            high_d = st.number_input("Max pause between pages (s)", min_value=0.5, max_value=60.0,
                                     step=0.5, value=max(float(delays[1]), float(low_d)), key=f"dhigh_{rev}")
            exec_cfg["delay_seconds"] = [float(low_d), float(high_d)]
            exec_cfg["enrich_details"] = st.toggle(
                "Open product pages for extra details (Zalando / MediaMarkt)",
                value=bool(exec_cfg.get("enrich_details", False)), key=f"enrich_{rev}",
            )
            exec_cfg["max_detail_products"] = int(st.number_input(
                "Max product pages per storefront", min_value=1, max_value=10000, step=1,
                value=int(exec_cfg.get("max_detail_products") or 30), key=f"maxdet_{rev}",
            ))
        with size_slot:
            if not pages_mode:
                exec_cfg["products_per_storefront"] = int(st.number_input(
                    "Products per storefront", min_value=1, max_value=5000, step=10,
                    value=int(exec_cfg.get("products_per_storefront") or 100), key=f"ppsf_{rev}",
                    help="Per storefront and per query (each audience query counts separately).",
                ))
            else:
                st.caption(f"Collecting {exec_cfg.get('pages', 1)} result page(s) per query "
                           "(see Advanced settings).")
        st.divider()
        sidebar_run_area = st.container()
    return exec_cfg, sidebar_run_area
