from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
from selenium.common.exceptions import WebDriverException

from price_lens.core.cleaning import apply_cleaning
from price_lens.core.export import (
    create_run_directory,
    save_run_artifacts,
    write_csv,
    write_json,
)

from .localization import collect_localized
from .registry import MARKETPLACE_REGISTRY, MarketplaceAdapter
from .schemas import ResearchPlan

DEFAULT_CLEANING = {
    "remove_sponsored": True,
    "remove_no_price": True,
    "remove_no_rating": False,
    "remove_duplicates": True,
    "remove_outliers": True,
    "outlier_pct": 99,
}


@dataclass(frozen=True)
class ResearchRunResult:
    run_dir: Path
    raw_products: pd.DataFrame
    cleaned_products: pd.DataFrame
    report: dict[str, Any]


def _combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    nonempty = [frame for frame in frames if not frame.empty]
    if nonempty:
        return pd.concat(nonempty, ignore_index=True, sort=False)
    if frames:
        return frames[0].copy()
    return pd.DataFrame()


def run_research(
    plan: ResearchPlan,
    *,
    adapters: Mapping[str, MarketplaceAdapter] | None = None,
    log=print,
) -> ResearchRunResult:
    registry = adapters or MARKETPLACE_REGISTRY
    run_dir = create_run_directory(plan.output_dir, "research")
    raw_frames: list[pd.DataFrame] = []
    cleaned_frames: list[pd.DataFrame] = []
    platform_reports: dict[str, Any] = {}
    cleaning_options = {**DEFAULT_CLEANING, **plan.cleaning}

    for platform in plan.platforms:
        adapter = registry[platform]
        platform_plan = plan.platform_plan(platform)
        platform_dir = run_dir / platform
        platform_dir.mkdir()
        platform_plan = replace(platform_plan, output_dir=platform_dir)
        log(f"\n=== {platform.upper()} ===")
        outcome = None
        collection_error: OSError | RuntimeError | WebDriverException | None = None
        collection_attempts = 0
        for collection_attempts in range(1, 3):
            try:
                outcome = collect_localized(adapter, platform_plan, log)
                collection_error = None
                break
            except (OSError, RuntimeError, WebDriverException) as exc:
                collection_error = exc
                if collection_attempts == 1:
                    log(
                        f"{platform} browser process failed before returning results; "
                        "restarting the marketplace once."
                    )
        if outcome is None:
            assert collection_error is not None
            exc = collection_error
            empty = pd.DataFrame()
            failed_report = {
                "platform": platform,
                "status": "failed",
                "error": f"{exc.__class__.__name__}: {exc}",
                "collection_attempts": collection_attempts,
                "cleaning": {
                    "options": cleaning_options,
                    "raw_rows": 0,
                    "cleaned_rows": 0,
                    "steps": ["Collection failed before products were returned"],
                },
            }
            save_run_artifacts(
                platform_dir,
                empty,
                empty,
                platform_plan.to_dict(),
                failed_report,
            )
            raw_frames.append(empty)
            cleaned_frames.append(empty)
            platform_reports[platform] = failed_report
            log(f"{platform} failed: {exc}")
            continue
        if outcome.raw_products.empty:
            cleaned = outcome.raw_products.copy()
            cleaning_log = ["No rows were available for cleaning"]
        else:
            cleaned, cleaning_log = apply_cleaning(
                outcome.raw_products.copy(), cleaning_options
            )
        platform_report = outcome.report.to_dict()
        platform_report["collection_attempts"] = collection_attempts
        platform_report["cleaning"] = {
            "options": cleaning_options,
            "raw_rows": len(outcome.raw_products),
            "cleaned_rows": len(cleaned),
            "steps": [line.replace("**", "") for line in cleaning_log],
        }
        save_run_artifacts(
            platform_dir,
            outcome.raw_products,
            cleaned,
            platform_plan.to_dict(),
            platform_report,
        )
        raw_frames.append(outcome.raw_products)
        cleaned_frames.append(cleaned)
        platform_reports[platform] = platform_report

    raw = _combine(raw_frames)
    cleaned = _combine(cleaned_frames)
    raw_path = run_dir / "combined_raw_products.csv"
    cleaned_path = run_dir / "combined_cleaned_products.csv"
    write_csv(raw, raw_path)
    write_csv(cleaned, cleaned_path)
    write_json(run_dir / "research_plan.json", plan.to_dict())

    failed_platforms = [
        platform
        for platform, report in platform_reports.items()
        if report.get("status") == "failed"
    ]
    target_met = plan.target_results is None or len(cleaned) >= plan.target_results
    status = (
        "failed"
        if len(failed_platforms) == len(platform_reports)
        else "partial"
        if failed_platforms or any(
            report.get("status") == "completed_with_errors"
            for report in platform_reports.values()
        )
        else "completed"
    )
    report = {
        "status": status,
        "research_question": plan.research_question,
        "platforms": list(plan.platforms),
        "raw_rows": len(raw),
        "cleaned_rows": len(cleaned),
        "target_results": plan.target_results,
        "target_met_before_ai_review": target_met,
        "failed_platforms": failed_platforms,
        "platform_reports": platform_reports,
        "files": {
            "combined_raw": str(raw_path),
            "combined_cleaned": str(cleaned_path),
        },
    }
    write_json(run_dir / "research_report.json", report)
    return ResearchRunResult(run_dir, raw, cleaned, report)
