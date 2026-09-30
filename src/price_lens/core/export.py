from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def create_run_directory(root: Path, platform: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidate = root / f"{platform}_{timestamp}"
    suffix = 1
    while candidate.exists():
        candidate = root / f"{platform}_{timestamp}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write Excel-friendly UTF-8 while preserving symbols such as €, £, and zł."""
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_excel(frame: pd.DataFrame, path: Path, *, sheet_name: str = "Products") -> None:
    """Write a compact, filterable workbook for analyst QC and forecasting."""
    excel_frame = frame.copy()
    if "scraped_at" in excel_frame.columns:
        parsed = pd.to_datetime(excel_frame["scraped_at"], errors="coerce", utc=True)
        excel_frame["scraped_at"] = parsed.dt.tz_localize(None)

    with pd.ExcelWriter(
        path,
        engine="xlsxwriter",
        datetime_format="yyyy-mm-dd hh:mm",
        engine_kwargs={"options": {"strings_to_urls": True, "strings_to_formulas": False}},
    ) as writer:
        excel_frame.to_excel(writer, sheet_name=sheet_name, index=False)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]
        worksheet.hide_gridlines(2)
        worksheet.freeze_panes(1, min(4, len(excel_frame.columns)))
        worksheet.set_default_row(18)

        formats = {
            "money": workbook.add_format({"num_format": "#,##0.00"}),
            "rating": workbook.add_format({"num_format": "0.0"}),
            "integer": workbook.add_format({"num_format": "#,##0"}),
            "percent": workbook.add_format({"num_format": "0.0"}),
            "date": workbook.add_format({"num_format": "yyyy-mm-dd hh:mm"}),
        }
        format_by_column = {
            "price_value": formats["money"],
            "price_usd": formats["money"],
            "shipping_price_value": formats["money"],
            "rating": formats["rating"],
            "review_count": formats["integer"],
            "relevance_confidence_pct": formats["percent"],
            "scraped_at": formats["date"],
        }
        width_caps = {
            "row_id": 22,
            "search_term": 32,
            "product_name": 48,
            "product_url": 45,
            "scraped_at": 19,
        }
        for column_number, column_name in enumerate(excel_frame.columns):
            values = excel_frame[column_name].dropna().astype(str).head(500)
            content_width = max(
                [len(str(column_name)) + 2, *(min(len(value) + 2, 48) for value in values)]
            )
            width = min(content_width, width_caps.get(column_name, 24))
            worksheet.set_column(
                column_number,
                column_number,
                max(width, 10),
                format_by_column.get(column_name),
            )

        if len(excel_frame.columns):
            last_row = max(len(excel_frame), 1)
            last_column = len(excel_frame.columns) - 1
            worksheet.add_table(
                0,
                0,
                last_row,
                last_column,
                {
                    "name": "FinalProducts",
                    "style": "Table Style Medium 2",
                    "columns": [{"header": column} for column in excel_frame.columns],
                },
            )
            if len(excel_frame):
                if "review_status" in excel_frame.columns:
                    status_column = excel_frame.columns.get_loc("review_status")
                    uncertain_format = workbook.add_format(
                        {"bg_color": "#FFF2CC", "font_color": "#7F6000"}
                    )
                    worksheet.conditional_format(
                        1,
                        status_column,
                        len(excel_frame),
                        status_column,
                        {
                            "type": "text",
                            "criteria": "containing",
                            "value": "uncertain",
                            "format": uncertain_format,
                        },
                    )
                if "relevance_confidence_pct" in excel_frame.columns:
                    confidence_column = excel_frame.columns.get_loc(
                        "relevance_confidence_pct"
                    )
                    worksheet.conditional_format(
                        1,
                        confidence_column,
                        len(excel_frame),
                        confidence_column,
                        {"type": "data_bar", "bar_color": "#5B9BD5"},
                    )


def save_run_artifacts(
    run_dir: Path,
    raw: pd.DataFrame,
    cleaned: pd.DataFrame,
    request: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Path]:
    paths = {
        "raw": run_dir / "raw_products.csv",
        "cleaned": run_dir / "cleaned_products.csv",
        "request": run_dir / "request.json",
        "report": run_dir / "scrape_report.json",
    }
    write_csv(raw, paths["raw"])
    write_csv(cleaned, paths["cleaned"])
    write_json(paths["request"], request)
    write_json(paths["report"], report)
    return paths
