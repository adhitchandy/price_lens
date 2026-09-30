"""④ Relevance review."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from price_lens.agent import assist
from price_lens.agent.review import (
    apply_review_decisions,
    extend_review_batches,
    prepare_review_batches,
    review_outdated,
    review_status,
)
from price_lens.core.validation import RequestValidationError
from price_lens.orchestrator import (
    history,
)

from .common import (
    _split_words,
    copy_button,
)


def render(result: dict | None):
    st.subheader("AI relevance review (optional)")
    st.caption("An AI model checks every listing against your research goal and removes "
               "accessories, parts and unrelated products that slipped past the keyword filters.")
    source = Path(result["run_dir"]) / "detailed_products.csv" if result else None
    if not result or result.get("kind") == "check" or not source or not source.exists() \
            or len(result.get("final", [])) == 0:
        st.info("Open a scrape run with listings (run one, or pick it in Run History) to review it.")
    else:
        run_dir = Path(result["run_dir"])
        review_dir = run_dir / "ai_review"
        run_plan = history._read_json(run_dir / "analyst_plan.json") or {}
        manifest_exists = (review_dir / "manifest.json").exists()
        stale = review_outdated(review_dir)
        if stale:
            st.warning(f"{stale['added']} listing(s) were added to this run after the review "
                       f"({', '.join(stale['reasons'])}) and have not been reviewed yet.")
            if st.button(f"➕ Add the {stale['added']} new listing(s) to the review", type="primary"):
                added = extend_review_batches(review_dir, source)
                st.session_state.rv_note = (f"Added {added['added']} listing(s) as new batches. "
                                            "Existing decisions are kept; review the new batches, "
                                            "then apply the review again.")
                st.rerun()
        applied = history._read_json(review_dir / "ai_review_report.json")

        if not manifest_exists:
            st.markdown(f"**Run:** `{run_dir.name}` · {len(result['final'])} listings")
            product_types = [s.get("product_type", "") for s in run_plan.get("searches", [])]
            instruction = st.text_area(
                "What should be kept?",
                value=assist.default_instruction(product_types, run_plan.get("research_question", "")),
                height=110, key=f"rv_instr_{run_dir.name}",
            )
            r1, r2, r3 = st.columns(3)
            batch_size = r1.number_input(
                "Products per batch", 1, 500,
                assist.RECOMMENDED_BATCH_API if assist.api_available() else assist.RECOMMENDED_BATCH_CHAT,
                key="rv_batch",
                help="~150 works reliably when pasting into ChatGPT, Gemini or Claude; with the "
                     "Claude API, ~100 per batch lets several batches run at the same time.")
            min_conf = r2.slider("Minimum confidence to accept", 0.5, 1.0, 0.8, 0.05, key="rv_conf")
            brands = r3.text_input("Only these brands (optional, comma-separated)", key="rv_brands")
            if st.button("Prepare review", type="primary"):
                try:
                    prepare_review_batches(
                        source, review_dir,
                        research_question=run_plan.get("research_question") or "Product research",
                        instruction=instruction.strip(), batch_size=int(batch_size),
                        minimum_keep_confidence=float(min_conf),
                        allowed_brands=tuple(b.lower() for b in _split_words(brands)),
                    )
                    st.rerun()
                except RequestValidationError as exc:
                    st.error(str(exc))
        else:
            progress = review_status(review_dir)
            done, total = len(progress["completed_batches"]), progress["total_batches"]
            remaining = assist.pending_products(review_dir) if progress["pending_batches"] else 0
            st.progress(done / max(1, total),
                        text=f"{done} of {total} batch(es) reviewed"
                             + (f" · {remaining} product(s) left" if remaining else ""))
            batch_files = assist.batch_files(review_dir)

            if note := st.session_state.pop("rv_note", None):
                st.success(note)

            if progress["pending_batches"]:
                if assist.api_available():
                    if st.button(f"🤖 Review {remaining} product(s) with Claude "
                                 f"({len(progress['pending_batches'])} batch(es), in parallel)",
                                 type="primary"):
                        with st.status("Reviewing with Claude…", expanded=True) as box:
                            outcome = assist.review_with_claude(review_dir, workers=5,
                                                                progress=st.write)
                            if outcome["pending"]:
                                box.update(label=f"{len(outcome['pending'])} batch(es) still open",
                                           state="error")
                            else:
                                box.update(label=f"All done — {outcome['saved']} decisions",
                                           state="complete")
                        st.rerun()
                else:
                    st.caption("Tip: set an `ANTHROPIC_API_KEY` environment variable before "
                               "starting the app to review everything automatically, several "
                               "batches at a time.")

                with st.expander("Review with any AI chat (copy / paste)",
                                 expanded=not assist.api_available()):
                    mode = st.radio(
                        "What to copy", ["All remaining products in one prompt", "One batch at a time"],
                        horizontal=True, key="rv_mode",
                        help="One prompt is fastest in chats with a long context (Claude, Gemini, "
                             "ChatGPT). If the answer gets cut off, the app keeps what arrived and "
                             "puts the rest in a small follow-up batch.")
                    if mode.startswith("All"):
                        chosen = list(progress["pending_batches"])
                    else:
                        chosen = [st.selectbox("Batch", progress["pending_batches"], key="rv_pick")]
                    prompt = assist.compact_prompt([batch_files[n] for n in chosen])
                    count = sum(len(assist.load_batch(batch_files[n])["products"]) for n in chosen)
                    st.markdown(f"**1. Copy the prompt** ({count} products) and paste it into your AI chat:")
                    copy_button(prompt, "Copy prompt", "Now paste it into your AI chat (Ctrl+V).")
                    with st.expander("Show prompt"):
                        st.code(prompt, language=None, height=260)
                    answer_key = "rv_answer_" + hashlib.md5("|".join(chosen).encode()).hexdigest()[:8]
                    answer = st.text_area("2. Paste the AI's answer here (lines like "
                                          "`p001|keep|0.95|smartphone|complete phone`)",
                                          height=180, key=answer_key)
                    if st.button("Save answer", key=f"save_{answer_key}", type="primary"):
                        try:
                            res = assist.save_answer(review_dir, chosen, answer)
                            msg = f"Saved {res['saved']} decision(s)."
                            if res["missing"]:
                                msg += (f" {res['missing']} product(s) were not answered and are now in "
                                        f"follow-up batch {', '.join(res['followups'])}.")
                            st.session_state.rv_note = msg
                            st.rerun()
                        except RequestValidationError as exc:
                            st.error(str(exc))
            elif not applied:
                if st.button("✅ Apply review", type="primary"):
                    try:
                        apply_review_decisions(review_dir)
                        st.rerun()
                    except RequestValidationError as exc:
                        st.error(str(exc))

            if applied:
                st.success("Review applied. The ③ Results tab now shows the reviewed prices "
                           "(switch between reviewed and all data at the top of that tab).")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Reviewed", applied["reviewed"])
                m2.metric("Accepted", applied["accepted"])
                m3.metric("Uncertain (kept)", applied["uncertain"])
                m4.metric("Excluded", applied["excluded"])
                reviewed_path = review_dir / "final_products.csv"
                if reviewed_path.exists():
                    reviewed = pd.read_csv(reviewed_path, encoding="utf-8-sig")
                    dl1, dl2, dl3 = st.columns(3)
                    dl1.download_button("Download reviewed CSV", reviewed_path.read_bytes(),
                                        "reviewed_products.csv", "text/csv")
                    xlsx = review_dir / "final_products.xlsx"
                    if xlsx.exists():
                        dl2.download_button(
                            "Download reviewed XLSX", xlsx.read_bytes(), "reviewed_products.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    audit = review_dir / "ai_classified_products.csv"
                    if audit.exists():
                        dl3.download_button("Download full audit (with reasons)", audit.read_bytes(),
                                            "ai_classified_products.csv", "text/csv")
                    st.dataframe(reviewed, hide_index=True, width="stretch")
                    if audit.exists():
                        with st.expander("Excluded listings and reasons"):
                            audit_df = pd.read_csv(audit, encoding="utf-8-sig")
                            cols = [c for c in ("product_name", "marketplace", "price_value",
                                                "ai_category", "ai_confidence", "ai_reason")
                                    if c in audit_df.columns]
                            st.dataframe(audit_df.loc[audit_df["review_status"] == "excluded", cols],
                                         hide_index=True, width="stretch")

            if st.button("↺ Start review over", help="Deletes this run's review files."):
                try:
                    if review_dir.exists():
                        history._rmtree_retrying(review_dir)
                    st.rerun()
                except OSError as exc:
                    st.error(f"Could not delete the review files (in use by another program?): {exc}")

