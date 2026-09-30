from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from selenium.common.exceptions import WebDriverException

from .agent.review import apply_review_decisions, prepare_review_batches, review_status
from .core.cleaning import apply_cleaning
from .core.doctor import run_doctor
from .core.export import create_run_directory, save_run_artifacts, write_csv, write_json
from .core.localization import language_options
from .core.validation import (
    RequestValidationError,
    load_amazon_plan,
    load_ebay_plan,
    load_mediamarkt_plan,
    load_zalando_plan,
)
from .marketplaces.amazon.constants import AMAZON_DOMAINS
from .marketplaces.amazon.scraper import AmazonScraper
from .marketplaces.ebay.constants import EBAY_MARKETPLACES
from .marketplaces.ebay.health import build_health_table, health_summary
from .marketplaces.ebay.scraper import EbayScraper
from .marketplaces.mediamarkt.constants import MEDIAMARKT_MARKETPLACES
from .marketplaces.mediamarkt.scraper import MediaMarktScraper
from .marketplaces.zalando.constants import ZALANDO_MARKETPLACES
from .marketplaces.zalando.health import (
    build_health_table as build_zalando_health_table,
)
from .marketplaces.zalando.health import health_summary as zalando_health_summary
from .marketplaces.zalando.scraper import ZalandoScraper
from .orchestrator.runner import run_research
from .orchestrator.validation import load_research_plan

DEFAULT_CLEANING = {
    "remove_sponsored": True,
    "remove_no_price": True,
    "remove_no_rating": False,
    "remove_duplicates": True,
    "remove_outliers": True,
    "outlier_pct": 99,
}


def _plain_log(message: str) -> None:
    print(message.replace("**", "").replace("`", ""), flush=True)


