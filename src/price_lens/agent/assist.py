"""Fast AI relevance review for the Streamlit app.

Compact format (about a third of the text of the original JSON exchange):

* prompt: one line per product -> ``p001 | title | brand | 499.00 EUR | amazon.de | ...``
* answer: one line per product -> ``p001|keep|0.95|smartphone|complete phone``

Answers can be pasted from any AI chat (one batch, or all remaining batches in one go) or
fetched from the Claude API in parallel. Partial answers are saved; products the AI skipped
are moved into a small follow-up batch, so nothing has to be redone.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from price_lens.core.validation import RequestValidationError

from .review import _validate_decision

DEFAULT_MODEL = "claude-sonnet-5-5"
API_URL = "https://api.anthropic.com/v1/messages"
RECOMMENDED_BATCH_CHAT = 150      # reliable in ChatGPT / Gemini / Claude chats
RECOMMENDED_BATCH_API = 100       # small enough for many parallel API calls
_manifest_lock = threading.Lock()

RULES = """You are reviewing marketplace listings for a price-research dataset.
Decide for EVERY product whether it belongs in the dataset described below.
- Use only the listing evidence given (title, brand, price, shop, ...).
- Accessories, spare parts, services, contracts, bundles of unrelated items and other
  product categories do NOT belong unless the instruction asks for them.
- Missing information is uncertainty, not proof: lower your confidence instead.
- confidence = how sure you are about YOUR decision, from 0 to 1.

