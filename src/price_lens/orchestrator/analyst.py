"""Portable, non-agent plans. Each search has independent country/platform scope."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pandas as pd

from price_lens.agent.review import FINAL_PRODUCT_FIELDS
from price_lens.core.export import (
    create_run_directory,
    write_csv,
    write_excel,
    write_json,
)
from price_lens.core import fx
from price_lens.core.cleaning import apply_cleaning
from price_lens.core.localization import language_options
from price_lens.core.validation import RequestValidationError
from price_lens.marketplaces.amazon.constants import AMAZON_DOMAINS
from price_lens.marketplaces.ebay.constants import EBAY_MARKETPLACES
from price_lens.marketplaces.mediamarkt.constants import (
    MEDIAMARKT_MARKETPLACES,
    UNAVAILABLE_MARKETPLACES,
)
from price_lens.marketplaces.zalando.constants import ZALANDO_MARKETPLACES

from .audiences import AUDIENCES, audience_query, search_audiences
from .localization import CHECKPOINT_DIR, RunPaused
from .runner import DEFAULT_CLEANING, run_research
from .validation import parse_research_plan

CATALOG = {
    platform: {domain: {"country": country, "language": language_options(domain, country)[0]}
               for domain, country in domains.items() if domain not in UNAVAILABLE_MARKETPLACES}
    for platform, domains in {
        "amazon": AMAZON_DOMAINS, "ebay": EBAY_MARKETPLACES,
        "zalando": ZALANDO_MARKETPLACES, "mediamarkt": MEDIAMARKT_MARKETPLACES,
    }.items()
}
COUNTRIES = sorted({item["country"] for domains in CATALOG.values() for item in domains.values()})


def targets(search):
    """Resolves matching platform/domain entries for a search specification."""
    if "targets" in search:
        resolved = {}
        for target in search.get("targets", []):
            platform = target.get("platform")
            if platform not in CATALOG:
                continue
            countries = target.get("countries", [])
            matched = {
                domain: info
                for domain, info in CATALOG[platform].items()
                if "all" in countries or info["country"] in countries
            }
            if matched:
                resolved.setdefault(platform, {}).update(matched)
        return resolved

    # Backward compatibility with analyst-v1 format
    return {
        platform: {
            domain: info
            for domain, info in CATALOG[platform].items()
            if "all" in search.get("countries", []) or info["country"] in search.get("countries", [])
        }
        for platform in search.get("platforms", [])
        if platform in CATALOG
    }


ANALYST_CLEANING = {
    "remove_sponsored": True,
    "remove_no_price": True,
    "remove_duplicates": True,
    "remove_outliers": False,
}

ALLOWED_SETTINGS = {
    "pages", "products_per_storefront", "retries", "headless", "delay_seconds",
    "enrich_details", "max_detail_products",
}
MAX_PAGES = 20


def research_settings(exec_config: dict) -> dict:
    """Translate analyst execution settings into research-plan settings.

    ``products_per_storefront`` (a product target) takes precedence over ``pages``: the
    scrapers may then page up to MAX_PAGES and stop as soon as the target is reached.
    """
    settings = {k: v for k, v in exec_config.items() if k != "products_per_storefront"}
    target = exec_config.get("products_per_storefront")
    if target is not None:
        if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 5000:
            raise RequestValidationError("'products_per_storefront' must be an integer between 1 and 5000.")
        settings["max_products"] = target
        settings["pages"] = MAX_PAGES
    return settings


def load_analyst_text(text):
    """Parses and validates JSON plan content supporting analyst-v2 and analyst-v1 schemas."""
    cleaned_text = text.lstrip("\ufeff").strip()
    if cleaned_text.startswith("```"):
        match = re.fullmatch(r"```(?:json|txt)?\s*\n(.*)\n```", cleaned_text, re.DOTALL)
        if not match:
            raise RequestValidationError("Paste one JSON object without surrounding commentary.")
        cleaned_text = match[1]

    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        raise RequestValidationError(f"Invalid JSON at line {exc.lineno}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise RequestValidationError("Plan must be a JSON object.")

    schema_version = data.get("schema_version")
    if schema_version not in ("analyst-v1", "analyst-v2"):
        raise RequestValidationError("Schema version must be 'analyst-v2' (or 'analyst-v1').")

    searches = data.get("searches")
    if not isinstance(searches, list) or not searches:
        raise RequestValidationError("At least one search is required in 'searches'.")
    if len(searches) > 100:
        raise RequestValidationError("At most 100 searches permitted per plan.")

    exec_config = data.get("execution") or data.get("settings", {})
    if not isinstance(exec_config, dict):
        raise RequestValidationError("'execution' must be a settings object.")

    unsupported_settings = set(exec_config) - ALLOWED_SETTINGS
    if unsupported_settings:
        raise RequestValidationError(f"Unsupported execution settings: {', '.join(sorted(unsupported_settings))}")

    parse_research_plan({
        "research_question": "Validate settings",
        **research_settings(exec_config),
        "marketplaces": {"mediamarkt": ["mediamarkt.de"]},
        "searches": [{"search_term": "validation_probe", "product_type": "Validation"}],
    })

    for idx, item in enumerate(searches, start=1):
        if not isinstance(item, dict):
            raise RequestValidationError(f"Search {idx} must be an object.")

        if schema_version == "analyst-v2":
            product_type = item.get("product_type")
            if not isinstance(product_type, str) or not product_type.strip():
                raise RequestValidationError(f"Search {idx} requires a non-empty 'product_type'.")

            query = item.get("query")
            if not isinstance(query, dict):
                raise RequestValidationError(f"Search {idx} requires a 'query' object.")

            default_term = query.get("default")
            if not isinstance(default_term, str) or not default_term.strip():
                raise RequestValidationError(f"Search {idx} requires a non-empty 'query.default' search term.")

            translations = query.get("translations", {})
            if not isinstance(translations, dict):
                raise RequestValidationError(f"Search {idx} 'query.translations' must be a dictionary.")

            filters = query.get("filters", {})
            if not isinstance(filters, dict):
                raise RequestValidationError(f"Search {idx} 'query.filters' must be an object.")
            for key in ("include", "exclude"):
                words = filters.get(key, [])
                if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
                    raise RequestValidationError(f"Search {idx} 'query.filters.{key}' must be a list of strings.")
            low, high = filters.get("min_price"), filters.get("max_price")
            for key, value in (("min_price", low), ("max_price", high)):
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                    raise RequestValidationError(f"Search {idx} 'query.filters.{key}' must be null or a positive number.")
            if low is not None and high is not None and high < low:
                raise RequestValidationError(f"Search {idx}: max_price must be greater than min_price.")

            audiences_value = item.get("audiences", [])
            if not isinstance(audiences_value, list) or any(a not in AUDIENCES for a in audiences_value):
                raise RequestValidationError(f"Search {idx} 'audiences' must be a list of men, women, kids.")
            if not isinstance(item.get("split_audiences", True), bool):
                raise RequestValidationError(f"Search {idx} 'split_audiences' must be true or false.")
            audience_queries = query.get("audience_queries", {})
            if not isinstance(audience_queries, dict) or not all(
                isinstance(v, dict) and all(k in AUDIENCES and isinstance(t, str) for k, t in v.items())
                for v in audience_queries.values()
            ):
                raise RequestValidationError(
                    f"Search {idx} 'query.audience_queries' must map language -> {{men|women|kids: phrase}}.")

            targets_data = item.get("targets")
            if not isinstance(targets_data, list) or not targets_data:
                raise RequestValidationError(f"Search {idx} requires a non-empty 'targets' list.")

            for t_idx, target in enumerate(targets_data, start=1):
                if not isinstance(target, dict):
                    raise RequestValidationError(f"Search {idx} target {t_idx} must be an object.")
                platform = target.get("platform")
                if platform not in CATALOG:
                    raise RequestValidationError(f"Search {idx} target {t_idx} has unsupported platform '{platform}'.")
                countries = target.get("countries")
                if not isinstance(countries, list) or not countries:
                    raise RequestValidationError(f"Search {idx} target {t_idx} requires non-empty 'countries'.")
                invalid_c = [c for c in countries if c != "all" and c not in COUNTRIES]
                if invalid_c:
                    raise RequestValidationError(f"Search {idx} contains invalid countries: {', '.join(invalid_c)}")
        else:
            for field in ("search_term", "product_type"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise RequestValidationError(f"Each search needs {field}.")
            for field, choices in (("countries", ["all", *COUNTRIES]), ("platforms", list(CATALOG)),
                                   ("audiences", ["men", "women", "kids"])):
                value = item.get(field, [] if field == "audiences" else None)
                if not isinstance(value, list) or any(not isinstance(x, str) or x not in choices for x in value):
                    raise RequestValidationError(f"Invalid {field} for {item['search_term']}.")
                if field != "audiences" and not value:
                    raise RequestValidationError(f"Select {field} for {item['search_term']}.")

    return data


def _compile_v2_search(index: int, search: dict, selected: dict, preview: list) -> list[dict]:
    """One analyst-v2 search -> research-plan searches.

    * Zalando: one search; its audience shops (men / women / kids) are chosen by the scraper.
    * Amazon, eBay, MediaMarkt: no audience switch exists, so when audiences are set and
      ``split_audiences`` is true (default) the query is run once per audience with the
      audience in the phrase ("men's sneakers", "Herren Sneaker", "baskets homme").
    """
    q_obj = search["query"]
    default_query = q_obj["default"].strip()
    translations = q_obj.get("translations") or {}
    audience_overrides = q_obj.get("audience_queries") or {}
    filters = q_obj.get("filters") or {}
    base_include = list(filters.get("include") or [])
    base_exclude = list(filters.get("exclude") or [])
    audiences = search_audiences(search)
    split = bool(audiences) and bool(search.get("split_audiences", True))

    def base_term(lang: str) -> tuple[str, list[str], list[str]]:
        override = translations.get(lang)
        if isinstance(override, str) and override.strip():
            return override.strip(), base_include, base_exclude
        if isinstance(override, dict):
            return (str(override.get("search_term") or "").strip() or default_query,
                    list(override.get("include", base_include)),
                    list(override.get("exclude", base_exclude)))
        return default_query, base_include, base_exclude

    def add_preview(platform, domain, info, lang, term, exc, audience_label):
        preview.append({
            "search_id": index, "category": search["product_type"], "platform": platform,
            "country": info["country"], "domain": domain, "language": lang,
            "audience": audience_label, "query": term, "exclude": ", ".join(exc),
        })

    specs: list[dict] = []
    zalando = selected.get("zalando") or {}
    others = {p: ds for p, ds in selected.items() if p != "zalando"}

    if zalando:
        zalando_audiences = audiences or list(AUDIENCES)
        localized = {}
        for domain, info in zalando.items():
            lang = info["language"]
            term, inc, exc = base_term(lang)
            localized[domain] = {"language": lang, "search_term": term, "include": inc, "exclude": exc}
            add_preview("zalando", domain, info, lang, term, exc, ", ".join(zalando_audiences))
        specs.append({"search_term": default_query, "product_type": search["product_type"],
                      "audiences": zalando_audiences, "platforms": ["zalando"],
                      "localized_queries": localized})

    if others:
        for audience in (audiences if split else [None]):
            localized = {}
            for platform, domains in others.items():
                for domain, info in domains.items():
                    lang = info["language"]
                    term, inc, exc = base_term(lang)
                    if audience:
                        term = audience_query(term, audience, lang, audience_overrides)
                    localized[domain] = {"language": lang, "search_term": term,
                                         "include": inc, "exclude": exc}
                    if audience:
                        localized[domain]["audience"] = audience
                    add_preview(platform, domain, info, lang, term, exc, audience or "")
            source = (audience_query(default_query, audience, "en", audience_overrides)
                      if audience else default_query)
            specs.append({"search_term": source, "product_type": search["product_type"],
                          "platforms": list(others), "localized_queries": localized})
    return specs


def compile_analyst_plan(data):
    """Compiles the JSON plan into executable scraper plans and a preview matrix."""
    verified_data = load_analyst_text(json.dumps(data) if not isinstance(data, str) else data)
    plans = []
    preview = []

    exec_settings = verified_data.get("execution") or verified_data.get("settings", {})
    schema_version = verified_data.get("schema_version", "analyst-v2")

    for index, search in enumerate(verified_data["searches"], start=1):
        selected = {p: ds for p, ds in targets(search).items() if ds}
        if not selected:
            raise RequestValidationError(f"Search {index}: no supported country/platform combinations.")

        if schema_version == "analyst-v2":
            specs = _compile_v2_search(index, search, selected, preview)
        else:
            translations = search.get("translations", {})
            localized = {}
            for platform, domains in selected.items():
                for domain, info in domains.items():
                    lang = info["language"]
                    value = translations.get(lang)
                    if not isinstance(value, dict) or not value.get("search_term"):
                        raise RequestValidationError(f"Search {index}: add a {lang} translation for {domain}.")
                    localized[domain] = {"language": lang, **value}
                    preview.append({
                        "search_id": index,
                        "category": search["product_type"],
                        "platform": platform,
                        "country": info["country"],
                        "domain": domain,
                        "language": lang,
                        "query": value["search_term"],
                        "exclude": ", ".join(value.get("exclude", [])),
                    })

            specs = [{
                "search_term": search["search_term"],
                "product_type": search["product_type"],
                "audiences": search.get("audiences", []),
                "localized_queries": localized,
            }]

        plans.append(parse_research_plan({
            "research_question": verified_data.get("research_question") or specs[0]["search_term"],
            **research_settings(exec_settings),
            "marketplaces": {p: list(ds) for p, ds in selected.items()},
            "require_localized_queries": True,
            "searches": specs,
            "cleaning": ANALYST_CLEANING,
        }))

    return plans, preview


def _price_ranges(data) -> list[tuple[float | None, float | None]]:
    """Per-search (min, max) price filters, interpreted in USD (``price_usd``)."""
    verified = load_analyst_text(json.dumps(data) if not isinstance(data, str) else data)
    ranges: list[tuple[float | None, float | None]] = []
    for search in verified["searches"]:
        filters = (search.get("query") or {}).get("filters") or {}
        ranges.append((filters.get("min_price"), filters.get("max_price")))
    return ranges


def _apply_price_range(frame: pd.DataFrame, low, high, log=print) -> pd.DataFrame:
    if frame.empty or (low is None and high is None):
        return frame
    column = "price_usd" if "price_usd" in frame.columns else "price_value"
    if column not in frame.columns:
        return frame
    prices = pd.to_numeric(frame[column], errors="coerce")
    mask = prices.notna()
    if low is not None:
        mask &= prices >= float(low)
    if high is not None:
        mask &= prices <= float(high)
    removed = int((~mask).sum())
    if removed:
        log(f"Price filter ({low or 0} - {high or 'any'} USD) removed {removed} listing(s).")
    return frame.loc[mask].reset_index(drop=True)


def upgrade_to_v2(data: dict) -> dict:
    """Convert an analyst-v1 plan into the analyst-v2 shape used by the visual builder."""
    if data.get("schema_version") == "analyst-v2":
        return data
    searches = []
    for index, item in enumerate(data.get("searches", []), start=1):
        translations = {}
        for lang, value in (item.get("translations") or {}).items():
            if isinstance(value, dict) and value.get("search_term"):
                translations[lang] = {
                    "search_term": value["search_term"],
                    "include": list(value.get("include", [])),
                    "exclude": list(value.get("exclude", [])),
                }
        targets_list = [{"platform": platform, "countries": list(item.get("countries", [])),
                         "platform_options": {}} for platform in item.get("platforms", [])]
        searches.append({
            "id": f"search_{index}",
            "product_type": item.get("product_type", ""),
            # v1 only applied audiences to Zalando; keep that behaviour.
            "audiences": list(item.get("audiences") or []),
            "split_audiences": False,
            "query": {
                "default": item.get("search_term", ""),
                "translations": translations,
                "filters": {"include": [], "exclude": [], "min_price": None, "max_price": None},
            },
            "targets": targets_list,
        })
    return {
        "schema_version": "analyst-v2",
        "research_question": data.get("research_question", ""),
        "execution": dict(data.get("execution") or data.get("settings") or {}),
        "searches": searches,
    }


class RunCancelled(BaseException):
    """Raised (from the log callback) to stop a run; finished searches are still saved.

    Derives from BaseException so scraper ``except Exception`` blocks do not swallow it,
    while their ``finally`` blocks still close the browser.
    """


def run_analyst_plan(
    data,
    output_dir=Path("output"),
    log=print,
    runner=run_research,
    root: Path | None = None,
):
    """Executes the compiled analyst plan and writes standard CSV, Excel, and JSON outputs."""
    plans, preview = compile_analyst_plan(data)
    root = Path(root) if root is not None else create_run_directory(Path(output_dir), "analyst")
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "analyst_plan.json", data)
    write_csv(pd.DataFrame(preview), root / "executed_queries.csv")

    price_ranges = _price_ranges(data)
    # a retry arrives with the rates of the research it is added to
    rates = fx.load_for_run(root) or fx.rates_for_new_run(root.parent)
    fx.save_for_run(root, rates)
    log(fx.describe(rates))
    frames, audit, reports = [], [], []
    for index, plan in enumerate(plans, start=1):
        try:
            log(f"\n##### Search {index}/{len(plans)}: {plan.searches[0].search_term} #####")
            result = runner(replace(plan, output_dir=root / f"search_{index:03}"), log=log)
            cleaned_frame = _apply_price_range(fx.apply(result.cleaned_products, rates["rates"]),
                                               *price_ranges[index - 1], log=log)
            raw_frame = fx.apply(result.raw_products, rates["rates"])
            for source, target in ((raw_frame, audit), (cleaned_frame, frames)):
                frame = source.copy()
                frame["search_id"] = index
                target.append(frame)
            reports.append({
                "search_id": index,
                "status": result.report.get("status", "completed"),
                "output": str(result.run_dir),
                "report": result.report,
            })
            if index < len(plans):  # interim save: finished searches survive a crash
                try:
                    write_run_outputs(root, frames, audit, reports)
                except OSError:
                    pass
        except (RunCancelled, RunPaused) as stop:
            state = "paused" if isinstance(stop, RunPaused) else "cancelled"
            # storefronts of this search that finished before the stop are saved as checkpoints
            kept = _search_from_checkpoints(root, index, rates, price_ranges[index - 1])
            if kept:
                raw_frame, cleaned_frame, stores = kept
                for source, target in ((raw_frame, audit), (cleaned_frame, frames)):
                    frame = source.copy()
                    frame["search_id"] = index
                    target.append(frame)
            verb = "Paused" if state == "paused" else "Stopped"
            reports.append({"search_id": index, "status": state,
                            "error": f"{verb} during this search; kept {len(kept[1]) if kept else 0} "
                                     f"listing(s) from {kept[2] if kept else 0} finished storefront(s)"})
            reports.extend({"search_id": later, "status": state, "error": "Not started"}
                           for later in range(index + 1, len(plans) + 1))
            break  # (no log() here: it raises again while the cancel flag exists)
        except Exception as exc:  # noqa: BLE001 - isolate failure and report
            reports.append({"search_id": index, "status": "failed", "error": str(exc)})
            log(f"Search {index} encountered failure: {exc}")

    final = write_run_outputs(root, frames, audit, reports)
    return root, final, reports


def write_run_outputs(root: Path, frames: list, audit: list, reports: list) -> pd.DataFrame:
    """Write the run's combined CSV / Excel / report files (also used for interim saves)."""
    cleaned = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    detailed = pd.concat(audit, ignore_index=True) if audit else pd.DataFrame()
    cleaned["review_status"] = "not_reviewed"
    cleaned["relevance_confidence_pct"] = None

    columns = ["search_id", *[col for col in FINAL_PRODUCT_FIELDS if col != "row_id"]]
    final = cleaned.reindex(columns=columns)

    write_csv(detailed, root / "raw_products.csv")
    write_csv(cleaned, root / "detailed_products.csv")
    write_csv(final, root / "final_products.csv")
    write_excel(final, root / "final_products.xlsx")
    write_json(root / "collection_report.json", {"searches": reports})
    return final