def _configure_console_encoding() -> None:
    """Prevent Windows cp1252 consoles from crashing on marketplace Unicode text."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def scrape_amazon(request_path: Path) -> int:
    try:
        plan = load_amazon_plan(request_path, set(AMAZON_DOMAINS))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2

    run_dir = create_run_directory(plan.output_dir, "amazon")
    print(f"Output directory: {run_dir.resolve()}")
    try:
        outcome = AmazonScraper().search_with_report(
            plan.search_config(),
            list(plan.marketplaces),
            headless=plan.headless,
            delay=plan.delay_seconds,
            postcodes=plan.postcodes,
            set_location=plan.set_location,
            pages=plan.pages,
            retries=plan.retries,
            log=_plain_log,
        )
    except (OSError, RuntimeError, WebDriverException) as exc:
        print(f"Scrape failed before completion: {exc}", file=sys.stderr)
        return 1

    cleaning_options = {**DEFAULT_CLEANING, **plan.cleaning}
    cleaned, cleaning_log = apply_cleaning(outcome.raw_products.copy(), cleaning_options)
    report = outcome.report.to_dict()
    report["cleaning"] = {
        "options": cleaning_options,
        "raw_rows": len(outcome.raw_products),
        "cleaned_rows": len(cleaned),
        "steps": [line.replace("**", "") for line in cleaning_log],
    }
    paths = save_run_artifacts(
        run_dir,
        outcome.raw_products,
        cleaned,
        plan.to_dict(),
        report,
    )
    print(f"Status: {outcome.report.status}")
    print(f"Raw listings: {len(outcome.raw_products):,}")
    print(f"Cleaned listings: {len(cleaned):,}")
    for label, path in paths.items():
        print(f"{label}: {path.resolve()}")
    return 0 if outcome.report.status != "failed" else 1


def validate_amazon(request_path: Path) -> int:
    try:
        plan = load_amazon_plan(request_path, set(AMAZON_DOMAINS))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2
    print(
        f"Valid Amazon request: {len(plan.searches)} search(es), "
        f"{len(plan.marketplaces)} marketplace(s), {plan.pages} page(s) each."
    )
    return 0


def scrape_ebay(request_path: Path) -> int:
    try:
        plan = load_ebay_plan(request_path, set(EBAY_MARKETPLACES))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2

    run_dir = create_run_directory(plan.output_dir, "ebay")
    print(f"Output directory: {run_dir.resolve()}")
    try:
        outcome = EbayScraper().search_with_report(
            plan.search_config(),
            list(plan.marketplaces),
            headless=plan.headless,
            delay=plan.delay_seconds,
            pages=plan.pages,
            retries=plan.retries,
            log=_plain_log,
        )
    except (OSError, RuntimeError, WebDriverException) as exc:
        print(f"Scrape failed before completion: {exc}", file=sys.stderr)
        return 1


    cleaning_options = {**DEFAULT_CLEANING, **plan.cleaning}
    cleaned, cleaning_log = apply_cleaning(outcome.raw_products.copy(), cleaning_options)
    report = outcome.report.to_dict()
    report["cleaning"] = {
        "options": cleaning_options,
        "raw_rows": len(outcome.raw_products),
        "cleaned_rows": len(cleaned),
        "steps": [line.replace("**", "") for line in cleaning_log],
    }
    paths = save_run_artifacts(
        run_dir,
        outcome.raw_products,
        cleaned,
        plan.to_dict(),
        report,
    )
    print(f"Status: {outcome.report.status}")
    print(f"Raw listings: {len(outcome.raw_products):,}")
    print(f"Cleaned listings: {len(cleaned):,}")
    for label, path in paths.items():
        print(f"{label}: {path.resolve()}")
    return 0 if outcome.report.status != "failed" else 1


def validate_ebay(request_path: Path) -> int:
    try:
        plan = load_ebay_plan(request_path, set(EBAY_MARKETPLACES))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2
    print(
        f"Valid eBay request: {len(plan.searches)} search(es), "
        f"{len(plan.marketplaces)} marketplace(s), {plan.pages} page(s) each."
    )
    return 0


def scrape_zalando(request_path: Path) -> int:
    try:
        plan = load_zalando_plan(request_path, set(ZALANDO_MARKETPLACES))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2

    run_dir = create_run_directory(plan.output_dir, "zalando")
    print(f"Output directory: {run_dir.resolve()}")
    try:
        outcome = ZalandoScraper().search_with_report(
            plan.search_config(),
            list(plan.marketplaces),
            headless=plan.headless,
            delay=plan.delay_seconds,
            pages=plan.pages,
            retries=plan.retries,
            enrich_details=plan.enrich_details,
            max_detail_products=plan.max_detail_products,
            log=_plain_log,
        )
    except (OSError, RuntimeError, WebDriverException) as exc:
        print(f"Scrape failed before completion: {exc}", file=sys.stderr)
        return 1

    cleaning_options = {**DEFAULT_CLEANING, **plan.cleaning}
    cleaned, cleaning_log = apply_cleaning(outcome.raw_products.copy(), cleaning_options)
    report = outcome.report.to_dict()
    report["cleaning"] = {
        "options": cleaning_options,
        "raw_rows": len(outcome.raw_products),
        "cleaned_rows": len(cleaned),
        "steps": [line.replace("**", "") for line in cleaning_log],
    }
    paths = save_run_artifacts(
        run_dir, outcome.raw_products, cleaned, plan.to_dict(), report
    )
    print(f"Status: {outcome.report.status}")
    print(f"Raw listings: {len(outcome.raw_products):,}")
    print(f"Cleaned listings: {len(cleaned):,}")
    for label, path in paths.items():
        print(f"{label}: {path.resolve()}")
    return 0 if outcome.report.status != "failed" else 1


def validate_zalando(request_path: Path) -> int:
    try:
        plan = load_zalando_plan(request_path, set(ZALANDO_MARKETPLACES))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2
    detail = (
        f", detail enrichment up to {plan.max_detail_products or 'all'} product(s)"
        if plan.enrich_details
        else ", search-card mode"
    )
    print(
        f"Valid Zalando request: {len(plan.searches)} search(es), "
        f"{len(plan.marketplaces)} marketplace(s), {plan.pages} page(s) each{detail}."
    )
    return 0


def scrape_mediamarkt(request_path: Path) -> int:
    try:
        plan = load_mediamarkt_plan(request_path, set(MEDIAMARKT_MARKETPLACES))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2

    run_dir = create_run_directory(plan.output_dir, "mediamarkt")
    print(f"Output directory: {run_dir.resolve()}")
    try:
        outcome = MediaMarktScraper().search_with_report(
            plan.search_config(),
            list(plan.marketplaces),
            diagnostics_dir=run_dir / "diagnostics",
            headless=plan.headless,
            delay=plan.delay_seconds,
            pages=plan.pages,
            retries=plan.retries,
            enrich_details=plan.enrich_details,
            max_detail_products=plan.max_detail_products,
            log=_plain_log,
        )
    except (OSError, RuntimeError, WebDriverException) as exc:
        print(f"Scrape failed before completion: {exc}", file=sys.stderr)
        return 1

    cleaning_options = {**DEFAULT_CLEANING, **plan.cleaning}
    cleaned, cleaning_log = apply_cleaning(outcome.raw_products.copy(), cleaning_options)
    report = outcome.report.to_dict()
    report["cleaning"] = {
        "options": cleaning_options,
        "raw_rows": len(outcome.raw_products),
        "cleaned_rows": len(cleaned),
        "steps": [line.replace("**", "") for line in cleaning_log],
    }
    paths = save_run_artifacts(
        run_dir, outcome.raw_products, cleaned, plan.to_dict(), report
    )
    print(f"Status: {outcome.report.status}")
    print(f"Raw listings: {len(outcome.raw_products):,}")
    print(f"Cleaned listings: {len(cleaned):,}")
    for label, path in paths.items():
        print(f"{label}: {path.resolve()}")
    return 0 if outcome.report.status != "failed" else 1


def validate_mediamarkt(request_path: Path) -> int:
    try:
        plan = load_mediamarkt_plan(request_path, set(MEDIAMARKT_MARKETPLACES))
    except RequestValidationError as exc:
        print(f"Invalid request: {exc}", file=sys.stderr)
        return 2
    detail = (
        f", detail enrichment up to {plan.max_detail_products or 'all'} product(s)"
        if plan.enrich_details
        else ", search-card mode"
    )
    print(
        f"Valid MediaMarkt request: {len(plan.searches)} search(es), "
        f"{len(plan.marketplaces)} marketplace(s), {plan.pages} page(s) each{detail}."
    )
    return 0


def check_mediamarkt_marketplaces(args) -> int:
    """Use a single plan, including localized queries, and report per-domain coverage."""
    try:
        plan = load_research_plan(args.request)
        if set(plan.platforms) != {"mediamarkt"}:
            raise RequestValidationError("Health plan must select only mediamarkt")
        if args.marketplaces:
            from dataclasses import replace
            if set(args.marketplaces) - set(plan.marketplaces["mediamarkt"]):
                raise RequestValidationError("Health subset must be present in the plan")
            plan = replace(plan, marketplaces={"mediamarkt": tuple(args.marketplaces)})
        result = run_research(plan, log=_plain_log)
    except (RequestValidationError, OSError, RuntimeError, WebDriverException) as exc:
        print(f"MediaMarkt check failed: {exc}", file=sys.stderr)
        return 1
    report = result.report["platform_reports"]["mediamarkt"]
    health = []
    for domain in plan.marketplaces["mediamarkt"]:
        products = result.raw_products
        subset = products[products["marketplace"] == domain] if not products.empty else products
        failures = [e for e in report.get("failures", []) if e.get("marketplace") == domain]
        events = [e for e in report.get("events", []) if e.get("marketplace") == domain]
        health.append({
            "marketplace": domain,
            "status": "unavailable" if any(e.get("status") == "unavailable" for e in failures)
            else "failed" if subset.empty else "partial" if failures else "passed",
            "unique_products": subset["product_id"].nunique() if not subset.empty else 0,
            "batches_succeeded": sum(e.get("status") == "succeeded" for e in events),
            "pagination_stops": sum(e.get("status") == "no_next_control" for e in events),
            "currency_codes": ",".join(sorted(subset["currency_code"].dropna().unique()))
                if not subset.empty else "",
            "error": " | ".join(e.get("error", "") for e in failures),
        })
    table = pd.DataFrame(health)
    path = result.run_dir / "marketplace_health.csv"
    write_csv(table, path)
    print(table.to_string(index=False))
    print(f"Health CSV: {path.resolve()}")
    return 0 if all(row["status"] == "passed" for row in health) else 1


def validate_research(request_path: Path) -> int:
    try:
        plan = load_research_plan(request_path)
    except RequestValidationError as exc:
        print(f"Invalid research plan: {exc}", file=sys.stderr)
        return 2
    platform_summary = ", ".join(
        f"{platform} ({len(domains)})"
        for platform, domains in plan.marketplaces.items()
    )
    print(
        f"Valid research plan: {len(plan.searches)} search(es); "
        f"platforms: {platform_summary}; {plan.pages} page(s) each."
    )
    return 0


def run_research_command(request_path: Path) -> int:
    try:
        plan = load_research_plan(request_path)
    except RequestValidationError as exc:
        print(f"Invalid research plan: {exc}", file=sys.stderr)
        return 2
    try:
        result = run_research(plan, log=_plain_log)
    except (OSError, RuntimeError, WebDriverException) as exc:
        print(f"Research run could not complete: {exc}", file=sys.stderr)
        return 1
    print(f"\nResearch output: {result.run_dir.resolve()}")
    print(f"Raw products: {len(result.raw_products):,}")
    print(f"Cleaned products: {len(result.cleaned_products):,}")
    if not result.cleaned_products.empty:
        review_dir = result.run_dir / "ai_review"
        manifest = prepare_review_batches(
            result.run_dir / "combined_cleaned_products.csv",
            review_dir,
            research_question=plan.research_question,
            instruction=plan.review.instruction,
            batch_size=plan.review.batch_size,
            target_results=plan.target_results,
            minimum_keep_confidence=plan.review.minimum_keep_confidence,
            allowed_brands=plan.review.allowed_brands,
        )
        print(
            f"AI review: {len(manifest['batches'])} batch(es) in "
            f"{review_dir.resolve()}"
        )
    return 1 if result.report["status"] == "failed" else 0


def prepare_ai_review(args: argparse.Namespace) -> int:
    try:
        manifest = prepare_review_batches(
            args.source,
            args.output_dir,
            research_question=args.research_question,
            instruction=args.instruction,
            batch_size=args.batch_size,
            target_results=args.target_results,
            minimum_keep_confidence=args.minimum_keep_confidence,
            allowed_brands=tuple(args.allowed_brand or ()),
        )
    except (OSError, RequestValidationError) as exc:
        print(f"Could not prepare AI review: {exc}", file=sys.stderr)
        return 2
    print(
        f"Prepared {len(manifest['batches'])} batch(es) for "
        f"{manifest['row_count']} product(s): {args.output_dir.resolve()}"
    )
    return 0


def apply_ai_review(review_dir: Path) -> int:
    try:
        report = apply_review_decisions(review_dir)
    except (OSError, KeyError, json.JSONDecodeError, RequestValidationError) as exc:
        print(f"Could not apply AI review: {exc}", file=sys.stderr)
        return 2
    print(
        f"AI review complete: {report['accepted']} accepted, "
        f"{report['uncertain']} uncertain candidate(s), "
        f"{report['excluded']} excluded."
    )
    print(f"Final CSV: {Path(report['files']['final']).resolve()}")
    print(f"Final Excel: {Path(report['files']['final_excel']).resolve()}")
    print(f"Detailed audit: {Path(report['files']['detailed_audit']).resolve()}")
    return 0


def review_status_command(review_dir: Path) -> int:
    try:
        status = review_status(review_dir)
    except (OSError, KeyError, json.JSONDecodeError, RequestValidationError) as exc:
        print(f"Could not inspect AI review: {exc}", file=sys.stderr)
        return 2
    print(
        f"AI review batches: {len(status['completed_batches'])}/"
        f"{status['total_batches']} complete"
    )
    if status["pending_batches"]:
        print("Pending: " + ", ".join(status["pending_batches"]))
    return 0 if status["complete"] else 1


def doctor_command(output_dir: Path) -> int:
    healthy, checks = run_doctor(output_dir)
    width = max(len(name) for name, _, _ in checks)
    for name, status, detail in checks:
        print(f"{name:<{width}}  {status.upper():6}  {detail}")
    return 0 if healthy else 1


def check_ebay_marketplaces(args: argparse.Namespace) -> int:
    marketplaces = args.marketplaces or list(EBAY_MARKETPLACES)
    search_config = {
        args.query: [
            {
                "type": "Marketplace Health Check",
                "include": [],
                "exclude": [],
            }
        ]
    }
    run_dir = create_run_directory(args.output_dir, "ebay_marketplace_check")
    print(f"Checking {len(marketplaces)} configured eBay marketplaces")
    print(f"Output directory: {run_dir.resolve()}")
    try:
        outcome = EbayScraper().search_with_report(
            search_config,
            marketplaces,
            headless=not args.visible,
            delay=(args.delay_min, args.delay_max),
            pages=1,
            retries=args.retries,
            log=_plain_log,
        )
    except (OSError, RuntimeError, WebDriverException) as exc:
        print(f"Marketplace check could not complete: {exc}", file=sys.stderr)
        return 1

    table = build_health_table(outcome, marketplaces)
    summary = health_summary(table)
    table_path = run_dir / "marketplace_health.csv"
    report_path = run_dir / "marketplace_health.json"
    write_csv(table, table_path)
    write_json(
        report_path,
        {
            **summary,
            "query": args.query,
            "collection_report": outcome.report.to_dict(),
        },
    )
    print(table.to_string(index=False))
    print(
        f"Summary: {summary['passed']} passed, {summary['warnings']} warning(s), "
        f"{summary['failed']} failed, {summary['not_available']} not available"
    )
    print(f"CSV: {table_path.resolve()}")
    print(f"JSON: {report_path.resolve()}")
    return 0 if summary["all_passed"] else 1


def check_zalando_marketplaces(args: argparse.Namespace) -> int:
    marketplaces = args.marketplaces or list(ZALANDO_MARKETPLACES)
    audiences = args.audiences or [args.audience]
    if audiences == ["all"]:
        audiences = ["men", "women", "kids"]
    search_config = {
        args.query: [
            {
                "type": "Marketplace Health Check",
                "include": [],
                "exclude": [],
                "audiences": audiences,
            }
        ]
    }
    run_dir = create_run_directory(args.output_dir, "zalando_marketplace_check")
    print(
        f"Checking {len(marketplaces)} Zalando marketplaces × "
        f"{len(audiences)} audience(s) = {len(marketplaces) * len(audiences)} checks"
    )
    print(f"Output directory: {run_dir.resolve()}")
    try:
        outcome = ZalandoScraper().search_with_report(
            search_config,
            marketplaces,
            headless=not args.visible,
            delay=(args.delay_min, args.delay_max),
            pages=1,
            retries=args.retries,
            log=_plain_log,
        )
    except (OSError, RuntimeError, WebDriverException) as exc:
        print(f"Marketplace check could not complete: {exc}", file=sys.stderr)
        return 1
    table = build_zalando_health_table(outcome, marketplaces, audiences)
    summary = zalando_health_summary(table)
    table_path = run_dir / "marketplace_health.csv"
    report_path = run_dir / "marketplace_health.json"
    write_csv(table, table_path)
    write_json(
        report_path,
        {
            **summary,
            "query": args.query,
            "audiences": audiences,
            "collection_report": outcome.report.to_dict(),
        },
    )
    print(table.to_string(index=False))
    print(
        f"Summary: {summary['passed']} passed, {summary['warnings']} warning(s), "
        f"{summary['failed']} failed"
    )
    print(f"CSV: {table_path.resolve()}")
    print(f"JSON: {report_path.resolve()}")
    return 0 if summary["all_passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="price_lens")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("marketplace-locales", help="Print query language planning defaults")
    scrape = commands.add_parser("scrape-amazon", help="Run an Amazon request JSON file")
    scrape.add_argument("request", type=Path)
    validate = commands.add_parser("validate-amazon", help="Validate without opening Firefox")
    validate.add_argument("request", type=Path)
    ebay_scrape = commands.add_parser("scrape-ebay", help="Run an eBay request JSON file")
    ebay_scrape.add_argument("request", type=Path)
    ebay_validate = commands.add_parser(
        "validate-ebay", help="Validate an eBay request without opening Firefox"
    )
    ebay_validate.add_argument("request", type=Path)
    ebay_check = commands.add_parser(
        "check-ebay-marketplaces",
        help="Test every configured eBay domain and write a health matrix",
    )
    ebay_check.add_argument("--query", default="digital camera")
    ebay_check.add_argument(
        "--marketplaces",
        nargs="+",
        choices=list(EBAY_MARKETPLACES),
        help="Optional subset, for example: --marketplaces ebay.de ebay.fr",
    )
    ebay_check.add_argument("--output-dir", type=Path, default=Path("output"))
    ebay_check.add_argument("--visible", action="store_true")
    ebay_check.add_argument("--retries", type=int, choices=range(4), default=1)
    ebay_check.add_argument("--delay-min", type=float, default=2.5)
    ebay_check.add_argument("--delay-max", type=float, default=4.5)
    zalando_scrape = commands.add_parser(
        "scrape-zalando", help="Run a Zalando request JSON file"
    )
    zalando_scrape.add_argument("request", type=Path)
    zalando_validate = commands.add_parser(
        "validate-zalando", help="Validate a Zalando request without opening Firefox"
    )
    zalando_validate.add_argument("request", type=Path)
    zalando_check = commands.add_parser(
        "check-zalando-marketplaces",
        help="Test every configured Zalando domain and write a health matrix",
    )
    zalando_check.add_argument("--query", default="running shoes")
    audience_options = zalando_check.add_mutually_exclusive_group()
    audience_options.add_argument(
        "--audience", choices=("men", "women", "kids", "all"), default="men"
    )
    audience_options.add_argument(
        "--audiences", nargs="+", choices=("men", "women", "kids")
    )
    zalando_check.add_argument(
        "--marketplaces", nargs="+", choices=list(ZALANDO_MARKETPLACES)
    )
    zalando_check.add_argument("--output-dir", type=Path, default=Path("output"))
    zalando_check.add_argument("--visible", action="store_true")
    zalando_check.add_argument("--retries", type=int, choices=range(4), default=1)
    zalando_check.add_argument("--delay-min", type=float, default=2.5)
    zalando_check.add_argument("--delay-max", type=float, default=4.5)
    mediamarkt_scrape = commands.add_parser(
        "scrape-mediamarkt", help="Run a MediaMarkt request JSON file"
    )
    mediamarkt_scrape.add_argument("request", type=Path)
    mediamarkt_validate = commands.add_parser(
        "validate-mediamarkt", help="Validate a MediaMarkt request without opening Firefox"
    )
    mediamarkt_validate.add_argument("request", type=Path)
    mediamarkt_check = commands.add_parser(
        "check-mediamarkt-marketplaces", help="Run a localized MediaMarkt plan with health report"
    )
    mediamarkt_check.add_argument("request", type=Path)
    mediamarkt_check.add_argument("--marketplaces", nargs="+", choices=list(MEDIAMARKT_MARKETPLACES))
    research_validate = commands.add_parser(
        "validate-research", help="Validate a unified local-agent research plan"
    )
    research_validate.add_argument("request", type=Path)
    research_run = commands.add_parser(
        "run-research", help="Run configured marketplaces from one research plan"
    )
    research_run.add_argument("request", type=Path)
    review_prepare = commands.add_parser(
        "prepare-ai-review", help="Split a product CSV into local agent review batches"
    )
    review_prepare.add_argument("source", type=Path)
    review_prepare.add_argument("--output-dir", type=Path, required=True)
    review_prepare.add_argument("--research-question", required=True)
    review_prepare.add_argument(
        "--instruction",
        default="Keep products that directly satisfy the research question.",
    )
    review_prepare.add_argument("--batch-size", type=int, default=30)
    review_prepare.add_argument("--target-results", type=int)
    review_prepare.add_argument("--minimum-keep-confidence", type=float, default=0.8)
    review_prepare.add_argument("--allowed-brand", action="append")
    review_apply = commands.add_parser(
        "apply-ai-review", help="Validate and merge local agent relevance decisions"
    )
    review_apply.add_argument("review_dir", type=Path)
    review_check = commands.add_parser(
        "review-status", help="Show completed and pending local AI review batches"
    )
    review_check.add_argument("review_dir", type=Path)
    doctor = commands.add_parser("doctor", help="Check the local scraper environment")
    doctor.add_argument("--output-dir", type=Path, default=Path("output"))
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    args = build_parser().parse_args(argv)
    if args.command == "marketplace-locales":
        catalog = {
            platform: {
                domain: {"country": country, "language_options": language_options(domain, country)}
                for domain, country in domains.items()
            }
            for platform, domains in {
                "amazon": AMAZON_DOMAINS, "ebay": EBAY_MARKETPLACES,
                "zalando": ZALANDO_MARKETPLACES, "mediamarkt": MEDIAMARKT_MARKETPLACES,
            }.items()
        }
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
        return 0
    if args.command == "scrape-amazon":
        return scrape_amazon(args.request)
    if args.command == "validate-amazon":
        return validate_amazon(args.request)
    if args.command == "scrape-ebay":
        return scrape_ebay(args.request)
    if args.command == "check-ebay-marketplaces":
        if args.delay_min < 0.5 or args.delay_max < args.delay_min:
            print("Invalid delays: require 0.5 <= delay-min <= delay-max", file=sys.stderr)
            return 2
        return check_ebay_marketplaces(args)
    if args.command == "validate-ebay":
        return validate_ebay(args.request)
    if args.command == "scrape-zalando":
        return scrape_zalando(args.request)
    if args.command == "validate-zalando":
        return validate_zalando(args.request)
    if args.command == "scrape-mediamarkt":
        return scrape_mediamarkt(args.request)
    if args.command == "validate-mediamarkt":
        return validate_mediamarkt(args.request)
    if args.command == "check-mediamarkt-marketplaces":
        return check_mediamarkt_marketplaces(args)
    if args.command == "validate-research":
        return validate_research(args.request)
    if args.command == "run-research":
        return run_research_command(args.request)
    if args.command == "prepare-ai-review":
        return prepare_ai_review(args)
    if args.command == "apply-ai-review":
        return apply_ai_review(args.review_dir)
    if args.command == "review-status":
        return review_status_command(args.review_dir)
    if args.command == "doctor":
        return doctor_command(args.output_dir)
    if args.command == "check-zalando-marketplaces" and (
        args.delay_min < 0.5 or args.delay_max < args.delay_min
    ):
        print("Invalid delays: require 0.5 <= delay-min <= delay-max", file=sys.stderr)
        return 2
    return check_zalando_marketplaces(args)


if __name__ == "__main__":
    raise SystemExit(main())
