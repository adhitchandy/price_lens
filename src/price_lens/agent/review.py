from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from price_lens.core.export import write_csv, write_excel, write_json
from price_lens.core.validation import RequestValidationError

REVIEW_FIELDS = (
    "row_id",
    "platform",
    "marketplace",
    "search_term",
    "source_search_term",
    "query_language",
    "product_name",
    "brand",
    "product_type",
    "price_value",
    "currency_code",
    "condition",
    "seller",
    "audience",
    "color",
    "availability",
    "product_url",
)

# Compact analytical output. All original fields, AI explanations, and quality-gate
# diagnostics remain available in ai_classified_products.csv.
FINAL_PRODUCT_FIELDS = (
    "row_id",
    "platform",
    "marketplace",
    "search_term",
    "product_id",
    "brand",
    "product_name",
    "product_type",
    "review_category",
    "audience",
    "condition",
    "color",
    "price_value",
    "currency_code",
    "price_usd",
    "shipping_price_value",
    "rating",
    "review_count",
    "seller",
    "buying_format",
    "availability",
    "detail_enriched",
    "product_url",
    "scraped_at",
    "review_status",
    "relevance_confidence_pct",
)


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _row_id(row: pd.Series, index: int) -> str:
    identity = "|".join(
        str(row.get(field, "") or "")
        for field in ("platform", "marketplace", "product_id", "product_url", "product_name")
    )
    digest = hashlib.sha256(f"{identity}|{index}".encode()).hexdigest()[:16]
    return f"product_{digest}"


