"""Price-research views of a run: tidy product table, price summary, Excel report."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import pandas as pd

from .analyst import CATALOG

DOMAIN_COUNTRY = {domain: info["country"] for domains in CATALOG.values() for domain, info in domains.items()}

# The columns an analyst looks at, in reading order.
PRODUCT_COLUMNS = [
    "product_name", "product_url", "brand", "price_value", "currency_code", "price_usd", "country",
    "platform", "marketplace", "group", "audience", "category", "condition", "color",
    "availability", "seller", "rating", "review_count", "review_status",
    "relevance_confidence_pct", "search_id", "product_id", "scraped_at",
]
# Always exported (even when empty) so downloads keep traceability, QC and dates.
EXPORT_ALWAYS = ["product_name", "product_url", "brand", "price_value", "currency_code",
                 "price_usd", "country", "platform", "marketplace", "review_status",
                 "relevance_confidence_pct", "search_id", "product_id", "scraped_at"]
COLUMN_LABELS = {
    "product_name": "Product", "brand": "Brand", "price_value": "Price", "currency_code": "Currency",
    "price_usd": "Price (USD)", "country": "Country", "platform": "Platform",
    "marketplace": "Storefront", "group": "Product group", "audience": "Audience",
    "category": "Category", "condition": "Condition", "color": "Colour",
    "availability": "Availability", "seller": "Seller", "rating": "Rating",
    "review_count": "Reviews", "review_status": "Review",
    "relevance_confidence_pct": "Relevance confidence (%)", "search_id": "Search",
    "product_id": "Product ID", "scraped_at": "Collected at (UTC)", "product_url": "Link",
}


def group_labels(plan: dict | None) -> dict[int, str]:
    """search_id -> readable product-group label, from the run's plan."""
    labels = {}
    for index, search in enumerate((plan or {}).get("searches", []), start=1):
        query = search.get("query") or {}
        name = search.get("product_type") or query.get("default") or search.get("search_term")
        labels[index] = f"{index} · {name}" if name else f"Search {index}"
    return labels


