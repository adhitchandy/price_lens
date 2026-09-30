"""① Plan: search builder."""
from __future__ import annotations

import copy
import hashlib

import pandas as pd
import streamlit as st

from price_lens.core.term_translations import suggest_translations
from price_lens.orchestrator import (
    planning,
    storefront_status,
)
from price_lens.orchestrator.analyst import (
    CATALOG,
)
from price_lens.orchestrator.audiences import audience_query, search_audiences

from .common import (
    AUDIENCES,
    _bump,
    _new_search,
    _split_words,
)


def render(plan: dict, rev: int, sf_status: dict):
    plan["research_question"] = st.text_input(
        "Research project goal",
        value=plan.get("research_question", ""),
        placeholder="e.g. European flagship electronics prices",
        key=f"rq_{rev}",
    )

    if st.button("➕ Add search"):
        plan["searches"].append(_new_search(len(plan["searches"]) + 1))
        _bump()
        st.rerun()

    if not plan["searches"]:
        st.info("No searches yet. Add one above or import a plan under Import / export.")

    for idx, search in enumerate(plan["searches"]):
        k = f"{rev}_{idx}"
        q_obj = search.setdefault("query", {})
        q_obj.setdefault("translations", {})
        filters = q_obj.setdefault("filters", {})

        with st.container(border=True):
            head_col, clone_col, del_col = st.columns([6, 1, 1])
            head_col.markdown(f"### Search #{idx + 1}: `{q_obj.get('default') or 'Untitled'}`")
            if clone_col.button("📋 Clone", key=f"clone_{k}"):
                duplicate = copy.deepcopy(search)
                duplicate["id"] = f"search_{len(plan['searches']) + 1}"
                plan["searches"].insert(idx + 1, duplicate)
                _bump()
                st.rerun()
            if del_col.button("🗑️ Delete", key=f"del_{k}"):
                plan["searches"].pop(idx)
                _bump()
                st.rerun()

            c1, c2 = st.columns(2)
            q_obj["default"] = c1.text_input(
                "Main query term", value=q_obj.get("default", ""), key=f"term_{k}"
            ).strip()
            search["product_type"] = c2.text_input(
                "Product category label", value=search.get("product_type", ""), key=f"type_{k}"
            ).strip()

            # ---- quick setup ------------------------------------------------------------
            qs1, qs2, qs3 = st.columns([2, 2, 1], vertical_alignment="bottom")
            preset = qs1.selectbox("Quick setup: product type", ["—", *planning.PRODUCT_PRESETS],
                                   key=f"preset_{k}",
                                   help="Sets suitable platforms, audiences and exclude words.")
            group = qs2.selectbox("Quick setup: countries", ["—", *planning.COUNTRY_GROUPS],
                                  key=f"group_{k}",
                                  help="Applies to every platform of this search, where available.")
            if qs3.button("Apply", key=f"qs_apply_{k}", disabled=preset == "—" and group == "—",
                          width="stretch"):
                notes = []
                if preset != "—":
                    notes += planning.apply_product_preset(search, preset)
                if group != "—":
                    notes += planning.apply_country_group(search, group)
                st.session_state.flash = "Quick setup applied." + (
                    " " + " · ".join(notes) if notes else "")
                _bump()
                st.rerun()

            # ---- platforms: one country picker per platform ---------------------------
            existing: dict[str, dict] = {}
            for tgt in search.get("targets") or []:
                plat = tgt.get("platform")
                if plat not in CATALOG:
                    continue
                if plat in existing:  # merge duplicate targets from imported plans
                    merged = [*existing[plat].get("countries", []), *(tgt.get("countries") or [])]
                    existing[plat]["countries"] = list(dict.fromkeys(merged))
                else:
                    existing[plat] = dict(tgt)
            chosen_platforms = st.multiselect(
                "Platforms", list(CATALOG), default=list(existing), key=f"plats_{k}",
                placeholder="Choose one or more platforms",
                help="The same search runs on every platform you pick.",
            )
            new_targets = []
            if chosen_platforms:
                cols = st.columns(min(len(chosen_platforms), 2))
                for i, plat in enumerate(chosen_platforms):
                    tgt = existing.get(plat) or {"platform": plat, "countries": [], "platform_options": {}}
                    plat_countries = sorted({info["country"] for info in CATALOG[plat].values()})
                    valid_defaults = [c for c in (tgt.get("countries") or [])
                                      if c == "all" or c in plat_countries]
                    tgt["countries"] = cols[i % len(cols)].multiselect(
                        f"Countries on {plat.title()}", options=["all", *plat_countries],
                        default=valid_defaults, key=f"countries_{k}_{plat}",
                        placeholder="Choose at least one country",
                    )
                    tgt["platform"] = plat
                    (tgt.get("platform_options") or {}).pop("audiences", None)  # now search-level
                    new_targets.append(tgt)
            search["targets"] = new_targets
            targets_list = new_targets
            others = [p for p in chosen_platforms if p != "zalando"]

            known_bad = storefront_status.problems(
                sf_status, [domain for _, domain, _, _ in planning.storefronts(search)])
            if known_bad:
                lines = [f"**{d}** — {info['result']} ({info['when'][:16].replace('T', ' ')} UTC)"
                         for d, info in known_bad.items()]
                w1, w2 = st.columns([5, 1], vertical_alignment="center")
                w1.warning("Failed last time:  \n" + "  \n".join(lines))
                if w2.button("Leave these out", key=f"skipbad_{k}"):
                    for tgt in search["targets"]:
                        bad_countries = {
                            CATALOG[tgt["platform"]][d]["country"]
                            for d in known_bad if d in CATALOG[tgt["platform"]]
                        }
                        if "all" in tgt["countries"]:
                            tgt["countries"] = sorted(planning.countries_on(tgt["platform"]))
                        tgt["countries"] = [c for c in tgt["countries"] if c not in bad_countries]
                    _bump()
                    st.rerun()

            # ---- audiences -------------------------------------------------------------
            au1, au2 = st.columns([2, 1])
            search["audiences"] = au1.multiselect(
                "Audiences (optional)", AUDIENCES, default=search_audiences(search), key=f"aud_{k}",
                help="Zalando searches its men / women / kids shops (all three if left empty). "
                     "Amazon, eBay and MediaMarkt have no such switch, so each audience becomes "
                     "its own query in the storefront's language, e.g. \"men's sneakers\", "
                     "\"Herren Sneaker\", \"baskets femme\".",
            )
            if search["audiences"] and others:
                search["split_audiences"] = au2.toggle(
                    "One query per audience on " + ", ".join(p.title() for p in others),
                    value=bool(search.get("split_audiences", True)), key=f"split_{k}",
                    help="Off: those platforms run the plain query once, without audience words.",
                )
            else:
                search.pop("split_audiences", None)
            splitting = bool(search["audiences"]) and bool(others) and search.get("split_audiences", True)
            if "zalando" in chosen_platforms and not search["audiences"]:
                st.caption("Zalando will search all three audience shops (men, women, kids).")

            # Languages used by every storefront this search touches (all targets).
            search_langs = sorted({
                info["language"]
                for tgt in targets_list
                for info in CATALOG.get(tgt.get("platform"), {}).values()
                if "all" in (tgt.get("countries") or []) or info["country"] in (tgt.get("countries") or [])
            })

            gaps = planning.missing_translations(search)
            if gaps:
                listed = "; ".join(
                    f"{planning.LANGUAGE_NAMES.get(lang, lang)} ({', '.join(countries[:4])}"
                    f"{'…' if len(countries) > 4 else ''})" for lang, countries in gaps.items())
                g1, g2 = st.columns([5, 1], vertical_alignment="center")
                g1.warning(
                    f"No local search term for: {listed}. These shops will search "
                    f"“{q_obj.get('default') or '…'}” as typed, which often returns the wrong "
                    "products. Add translations under *Language & audience query overrides*.")
                if g2.button("Use as typed", key=f"asis_{k}",
                             help="Confirm the term is correct in these languages (e.g. a brand "
                                  "or a word used locally, like 'Smartphone' in German)."):
                    for lang in gaps:
                        q_obj["translations"][lang] = q_obj.get("default") or ""
                    _bump()
                    st.rerun()

            with st.expander("Keyword & price filters"):
                f1, f2 = st.columns(2)
                filters["exclude"] = _split_words(f1.text_input(
                    "Exclude keywords (comma-separated)",
                    value=", ".join(filters.get("exclude") or []), key=f"ex_{k}",
                ))
                filters["include"] = _split_words(f2.text_input(
                    "Must-include keywords (comma-separated)",
                    value=", ".join(filters.get("include") or []), key=f"in_{k}",
                ))

                sugg_key = f"sugg_{idx}"
                if f1.button("🌐 Suggest translations", key=f"suggest_{k}",
                             disabled=not (filters["exclude"] and search_langs),
                             help="Adds local-language versions of your exclude words for the "
                                  "countries selected above (e.g. case → hülle, etui)."):
                    found, unknown = suggest_translations(filters["exclude"], search_langs)
                    st.session_state[sugg_key] = {
                        "words": [w for words in found.values() for w in words],
                        "unknown": unknown,
                    }
                pending = st.session_state.get(sugg_key)
                if pending is not None:
                    if pending["words"]:
                        edited_words = st.text_input(
                            "Suggested exclude words (edit before adding)",
                            value=", ".join(pending["words"]), key=f"sugg_text_{k}",
                        )
                        a1, a2, _ = st.columns([1, 1, 3])
                        if a1.button("Add these", key=f"sugg_add_{k}", type="primary"):
                            filters["exclude"] = list(dict.fromkeys(
                                [*filters["exclude"], *_split_words(edited_words)]))
                            st.session_state.pop(sugg_key, None)
                            _bump()
                            st.rerun()
                        if a2.button("Dismiss", key=f"sugg_no_{k}"):
                            st.session_state.pop(sugg_key, None)
                            st.rerun()
                    else:
                        st.info("No new translations to add for these words and languages.")
                    if pending["unknown"]:
                        st.caption("No offline translation known for: " + ", ".join(pending["unknown"]))

                p1, p2 = st.columns(2)
                min_p = p1.number_input(
                    "Minimum price (USD, 0 = none)", min_value=0.0, step=10.0,
                    value=float(filters.get("min_price") or 0.0), key=f"min_{k}",
                )
                max_p = p2.number_input(
                    "Maximum price (USD, 0 = none)", min_value=0.0, step=10.0,
                    value=float(filters.get("max_price") or 0.0), key=f"max_{k}",
                )
                filters["min_price"] = float(min_p) if min_p > 0 else None
                filters["max_price"] = float(max_p) if max_p > 0 else None
                st.caption("Keywords match anywhere in the listing title. Prices are compared "
                           "after conversion to USD so they work across currencies.")

            with st.expander(("⚠️ " if gaps else "") + "Language & audience query overrides",
                             expanded=bool(gaps)):
                st.caption("Blank cells use the main query term and the automatic audience phrases "
                           "shown on the right. Type only where you want a better local phrase.")
                translations: dict = q_obj["translations"]
                audience_overrides: dict = q_obj.get("audience_queries") or {}
                aud_cols = list(search["audiences"]) if splitting else []
                other_langs = sorted({
                    info["language"] for tgt in targets_list if tgt["platform"] != "zalando"
                    for info in CATALOG[tgt["platform"]].values()
                    if "all" in tgt["countries"] or info["country"] in tgt["countries"]
                })
                if search_langs:
                    rows = []
                    for lang in search_langs:
                        value = translations.get(lang, "")
                        if isinstance(value, dict):
                            value = value.get("search_term", "")
                        row = {"Language": lang, "Translated search term": value}
                        base = (value or q_obj.get("default") or "…").strip()
                        for aud in aud_cols:
                            row[f"{aud} query"] = (audience_overrides.get(lang) or {}).get(aud, "")
                        if aud_cols:
                            row["Automatic audience phrases"] = (
                                " · ".join(audience_query(base, a, lang) for a in aud_cols)
                                if lang in other_langs else "(Zalando only: audience shops)")
                        rows.append(row)
                    signature = hashlib.md5(
                        (",".join(search_langs) + "|" + ",".join(aud_cols)).encode()).hexdigest()[:8]
                    edited = st.data_editor(
                        pd.DataFrame(rows),
                        disabled=["Language", "Automatic audience phrases"],
                        hide_index=True,
                        width="stretch",
                        key=f"lang_{k}_{signature}",
                    )
                    updated: dict = {
                        lang: value for lang, value in translations.items() if lang not in search_langs
                    }
                    new_aud_overrides: dict = {
                        lang: value for lang, value in audience_overrides.items()
                        if lang not in search_langs or not aud_cols  # keep while hidden
                    }
                    for _, row in edited.iterrows():
                        lang = str(row["Language"])
                        raw_term = row["Translated search term"]
                        term = "" if pd.isna(raw_term) else str(raw_term).strip()
                        if term:
                            previous = translations.get(lang)
                            if isinstance(previous, dict):  # keep per-language include/exclude
                                updated[lang] = {**previous, "search_term": term}
                            else:
                                updated[lang] = term
                        for aud in aud_cols:
                            raw = row.get(f"{aud} query")
                            phrase = "" if raw is None or pd.isna(raw) else str(raw).strip()
                            if phrase:
                                new_aud_overrides.setdefault(lang, {})[aud] = phrase
                    q_obj["translations"] = updated
                    if new_aud_overrides:
                        q_obj["audience_queries"] = new_aud_overrides
                    else:
                        q_obj.pop("audience_queries", None)
                else:
                    st.info("Select at least one country to see its query languages.")