def _search_from_checkpoints(root: Path, index: int, rates: dict, price_range) -> tuple | None:
    """(raw, cleaned, storefronts) rebuilt from one search's per-storefront checkpoints."""
    checkpoints = sorted((Path(root) / f"search_{index:03}").glob(f"*/*/{CHECKPOINT_DIR}/*.csv"))
    parts = []
    for path in checkpoints:
        try:
            part = pd.read_csv(path, encoding="utf-8-sig") if path.stat().st_size else pd.DataFrame()
        except (OSError, pd.errors.EmptyDataError):
            continue
        if not part.empty:
            parts.append(part)
    if not parts:
        return None
    raw = fx.apply(pd.concat(parts, ignore_index=True), rates["rates"])
    try:
        cleaned, _ = apply_cleaning(raw.copy(), {**DEFAULT_CLEANING, **ANALYST_CLEANING})
    except (KeyError, ValueError, TypeError):
        cleaned = raw.copy()
    cleaned = _apply_price_range(cleaned, *price_range, log=lambda _m: None)
    return raw, cleaned, len(parts)


def recover_run(root: Path, reason: str = "Run stopped unexpectedly") -> dict:
    """Rebuild a run's result files from per-storefront checkpoints after a crash, sleep,
    shutdown or force stop. Every storefront that finished before the stop is kept."""
    root = Path(root)
    data = json.loads((root / "analyst_plan.json").read_text(encoding="utf-8"))
    price_ranges = _price_ranges(data)
    rates = fx.load_for_run(root) or fx.with_manual(fx.get_rates(root.parent), root.parent)
    fx.save_for_run(root, rates)
    frames, audit, reports = [], [], []
    for index in range(1, len(data.get("searches", [])) + 1):
        kept = _search_from_checkpoints(root, index, rates, price_ranges[index - 1])
        if not kept:
            reports.append({"search_id": index, "status": "failed",
                            "error": f"{reason} before any storefront of this search finished"})
            continue
        raw, cleaned, stores = kept
        for source, target in ((raw, audit), (cleaned, frames)):
            frame = source.copy()
            frame["search_id"] = index
            target.append(frame)
        reports.append({"search_id": index, "status": "partial",
                        "error": f"{reason}; recovered {len(cleaned)} listing(s) "
                                 f"from {stores} finished storefront(s)"})
    final = write_run_outputs(root, frames, audit, reports)
    return {"listings": len(final), "searches": reports}
