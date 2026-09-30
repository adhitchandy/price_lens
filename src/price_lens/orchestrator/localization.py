from dataclasses import replace
from pathlib import Path

import pandas as pd
from selenium.common.exceptions import WebDriverException

from price_lens.core import network
from price_lens.core.results import ScrapeOutcome
from price_lens.core.schemas import ProductRule, ScrapeReport, utc_now


class RunPaused(BaseException):
    """Raised between two storefronts when the user asked to pause (see jobs.request_pause)."""


# Set by the background worker; checked before each storefront starts.
PAUSE_CHECK = lambda: False  # noqa: E731


def collect_localized(adapter, plan, log):
    """Localize before calling any adapter; legacy plans retain their original execution."""
    if not any(search.localized_queries for search in plan.searches):
        return adapter.collect(plan, log)
    report = ScrapeReport(platform=adapter.name, pages_requested=plan.pages)
    frames = []
    state = {"offline": False, "gave_up": False}
    for domain in plan.marketplaces:
        if PAUSE_CHECK():  # every storefront before this one is already saved
            raise RunPaused()
        searches, sources, languages, audiences = [], {}, {}, {}
        for search in plan.searches:
            localized = search.localized_queries.get(domain)
            term = localized["search_term"] if localized else search.search_term
            language = localized["language"] if localized else None
            rule = ProductRule(
                search.rule.product_type,
                tuple(localized["include"]), tuple(localized["exclude"]),
            ) if localized else search.rule
            searches.append(replace(search, search_term=term, rule=rule, localized_queries={}))
            sources[term] = search.search_term
            languages[term] = language
            audiences[term] = localized.get("audience") if localized else None
            report.events.append({
                "stage": "query_localization", "marketplace": domain,
                "source_search_term": search.search_term, "search_term": term,
                "query_language": language,
            })
        chosen_languages = {v for v in languages.values() if v}
        domain_plan = replace(
            plan, marketplaces=(domain,), searches=tuple(searches),
            languages={domain: next(iter(chosen_languages))} if len(chosen_languages) == 1 else {},
        )
        outcome, error = _collect_with_reconnect(adapter, domain_plan, domain, log, state)
        if outcome is None:
            report.failures.append({"marketplace": domain, "error": error})
            _mark_failed(plan, domain, error)
            continue
        frame = outcome.raw_products.copy()
        if not frame.empty:
            frame["source_search_term"] = frame["search_term"].map(sources)
            frame["query_language"] = frame["search_term"].map(languages)
            query_audience = frame["search_term"].map(audiences)
            if query_audience.notna().any():
                frame["audience"] = (frame["audience"].where(frame["audience"].notna(), query_audience)
                                     if "audience" in frame.columns else query_audience)
        _checkpoint(plan, domain, frame)
        frames.append(frame)
        for key in ("pages_attempted", "pages_succeeded", "listings_collected",
                    "unique_listings", "missing_price_count", "duplicate_count"):
            setattr(report, key, getattr(report, key) + getattr(outcome.report, key))
        report.events.extend(outcome.report.events)
        report.failures.extend(outcome.report.failures)
    report.status = (
        "failed" if not any(not frame.empty for frame in frames) else
        "completed_with_errors" if report.failures else "completed"
    )
    report.finished_at = utc_now()
    nonempty = [frame for frame in frames if not frame.empty]
    raw = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()
    return ScrapeOutcome(raw, report)


CHECKPOINT_DIR = "checkpoints"


def _checkpoint(plan, domain, frame):
    """Save each finished storefront immediately, so a crash or shutdown loses at most the
    storefront that was in progress (see history.recover_run)."""
    try:
        if not Path(plan.output_dir).is_dir():
            return  # only inside a real run folder
        folder = Path(plan.output_dir) / CHECKPOINT_DIR
        folder.mkdir(exist_ok=True)
        frame.to_csv(folder / f"{domain}.csv", index=False, encoding="utf-8-sig")
    except OSError:
        pass


def _mark_failed(plan, domain, error):
    """Remember that this storefront was tried and failed, so a resumed run does not treat it
    as "not started yet" (it is offered under "Retry" instead)."""
    try:
        if not Path(plan.output_dir).is_dir():
            return
        folder = Path(plan.output_dir) / CHECKPOINT_DIR
        folder.mkdir(exist_ok=True)
        (folder / f"{domain}.failed.txt").write_text(str(error or "failed"), encoding="utf-8")
    except OSError:
        pass


def _errors(outcome, error):
    texts = [error] if error else []
    if outcome is not None:
        texts += [str(f.get("error", "")) for f in outcome.report.failures]
    return texts


def _unique_rows(outcome):
    return 0 if outcome is None else len(outcome.raw_products)


def _collect_once(adapter, domain_plan, log):
    try:
        return adapter.collect(domain_plan, log), None
    except (RuntimeError, OSError, WebDriverException) as exc:
        return None, f"{exc.__class__.__name__}: {exc}"


def _collect_with_reconnect(adapter, domain_plan, domain, log, state):
    """Collect one storefront; if the connection dropped, wait for it and redo the storefront."""
    if state["gave_up"]:
        if not network.probe(network.storefront_hosts(domain)):
            return None, "Network: still offline — storefront skipped"
        state.update(gave_up=False, offline=False)
    elif state["offline"] and not network.probe(network.storefront_hosts(domain)):
        log(f"{domain}: connection still down — waiting before this storefront…")
        if not network.wait_for_connection(domain, log):
            state["gave_up"] = True
            return None, "Network: offline — storefront skipped after waiting"
        log(f"{domain}: connection is back")
        state["offline"] = False

    outcome, error = _collect_once(adapter, domain_plan, log)
    errors = _errors(outcome, error)
    if not network.mostly_network_errors(errors):
        return outcome, error
    if network.probe(network.storefront_hosts(domain)):
        return outcome, error  # the site is reachable: not a connection problem on our side
    state["offline"] = True
    log(f"⚠️ {domain}: internet connection lost — pausing and checking every "
        f"{network.POLL_SECONDS} s (up to {network.WAIT_SECONDS // 60} min)…")
    if not network.wait_for_connection(domain, log):
        state["gave_up"] = True
        log("Still offline — remaining storefronts will be skipped unless the connection returns.")
        if outcome is not None and not outcome.raw_products.empty:
            return outcome, error
        return None, "Network: offline — " + (errors[0] if errors else "connection lost")
    state["offline"] = False
    log(f"✅ {domain}: connection is back — collecting this storefront again")
    retry, retry_error = _collect_once(adapter, domain_plan, log)
    return (retry, retry_error) if _unique_rows(retry) >= _unique_rows(outcome) else (outcome, error)