ANSWER FORMAT - one line per product, nothing else (no headers, no commentary):
ref|keep-or-drop|confidence|category|reason (max 6 words)
Example:
p001|keep|0.95|smartphone|complete phone, current model
p002|drop|0.97|phone case|accessory, not a phone
Answer for every ref below, in any order."""


def default_instruction(product_types: list[str], research_question: str = "") -> str:
    kinds = ", ".join(dict.fromkeys(t for t in product_types if t)) or "the searched products"
    return (f"Keep complete {kinds} that match the research question. Exclude accessories "
            "(cases, covers, cables, chargers, screen protectors, mounts, bags), spare parts, "
            "services, contracts/tariffs, and unrelated products.")


# ---------------------------------------------------------------------------
# Batches and manifest
# ---------------------------------------------------------------------------
def load_batch(batch_path: Path) -> dict[str, Any]:
    return json.loads(Path(batch_path).read_text(encoding="utf-8"))


def _manifest(review_dir: Path) -> dict:
    from .review import load_manifest  # paths re-anchored to this folder

    return load_manifest(Path(review_dir))


def _write_manifest(review_dir: Path, manifest: dict) -> None:
    (Path(review_dir) / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def batch_files(review_dir: Path) -> dict[str, Path]:
    """Batch name -> batch JSON path in this review folder."""
    return {b["batch"]: Path(b["input"]) for b in _manifest(review_dir).get("batches", [])}


def _decision_path(review_dir: Path, batch_path: Path) -> Path:
    """Always inside this review folder, even if the batch file names an older location."""
    return Path(review_dir) / "decisions" / f"{Path(batch_path).stem}.decisions.json"


def pending_batches(review_dir: Path) -> list[str]:
    return [name for name, path in batch_files(review_dir).items()
            if not _decision_path(review_dir, path).exists()]


def pending_products(review_dir: Path) -> int:
    files = batch_files(review_dir)
    return sum(len(load_batch(files[name])["products"]) for name in pending_batches(review_dir))


def _ref(product: dict) -> str:
    return str(product.get("ref") or product["row_id"])


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def _fmt_price(product: dict) -> str:
    value = product.get("price_value")
    if value is None:
        return "no price"
    try:
        return f"{float(value):.2f} {product.get('currency_code') or ''}".strip()
    except (TypeError, ValueError):
        return str(value)


def _product_line(product: dict, show_query: bool) -> str:
    title = " ".join(str(product.get("product_name") or "").replace("|", "/").split())
    parts = [
        _ref(product),
        title,  # full title: details such as colour or model often sit at the end
        str(product.get("brand") or "-"),
        _fmt_price(product),
        str(product.get("marketplace") or product.get("platform") or "-"),
    ]
    # Every captured attribute that can decide relevance (e.g. "black running shoes").
    for field in ("condition", "audience", "color", "availability", "seller"):
        value = product.get(field)
        if value not in (None, "") and str(value).lower() != "nan":
            parts.append(f"{field}: {' '.join(str(value).replace('|', '/').split())}")
    if show_query and product.get("source_search_term"):
        parts.append(f"searched: {product['source_search_term']}")
    return " | ".join(parts)


def compact_prompt(batch_paths: list[Path]) -> str:
    batches = [load_batch(p) for p in batch_paths]
    products = [p for b in batches for p in b["products"]]
    queries = {p.get("source_search_term") for p in products if p.get("source_search_term")}
    lines = "\n".join(_product_line(p, len(queries) > 1) for p in products)
    return (f"{RULES}\n\nRESEARCH QUESTION: {batches[0]['research_question']}\n"
            f"WHAT TO KEEP: {batches[0]['instruction']}\n\n"
            f"PRODUCTS ({len(products)}): ref | title | brand | price | shop | extra\n{lines}\n")


# Backwards-compatible name used by older code.
def batch_prompt(batch_path: Path) -> str:
    return compact_prompt([batch_path])


# ---------------------------------------------------------------------------
# Parsing answers
# ---------------------------------------------------------------------------
KEEP_WORDS = {"keep", "k", "yes", "y", "1", "true", "include", "accept", "relevant", "✓"}
DROP_WORDS = {"drop", "d", "x", "no", "n", "0", "false", "exclude", "remove", "reject",
              "irrelevant", "✗"}


def _confidence(text: Any) -> float | None:
    try:
        value = float(str(text).strip().rstrip("%").replace(",", "."))
    except ValueError:
        return None
    if value > 1:
        value /= 100
    return value if 0 <= value <= 1 else None


def _keep(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    return True if word in KEEP_WORDS else False if word in DROP_WORDS else None


def _raw_items(text: str) -> list[dict]:
    """Accept the compact line format or the older JSON {"decisions": [...]} format."""
    cleaned = text.strip().lstrip("﻿")
    fenced = re.findall(r"```(?:\w+)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = "\n".join(fenced)
    if cleaned[:1] in "[{":
        try:
            data = json.loads(cleaned)
            items = data.get("decisions") if isinstance(data, dict) else data
            if isinstance(items, list):
                return [i for i in items if isinstance(i, dict)]
        except json.JSONDecodeError:
            pass
    items = []
    for line in cleaned.splitlines():
        line = line.strip().strip("`").lstrip("-*• ").strip()
        if line.count("|") < 2:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[0].lower() in {"ref", "id", "row_id"}:
            continue  # header row
        items.append({"ref": cells[0], "keep": cells[1],
                      "confidence": cells[2] if len(cells) > 2 else None,
                      "category": cells[3] if len(cells) > 3 else "",
                      "reason": " | ".join(cells[4:]) if len(cells) > 4 else ""})
    return items


def parse_answer(text: str, batch_paths: list[Path]) -> tuple[dict[Path, list[dict]], dict[Path, list[dict]]]:
    """Return (decisions per batch, skipped products per batch). Raises if nothing usable."""
    owner: dict[str, tuple[Path, dict]] = {}
    for path in batch_paths:
        for product in load_batch(path)["products"]:
            owner[_ref(product).lower()] = (path, product)
            owner[str(product["row_id"]).lower()] = (path, product)
    decided: dict[Path, dict[str, dict]] = {Path(p): {} for p in batch_paths}
    for item in _raw_items(text):
        key = str(item.get("ref") or item.get("row_id") or "").strip().lower()
        if key not in owner:
            continue
        path, product = owner[key]
        keep, confidence = _keep(item.get("keep")), _confidence(item.get("confidence"))
        if keep is None or confidence is None:
            continue
        decision = {
            "row_id": product["row_id"], "keep": keep, "confidence": confidence,
            "category": str(item.get("category") or "").strip() or "unspecified",
            "reason": str(item.get("reason") or "").strip() or "no reason given",
        }
        _validate_decision(decision, {product["row_id"]}, Path(path))
        decided[Path(path)][product["row_id"]] = decision
    if not any(decided.values()):
        raise RequestValidationError(
            "No usable decisions found. Each line should look like: p001|keep|0.95|category|reason")
    missing = {Path(p): [prod for prod in load_batch(p)["products"]
                         if prod["row_id"] not in decided[Path(p)]] for p in batch_paths}
    return {p: list(v.values()) for p, v in decided.items()}, missing


# ---------------------------------------------------------------------------
# Saving (with follow-up batches for skipped products)
# ---------------------------------------------------------------------------
def _add_followup(review_dir: Path, batch_path: Path, products: list[dict]) -> str:
    review_dir = Path(review_dir)
    with _manifest_lock:
        manifest = _manifest(review_dir)
        base = Path(batch_path).stem
        existing = {b["batch"] for b in manifest["batches"]}
        n = 1
        while f"{base}_rest{n}" in existing:
            n += 1
        name = f"{base}_rest{n}"
        batch = load_batch(batch_path)
        decision_file = (review_dir / "decisions" / f"{name}.decisions.json").resolve()
        batch.update(products=products, output_file=str(decision_file))
        input_path = (review_dir / f"{name}.json").resolve()
        input_path.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest["batches"].append({"batch": name, "input": str(input_path),
                                    "decisions": str(decision_file), "rows": len(products)})
        _write_manifest(review_dir, manifest)
    return name


def save_answer(review_dir: Path, batch_names: list[str], text: str) -> dict[str, Any]:
    """Save an AI answer for one or more pending batches.

    Answered products are saved; skipped products go into a follow-up batch.
    """
    files = batch_files(review_dir)
    paths = [files[name] for name in batch_names]
    decided, missing = parse_answer(text, paths)
    saved, followups = 0, []
    for path in paths:
        decisions = decided[path]
        if not decisions:
            continue  # nothing answered for this batch: it simply stays pending
        target = _decision_path(review_dir, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"decisions": decisions}, indent=2, ensure_ascii=False),
                          encoding="utf-8")
        saved += len(decisions)
        if missing[path]:
            followups.append(_add_followup(review_dir, path, missing[path]))
    return {"saved": saved, "missing": sum(len(v) for p, v in missing.items() if decided[p]),
            "followups": followups,
            "unanswered_batches": [n for n, p in zip(batch_names, paths) if not decided[p]]}


# ---------------------------------------------------------------------------
# Claude API (parallel)
# ---------------------------------------------------------------------------
def api_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _call_claude(prompt: str, *, api_key: str | None = None, model: str | None = None,
                 timeout: int = 240) -> str:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RequestValidationError("Set the ANTHROPIC_API_KEY environment variable first.")
    body = json.dumps({
        "model": model or os.environ.get("PI_REVIEW_MODEL", DEFAULT_MODEL),
        "max_tokens": 12000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RequestValidationError(f"Claude API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RequestValidationError(f"Could not reach the Claude API: {exc.reason}") from exc
    return "".join(part.get("text", "") for part in reply.get("content", [])
                   if part.get("type") == "text")


def review_with_claude(review_dir: Path, *, workers: int = 5, rounds: int = 3,
                       progress: Callable[[str], None] | None = None,
                       call: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Review every pending batch, several at once; retry skipped rows in follow-up rounds."""
    progress = progress or (lambda _m: None)
    call = call or _call_claude
    totals: dict[str, Any] = {"saved": 0, "errors": []}
    for round_no in range(1, rounds + 1):
        pending = pending_batches(review_dir)
        if not pending:
            break
        files = batch_files(review_dir)
        progress(f"Round {round_no}: sending {len(pending)} batch(es), {workers} at a time…")

        def work(name: str) -> dict:
            return save_answer(review_dir, [name], call(compact_prompt([files[name]])))

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(work, name): name for name in pending}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    totals["saved"] += result["saved"]
                    extra = f", {result['missing']} skipped → retry" if result["missing"] else ""
                    progress(f"{name}: {result['saved']} decisions{extra}")
                except RequestValidationError as exc:
                    totals["errors"].append(f"{name}: {exc}")
                    progress(f"{name}: failed — {exc}")
    totals["pending"] = pending_batches(review_dir)
    return totals


# Backwards-compatible helpers ------------------------------------------------
def parse_decisions(text: str, batch_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Strict: every product of one batch must be answered."""
    decided, missing = parse_answer(text, [Path(batch_path)])
    if missing[Path(batch_path)]:
        raise RequestValidationError(
            f"{len(missing[Path(batch_path)])} products have no decision.")
    return {"decisions": decided[Path(batch_path)]}


def save_decisions(batch_path: Path, payload: dict) -> Path:
    target = Path(load_batch(batch_path)["output_file"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
