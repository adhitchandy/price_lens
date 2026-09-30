"""⇄ Import / export: AI prompt builder and plan JSON import/export."""
from __future__ import annotations

import json

import streamlit as st

from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator.analyst import (
    load_analyst_text,
    upgrade_to_v2,
)

from .common import (
    ROOT,
    _bump,
    copy_button,
)


def render(plan: dict):
    st.subheader("Let an AI write the plan")
    st.caption("Describe what you want in plain words. The app builds a prompt (the planning "
               "rules from agent/llmskill.md + your request) to paste into any AI chat. The AI "
               "first asks a few questions to sharpen the search (product type, brands, "
               "audiences, local search terms…) — answer them in the chat, then paste the JSON "
               "plan it returns under “Import LLM plan” below.")
    request_text = st.text_area(
        "Describe your research", height=110, key="describe_request",
        placeholder="e.g. Men's and women's sneaker prices in Germany, France and the UK on "
                    "Zalando, Amazon and eBay, about 50 per shop, no socks or laces.",
    )
    skill_path = ROOT / "agent" / "llmskill.md"
    skill_text = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
    if request_text.strip():
        prompt_text = f"{skill_text}\n\n## Research request\n\n{request_text.strip()}\n"
        copy_button(prompt_text, "Copy prompt", "Paste it into your AI chat (Ctrl+V).")
        with st.expander("Show prompt"):
            st.code(prompt_text, language=None, height=220)
    st.divider()
    st.subheader("Import & export research plans")
    col_exp, col_imp = st.columns(2)
    with col_exp:
        st.markdown("#### Export current plan")
        plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 Download analyst_plan.json",
            data=plan_json,
            file_name="analyst_plan.json",
            mime="application/json",
            width="stretch",
        )
        st.code(plan_json, language="json")

    with col_imp:
        st.markdown("#### Import LLM plan")
        uploaded_file = st.file_uploader("Upload analyst_plan.json", type=["json", "txt"])
        pasted_text = st.text_area("…or paste JSON", height=250)
        if st.button("Load Plan into Workspace", type="primary", width="stretch"):
            raw_payload = uploaded_file.getvalue().decode("utf-8-sig") if uploaded_file else pasted_text
            if not raw_payload.strip():
                st.warning("Upload a plan file or paste JSON first.")
            else:
                try:
                    parsed = load_analyst_text(raw_payload)
                    st.session_state.plan = upgrade_to_v2(parsed)
                    _bump()
                    st.session_state.flash = "Plan loaded. Review it on the Plan tab."
                    st.rerun()
                except RequestValidationError as exc:
                    st.error(f"Plan validation failed: {exc}")
                except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
                    st.error(f"Could not read plan: {exc}")

