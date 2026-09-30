"""Summarise a quick one-page run into a per-storefront health table."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

CHECK_COLUMNS = ["platform", "country", "storefront", "result", "products_found", "problem", "final_url"]

_PATTERNS = (
    # Our own connection, not the shop: checked first and never remembered as a shop problem.
    ("Network", r"^network:|neterror|dnsnotfound|connectionfailure|nettimeout|netreset|"
                r"reached error page|err_internet_disconnected|err_name_not_resolved|"
                r"name or service not known|getaddrinfo failed|network is unreachable"),
    ("Cookie wall", r"cookie|consent"),
    ("Bot check", r"captcha|robot|verify|verif|access denied|zugriff verweigert|blocked|"
                  r"security verification|pardon our interruption|checking your browser|mensch"),
    ("Redirect", r"redirect|unexpected retailer|outside"),
    ("Unavailable", r"unavailable"),
    ("Browser problem", r"geckodriver|firefox|browser|session not created|webdriverexception"),
    ("No products loaded", r"timeout|no new listing|not parsed|no product|grid"),
)


def classify_problem(error: str) -> str:
    text = (error or "").lower()
    for label, pattern in _PATTERNS:
        if re.search(pattern, text):
            return label
    return "Error" if text else ""


def storefront_check_table(reports: list[dict], preview: list[dict] | None = None) -> pd.DataFrame:
    """One row per storefront: OK / Partial / problem type, with the evidence."""
    info: dict[tuple[str, str], dict[str, Any]] = {}
    for row in preview or []:
        info.setdefault((row["platform"], row["domain"]), {
            "platform": row["platform"], "country": row.get("country", ""),
            "storefront": row["domain"], "products_found": 0, "errors": [], "final_url": "",
            "partial": False,
        })

    for search in reports:
        if search.get("error") and not search.get("report"):
            for item in info.values():
                if not item["products_found"]:
                    item["errors"].append(search["error"])
        for platform, report in ((search.get("report") or {}).get("platform_reports") or {}).items():
            touched = set()
            for event in report.get("events", []):
                domain = event.get("marketplace")
                if not domain or "listings" not in event:
                    continue
                item = info.setdefault((platform, domain), {
                    "platform": platform, "country": "", "storefront": domain,
                    "products_found": 0, "errors": [], "final_url": "", "partial": False})
                item["products_found"] += int(event.get("listings") or 0)
                item["final_url"] = event.get("final_url") or item["final_url"]
                item["partial"] |= event.get("status") == "partial"
                touched.add(domain)
            for failure in report.get("failures", []):
                domain = failure.get("marketplace")
                if not domain:
                    continue
                item = info.setdefault((platform, domain), {
                    "platform": platform, "country": "", "storefront": domain,
                    "products_found": 0, "errors": [], "final_url": "", "partial": False})
                item["errors"].append(str(failure.get("error", "")))
                item["final_url"] = failure.get("final_url") or item["final_url"]
                touched.add(domain)
            if report.get("status") == "failed" and report.get("error"):
                for (plat, domain), item in info.items():
                    if plat == platform and domain not in touched:
                        item["errors"].append(str(report["error"]))

    rows = []
    for item in info.values():
        error = " | ".join(dict.fromkeys(e for e in item["errors"] if e))
        problem = classify_problem(error)
        if item["products_found"] and not error:
            result = "Partial" if item["partial"] else "OK"
        elif item["products_found"]:
            result = "Partial"
        else:
            result = problem or "No products loaded"
        rows.append({
            "platform": item["platform"], "country": item["country"],
            "storefront": item["storefront"], "result": result,
            "products_found": item["products_found"],
            "problem": error[:400], "final_url": item["final_url"],
        })
    return pd.DataFrame(rows, columns=CHECK_COLUMNS)