def prepare_review_batches(
    source_csv: Path,
    output_dir: Path,
    *,
    research_question: str,
    instruction: str,
    batch_size: int = 30,
    target_results: int | None = None,
    minimum_keep_confidence: float = 0.8,
    allowed_brands: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not source_csv.exists():
        raise RequestValidationError(f"Input CSV not found: {source_csv}")
    if not 1 <= batch_size <= 500:
        raise RequestValidationError("Batch size must be between 1 and 500")
    if not 0 <= minimum_keep_confidence <= 1:
        raise RequestValidationError("Minimum keep confidence must be between 0 and 1")
    frame = pd.read_csv(source_csv)
    if "product_name" not in frame.columns:
        raise RequestValidationError("Input CSV must contain 'product_name'")
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir = output_dir / "decisions"
    decisions_dir.mkdir(exist_ok=True)
    frame = frame.copy()
    frame["row_id"] = [_row_id(row, index) for index, (_, row) in enumerate(frame.iterrows())]
    source_with_ids = output_dir / "review_source.csv"
    write_csv(frame, source_with_ids)

    quality_gates = {
        "minimum_keep_confidence": minimum_keep_confidence,
        "allowed_brands": list(allowed_brands),
        "low_confidence_policy": "retain_as_uncertain_candidate",
        "missing_brand_evidence_policy": "retain_as_uncertain_candidate",
        "conflicting_brand_policy": "exclude",
    }

    batches: list[dict[str, Any]] = []
    for batch_number, start in enumerate(range(0, len(frame), batch_size), start=1):
        batch_frame = frame.iloc[start : start + batch_size]
        batch_name = f"batch_{batch_number:03d}"
        width = max(3, len(str(len(frame))))
        products = [
            {
                # Short, stable reference used in compact prompts ("p001"); row_id stays the key.
                "ref": f"p{start + offset + 1:0{width}d}",
                **{
                    field: _clean_value(row.get(field))
                    for field in REVIEW_FIELDS
                    if field in row.index
                },
            }
            for offset, (_, row) in enumerate(batch_frame.iterrows())
        ]
        batch_path = output_dir / f"{batch_name}.json"
        decision_path = (decisions_dir / f"{batch_name}.decisions.json").resolve()
        write_json(
            batch_path,
            {
                "research_question": research_question,
                "instruction": instruction,
                "quality_gates": quality_gates,
                "output_file": str(decision_path),
                "decision_schema": {
                    "row_id": "copy exactly from the product",
                    "keep": "boolean",
                    "category": "short category label",
                    "confidence": "number from 0 to 1",
                    "reason": "concise evidence-based explanation",
                },
                "products": products,
            },
        )
        batches.append(
            {
                "batch": batch_name,
                "input": str(batch_path.resolve()),
                "decisions": str(decision_path),
                "rows": len(products),
            }
        )

    manifest = {
        "research_question": research_question,
        "instruction": instruction,
        "original_source": str(source_csv.resolve()),
        "review_source": str(source_with_ids.resolve()),
        "row_count": len(frame),
        "batch_size": batch_size,
        "target_results": target_results,
        "quality_gates": quality_gates,
        "batches": batches,
    }
    write_json(output_dir / "manifest.json", manifest)
    (output_dir / "INSTRUCTIONS.md").write_text(
        "# AI relevance review\n\n"
        "Read each `batch_*.json` file and write only the requested JSON decisions "
        "to its `output_file`. Copy every `row_id` exactly once. Do not change "
        "`review_source.csv` or `manifest.json`. Use only supplied listing evidence. "
        "Review each product semantically; do not generate decisions with keyword, regex, "
        "shell, or Python classification scripts. Structured fields are stronger evidence "
        "than the search term, but a missing field is uncertainty rather than proof of "
        "irrelevance. Use high-confidence exclusion only when supplied evidence explicitly "
        "contradicts the research request. Do not invent a brand whitelist for a generic "
        "product request. After all batches are complete, run "
        "`price_lens apply-ai-review <this-directory>`.\n",
        encoding="utf-8",
    )
    return manifest


def load_manifest(review_dir: Path) -> dict[str, Any]:
    """manifest.json with every file path pointed at this review folder.

    manifest.json stores absolute paths. After the project folder is moved, renamed or copied
    (for example to a new OneDrive folder) those would point at the old place, so the review
    would fail or, worse, read and write the old copy. The files always live in the review
    folder itself, so the paths are rebuilt from it."""
    review_dir = Path(review_dir)
    manifest_path = review_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RequestValidationError(f"Review manifest not found: {manifest_path}") from exc
    manifest["review_source"] = str(review_dir / "review_source.csv")
    for batch in manifest.get("batches", []):
        batch["input"] = str(review_dir / f"{batch['batch']}.json")
        batch["decisions"] = str(review_dir / "decisions" / f"{batch['batch']}.decisions.json")
    return manifest


OUTDATED_FILE = "OUTDATED.json"
RESULT_FILES = ("ai_review_report.json", "final_products.csv", "final_products.xlsx",
                "ai_classified_products.csv", "coverage_report.json")


def _identity(row: pd.Series) -> str:
    return "|".join(str(row.get(f, "") or "") for f in
                    ("platform", "marketplace", "product_id", "product_url", "product_name"))


def mark_review_outdated(review_dir: Path, reason: str, added: int) -> None:
    """Called when new listings join a run that already has a review (e.g. after a retry)."""
    if not (review_dir / "manifest.json").exists():
        return
    note = json.loads((review_dir / OUTDATED_FILE).read_text(encoding="utf-8")) \
        if (review_dir / OUTDATED_FILE).exists() else {"reasons": [], "added": 0}
    note["reasons"].append(reason)
    note["added"] += added
    write_json(review_dir / OUTDATED_FILE, note)


def review_outdated(review_dir: Path) -> dict[str, Any] | None:
    path = review_dir / OUTDATED_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def extend_review_batches(review_dir: Path, source_csv: Path, batch_size: int = 150) -> dict[str, Any]:
    """Add batches for listings not yet in the review (existing decisions are kept).

    The applied results are removed so the next "Apply review" covers old + new listings."""
    manifest = load_manifest(review_dir)
    existing = pd.read_csv(review_dir / "review_source.csv")
    known = {_identity(row) for _, row in existing.iterrows()}
    current = pd.read_csv(source_csv)
    new = current[[_identity(row) not in known for _, row in current.iterrows()]].copy()
    if not new.empty:
        offset = len(existing)
        new["row_id"] = [_row_id(row, offset + i) for i, (_, row) in enumerate(new.iterrows())]
        combined = pd.concat([existing, new], ignore_index=True)
        write_csv(combined, review_dir / "review_source.csv")
        template = json.loads(Path(manifest["batches"][0]["input"]).read_text(encoding="utf-8")) \
            if manifest["batches"] and Path(manifest["batches"][0]["input"]).exists() else {}
        width = max(3, len(str(len(combined))))
        decisions_dir = review_dir / "decisions"
        decisions_dir.mkdir(exist_ok=True)
        number = len(manifest["batches"])
        for start in range(0, len(new), batch_size):
            number += 1
            name = f"batch_{number:03d}_new"
            chunk = new.iloc[start:start + batch_size]
            products = [{"ref": f"p{offset + start + i + 1:0{width}d}",
                         **{f: _clean_value(row.get(f)) for f in REVIEW_FIELDS if f in row.index}}
                        for i, (_, row) in enumerate(chunk.iterrows())]
            decision_path = (decisions_dir / f"{name}.decisions.json").resolve()
            batch_path = review_dir / f"{name}.json"
            write_json(batch_path, {
                "research_question": manifest["research_question"],
                "instruction": manifest["instruction"],
                "quality_gates": manifest.get("quality_gates", {}),
                "output_file": str(decision_path),
                "decision_schema": template.get("decision_schema", {}),
                "products": products,
            })
            manifest["batches"].append({"batch": name, "input": str(batch_path.resolve()),
                                        "decisions": str(decision_path), "rows": len(products)})
        manifest["row_count"] = len(combined)
        write_json(review_dir / "manifest.json", manifest)
    for name in RESULT_FILES:
        (review_dir / name).unlink(missing_ok=True)
    (review_dir / OUTDATED_FILE).unlink(missing_ok=True)
    return {"added": len(new)}


def review_status(review_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(review_dir)
    completed: list[str] = []
    pending: list[str] = []
    for batch in manifest["batches"]:
        decision_path = Path(batch["decisions"])
        (completed if decision_path.exists() else pending).append(batch["batch"])
    return {
        "total_batches": len(manifest["batches"]),
        "completed_batches": completed,
        "pending_batches": pending,
        "complete": not pending,
    }


def _validate_decision(item: Any, expected_ids: set[str], source: Path) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RequestValidationError(f"Every decision in {source} must be an object")
    row_id = item.get("row_id")
    if row_id not in expected_ids:
        raise RequestValidationError(f"Unknown row_id in {source}: {row_id}")
    if not isinstance(item.get("keep"), bool):
        raise RequestValidationError(f"Decision {row_id} in {source} requires boolean 'keep'")
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise RequestValidationError(
            f"Decision {row_id} in {source} requires confidence from 0 to 1"
        )
    category = str(item.get("category", "")).strip()
    reason = str(item.get("reason", "")).strip()
    if not category or not reason:
        raise RequestValidationError(
            f"Decision {row_id} in {source} requires category and reason"
        )
    return {
        "row_id": row_id,
        "ai_keep": item["keep"],
        "ai_category": category,
        "ai_confidence": float(confidence),
        "ai_reason": reason,
    }


def _brand_evidence_status(row: pd.Series, allowed_brands: tuple[str, ...]) -> tuple[str, str]:
    if not allowed_brands:
        return "not_required", "No allowed-brand gate configured."

    def contains_allowed(value: str) -> bool:
        lowered = value.casefold()
        return any(
            re.search(rf"(?<!\w){re.escape(brand.casefold())}(?!\w)", lowered)
            for brand in allowed_brands
        )

    brand_value = str(row.get("brand") or "").strip()
    if brand_value and brand_value.casefold() != "nan":
        if contains_allowed(brand_value):
            return "verified", f"Brand metadata matches: {brand_value}"
        return "conflict", f"Brand metadata is outside allowed brands: {brand_value}"
    title = str(row.get("product_name") or "")
    if contains_allowed(title):
        return "verified", "Allowed brand is explicit in the product title."
    return "unverified", "No allowed brand is explicit in brand metadata or title."


def _status_for(row: pd.Series, minimum_confidence: float) -> str:
    # Confidence describes confidence in the AI decision. Every low-confidence
    # decision remains visible in the final candidate file, including tentative
    # exclusions; this prevents uncertain rows from being silently discarded.
    if row["ai_confidence"] < minimum_confidence:
        return "uncertain"
    if row["brand_evidence_status"] == "conflict":
        return "excluded"
    if row["brand_evidence_status"] == "unverified":
        return "uncertain"
    return "accepted" if row["ai_keep"] else "excluded"


OVERRIDES_FILE = "overrides.json"


def load_overrides(review_dir: Path) -> dict[str, bool]:
    """Decisions the analyst changed by hand: {row_id: keep}."""
    try:
        data = json.loads((Path(review_dir) / OVERRIDES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): bool(v) for k, v in data.items()} if isinstance(data, dict) else {}


def set_override(review_dir: Path, row_id: str, keep: bool | None) -> dict[str, bool]:
    """Keep or leave out one listing regardless of the AI (None = back to the AI's call)."""
    review_dir = Path(review_dir)
    manifest = load_manifest(review_dir)
    known = set(pd.read_csv(manifest["review_source"], usecols=["row_id"])["row_id"].astype(str))
    if str(row_id) not in known:
        raise RequestValidationError(f"Unknown listing: {row_id}")
    overrides = load_overrides(review_dir)
    if keep is None:
        overrides.pop(str(row_id), None)
    else:
        overrides[str(row_id)] = bool(keep)
    write_json(review_dir / OVERRIDES_FILE, overrides)
    return overrides


def decision_table(review_dir: Path) -> pd.DataFrame:
    """Every listing with the AI decision so far (status 'pending' when not reviewed yet),
    the status it will get when applied, and any change made by hand."""
    review_dir = Path(review_dir)
    manifest = load_manifest(review_dir)
    source = pd.read_csv(manifest["review_source"])
    source["row_id"] = source["row_id"].astype(str)
    expected = set(source["row_id"])
    decisions = []
    for batch in manifest["batches"]:
        path = Path(batch["decisions"])
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for item in payload.get("decisions") or []:
                decisions.append(_validate_decision(item, expected, path))
        except (ValueError, RequestValidationError):
            continue
    frame = source.merge(pd.DataFrame(decisions, columns=[
        "row_id", "ai_keep", "ai_category", "ai_confidence", "ai_reason"]).drop_duplicates("row_id"),
        on="row_id", how="left")
    gates = manifest.get("quality_gates", {})
    minimum = float(gates.get("minimum_keep_confidence", 0.8))
    allowed = tuple(str(v).strip().lower() for v in gates.get("allowed_brands", []))
    checks = [_brand_evidence_status(row, allowed) for _, row in frame.iterrows()]
    frame["brand_evidence_status"] = [status for status, _ in checks]
    frame["review_status"] = [
        "pending" if pd.isna(row["ai_keep"]) else _status_for(row, minimum)
        for _, row in frame.iterrows()]
    overrides = load_overrides(review_dir)
    frame["review_override"] = frame["row_id"].map(
        lambda rid: ("keep" if overrides[rid] else "drop") if rid in overrides else "")
    for rid, keep in overrides.items():
        frame.loc[frame["row_id"] == rid, "review_status"] = "accepted" if keep else "excluded"
    return frame


def apply_review_decisions(review_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(review_dir)
    source = pd.read_csv(manifest["review_source"])
    expected_ids = set(source["row_id"].astype(str))
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for batch in manifest["batches"]:
        decision_path = Path(batch["decisions"])
        try:
            payload = json.loads(decision_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RequestValidationError(f"Missing decision file: {decision_path}") from exc
        raw_decisions = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(raw_decisions, list):
            raise RequestValidationError(
                f"Decision file must contain a 'decisions' list: {decision_path}"
            )
        for item in raw_decisions:
            decision = _validate_decision(item, expected_ids, decision_path)
            if decision["row_id"] in seen:
                raise RequestValidationError(
                    f"Duplicate decision for {decision['row_id']} in {decision_path}"
                )
            seen.add(decision["row_id"])
            decisions.append(decision)
    missing = sorted(expected_ids - seen)
    if missing:
        raise RequestValidationError(
            f"AI review is incomplete: {len(missing)} product decision(s) are missing"
        )
    decision_frame = pd.DataFrame(decisions)
    classified = source.merge(decision_frame, on="row_id", how="left", validate="one_to_one")
    gates = manifest.get("quality_gates", {})
    minimum_confidence = float(gates.get("minimum_keep_confidence", 0.8))
    allowed_brands = tuple(str(value).strip().lower() for value in gates.get("allowed_brands", []))
    brand_checks = [
        _brand_evidence_status(row, allowed_brands)
        for _, row in classified.iterrows()
    ]
    classified["brand_evidence_status"] = [status for status, _ in brand_checks]
    classified["quality_gate_reason"] = [reason for _, reason in brand_checks]

    classified["review_status"] = classified.apply(
        lambda row: _status_for(row, minimum_confidence), axis=1)
    overrides = load_overrides(review_dir)
    classified["review_override"] = classified["row_id"].astype(str).map(
        lambda rid: ("kept by you" if overrides[rid] else "left out by you") if rid in overrides else "")
    for rid, keep in overrides.items():
        classified.loc[classified["row_id"].astype(str) == rid, "review_status"] = (
            "accepted" if keep else "excluded")
    classified["relevance_confidence_pct"] = classified.apply(
        lambda row: round(
            100 * (row["ai_confidence"] if row["ai_keep"] else 1 - row["ai_confidence"]),
            1,
        ),
        axis=1,
    )
    classified["review_category"] = classified["ai_category"]
    candidates = classified[classified["review_status"] != "excluded"].reset_index(drop=True)
    accepted = candidates[candidates["review_status"] == "accepted"].reset_index(drop=True)
    uncertain = candidates[candidates["review_status"] == "uncertain"].reset_index(drop=True)
    excluded = classified[classified["review_status"] == "excluded"].reset_index(drop=True)
    final_columns = (["search_id"] if "search_id" in candidates.columns else []) + [
        field for field in FINAL_PRODUCT_FIELDS if field in candidates.columns
    ]
    final_products = candidates.loc[:, final_columns]
    classified_path = review_dir / "ai_classified_products.csv"
    final_path = review_dir / "final_products.csv"
    final_excel_path = review_dir / "final_products.xlsx"
    write_csv(classified, classified_path)
    write_csv(final_products, final_path)
    write_excel(final_products, final_excel_path)
    by_platform = (
        candidates["platform"].fillna("unknown").value_counts().to_dict()
        if "platform" in candidates.columns
        else {}
    )
    by_marketplace = (
        candidates["marketplace"].fillna("unknown").value_counts().to_dict()
        if "marketplace" in candidates.columns
        else {}
    )
    by_brand = (
        candidates["brand"].fillna("unknown").value_counts().to_dict()
        if "brand" in candidates.columns
        else {}
    )
    target_results = manifest.get("target_results")
    coverage = {
        "candidate_rows": len(candidates),
        "accepted_rows": len(accepted),
        "uncertain_rows": len(uncertain),
        "target_results": target_results,
        "target_met_by_candidates": target_results is None or len(candidates) >= target_results,
        "target_met_by_accepted": target_results is None or len(accepted) >= target_results,
        "by_platform": by_platform,
        "by_marketplace": by_marketplace,
        "by_brand": by_brand,
    }
    coverage_path = review_dir / "coverage_report.json"
    write_json(coverage_path, coverage)
    report = {
        "reviewed": len(classified),
        "candidates": len(candidates),
        "accepted": len(accepted),
        "uncertain": len(uncertain),
        "excluded": len(excluded),
        "minimum_keep_confidence": minimum_confidence,
        "candidate_rate": (
            round(len(candidates) / len(classified), 4) if len(classified) else 0
        ),
        "files": {
            "detailed_audit": str(classified_path),
            "final": str(final_path),
            "final_excel": str(final_excel_path),
            "coverage": str(coverage_path),
        },
    }
    write_json(review_dir / "ai_review_report.json", report)
    return report