def prepare_products(frame: pd.DataFrame, labels: dict[int, str] | None = None) -> pd.DataFrame:
    """Add country / product-group / category columns and numeric prices."""
    df = frame.copy()
    if df.empty:
        return df.reindex(columns=list(dict.fromkeys([*df.columns, *PRODUCT_COLUMNS])))
    if "marketplace" in df.columns:
        country = df["marketplace"].map(DOMAIN_COUNTRY)
        if "country" in df.columns:  # (fillna(None) fails on older pandas)
            country = country.fillna(df["country"])
        df["country"] = country
    for column in ("price_value", "price_usd", "rating", "review_count", "relevance_confidence_pct"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    category = df["product_type"] if "product_type" in df.columns else pd.Series(index=df.index, dtype=object)
    if "review_category" in df.columns:
        category = df["review_category"].where(df["review_category"].notna(), category)
    df["category"] = category
    if "search_id" in df.columns:
        ids = pd.to_numeric(df["search_id"], errors="coerce")
        df["group"] = ids.map(lambda i: (labels or {}).get(int(i), f"Search {int(i)}")
                              if pd.notna(i) else None)
    if "audience" in df.columns:
        df["audience"] = df["audience"].replace({"": None})
    return df


def product_view(df: pd.DataFrame, *, export: bool = False) -> pd.DataFrame:
    """Analyst columns. On screen, empty columns are hidden; exports keep the key fields."""
    columns = [c for c in PRODUCT_COLUMNS if c in df.columns
               and (df[c].notna().any() or (export and c in EXPORT_ALWAYS))]
    return df.loc[:, columns]


def _group_keys(df: pd.DataFrame) -> list[str]:
    keys = []
    if "group" in df.columns and df["group"].nunique(dropna=True) > 1:
        keys.append("group")
    keys += [k for k in ("country", "platform", "marketplace") if k in df.columns]
    if "audience" in df.columns and df["audience"].notna().any():
        keys.append("audience")
    return keys


def price_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per storefront (and category / audience when present)."""
    columns = ["listings", "with_price", "currency", "min", "median", "max",
               "min_usd", "median_usd", "mean_usd", "max_usd"]
    if df.empty or "price_value" not in df.columns:
        return pd.DataFrame(columns=columns)
    keys = _group_keys(df)
    work = df.copy()
    for key in keys:
        work[key] = work[key].fillna("—")
    usd = work["price_usd"] if "price_usd" in work.columns else pd.Series(index=work.index, dtype=float)
    work["_usd"] = usd
    grouped = work.groupby(keys, dropna=False, sort=True)
    summary = grouped.agg(
        listings=("price_value", "size"),
        with_price=("price_value", "count"),
        currency=("currency_code", lambda s: ", ".join(sorted(set(s.dropna().astype(str)))))
        if "currency_code" in work.columns else ("price_value", lambda s: ""),
        min=("price_value", "min"),
        median=("price_value", "median"),
        max=("price_value", "max"),
        min_usd=("_usd", "min"),
        median_usd=("_usd", "median"),
        mean_usd=("_usd", "mean"),
        max_usd=("_usd", "max"),
    ).reset_index()
    for column in ("min", "median", "max", "min_usd", "median_usd", "mean_usd", "max_usd"):
        summary[column] = summary[column].round(2)
    return summary.sort_values(["median_usd"], na_position="last").reset_index(drop=True)


def headline(df: pd.DataFrame, summary: pd.DataFrame) -> dict[str, Any]:
    priced = summary.dropna(subset=["median_usd"]) if not summary.empty else summary
    # A storefront needs a few priced listings before its median means anything.
    solid = priced[priced["with_price"] >= min(3, int(priced["with_price"].max()))] if len(priced) else priced
    cheapest = solid.iloc[0] if len(solid) else None
    dearest = solid.iloc[-1] if len(solid) else None

    def label(row):
        if row is None:
            return "—"
        extra = [str(row[c]) for c in ("group", "audience") if c in row and row[c] != "—"]
        return " · ".join([str(row["platform"]), *extra])
    return {
        "listings": int(len(df)),
        "storefronts": int(df["marketplace"].nunique()) if "marketplace" in df.columns else 0,
        "median_usd": float(df["price_usd"].median()) if "price_usd" in df.columns and df["price_usd"].notna().any() else None,
        "cheapest": label(cheapest),
        "cheapest_country": str(cheapest["country"]) if cheapest is not None else "—",
        "cheapest_usd": float(cheapest["median_usd"]) if cheapest is not None else None,
        "dearest": label(dearest),
        "dearest_country": str(dearest["country"]) if dearest is not None else "—",
        "dearest_usd": float(dearest["median_usd"]) if dearest is not None else None,
    }


SUMMARY_LABELS = {
    "group": "Product group", "country": "Country", "platform": "Platform", "marketplace": "Storefront",
    "audience": "Audience", "listings": "Listings", "with_price": "With price", "currency": "Currency",
    "min": "Min (local)", "median": "Median (local)", "max": "Max (local)", "min_usd": "Min (USD)",
    "median_usd": "Median (USD)", "mean_usd": "Mean (USD)", "max_usd": "Max (USD)",
}


def price_report_xlsx(summary: pd.DataFrame, products: pd.DataFrame, meta: dict[str, str],
                      fx_info: dict | None = None) -> bytes:
    """Workbook: Summary (per storefront), Products (clean view), About (method)."""
    buffer = io.BytesIO()
    summary_out = summary.rename(columns=SUMMARY_LABELS)
    products_out = product_view(products, export=True).rename(columns=COLUMN_LABELS)
    if fx_info:
        used = sorted(set(products.get("currency_code", pd.Series(dtype=str)).dropna().astype(str)))
        rates = fx_info.get("rates", {})
        rate_text = ", ".join(f"1 {c} = {rates[c]:.4f} USD" for c in used if c in rates and c != "USD")
        fx_rows = [("USD rates source", fx_info.get("source", "")),
                   ("USD rates date", fx_info.get("date") or "undated (static table)"),
                   ("USD rates used", rate_text or "—")]
        static = [c for c in used if c in (fx_info.get("static_currencies") or []) and fx_info.get("date")]
        if static:
            fx_rows.append(("Static (undated) rates for", ", ".join(static)))
        manual = fx_info.get("manual") or {}
        own = [f"{c}{' (' + manual[c]['note'] + ')' if manual[c].get('note') else ''}" for c in used if c in manual]
        if own:
            fx_rows.append(("Rates set by the analyst", ", ".join(own)))
        for change in fx_info.get("repriced") or []:
            fx_rows.append(("USD prices updated", f"{str(change.get('at', ''))[:16].replace('T', ' ')}: "
                            f"{', '.join(sorted(change.get('currencies') or {}))}"))
    else:
        fx_rows = [("USD conversion", "Static rates in core/currency.py (run has no dated rates)")]
    about = pd.DataFrame([
        ("Research goal", meta.get("research_question", "")),
        ("Run", meta.get("run", "")),
        ("Report created", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Product group", meta.get("group", "all")),
        ("Filters applied in app", meta.get("filters", "none")),
        ("Data", meta.get("data", "")),
        *fx_rows,
        ("Note", "Median/min/max use listings with a price. Local prices are in each "
                 "storefront's currency; compare countries using the USD columns. Compare "
                 "prices within one product group."),
    ], columns=["Item", "Value"])

    # Never turn listing text like "=HYPERLINK(...)" into live formulas (same as core.export).
    with pd.ExcelWriter(buffer, engine="xlsxwriter", engine_kwargs={
            "options": {"strings_to_formulas": False, "strings_to_urls": True}}) as writer:
        book = writer.book
        header = book.add_format({"bold": True, "bg_color": "#1f2937", "font_color": "#ffffff",
                                  "border": 0, "text_wrap": True, "valign": "top"})
        money = book.add_format({"num_format": "#,##0.00"})
        for name, frame in (("Summary", summary_out), ("Products", products_out), ("About", about)):
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            for col, title in enumerate(frame.columns):
                sheet.write(0, col, title, header)
                lengths = frame[title].map(lambda v: len(str(v)) if pd.notna(v) else 0)
                typical = int(lengths.quantile(0.9)) if len(lengths) else 10
                width = min(60, max(len(str(title)), typical) + 2)
                is_money = any(w in str(title) for w in ("Price", "Min", "Median", "Mean", "Max"))
                sheet.set_column(col, col, width, money if is_money else None)
            if len(frame) and name != "About":
                sheet.autofilter(0, 0, len(frame), len(frame.columns) - 1)
                sheet.freeze_panes(1, 0)
    return buffer.getvalue()
