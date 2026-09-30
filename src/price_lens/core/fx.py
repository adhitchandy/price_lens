"""Dated exchange rates for USD price comparisons.

At the start of every run the app fetches the European Central Bank's daily euro reference
rates, converts them to "USD per unit" and saves them in the run folder (fx_rates.json), so
every report can state which rates, from which date and source, were used. Offline, the last
cached ECB rates are used, and as a last resort the static table in core/currency.py.
Currencies the ECB does not publish (e.g. AED, SAR, EGP) use the static table and are listed.
Rates the analyst sets by hand (fx_manual.json in the output folder) win over both.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .currency import FX_TO_USD as STATIC_TO_USD

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_SOURCE = "European Central Bank euro reference rates"
STATIC_SOURCE = "Static rates in core/currency.py (no dated rates available)"
CACHE_FILE = "fx_cache.json"
RUN_FILE = "fx_rates.json"


def _fetch_ecb(timeout: int = 10) -> str:
    with urllib.request.urlopen(ECB_URL, timeout=timeout) as response:
        return response.read().decode("utf-8")


def parse_ecb(xml: str) -> tuple[str, dict[str, float]]:
    """Return (date, {currency: USD per unit})."""
    day = re.search(r"time=['\"](\d{4}-\d{2}-\d{2})['\"]", xml)
    per_eur = {c: float(r) for c, r in re.findall(
        r"currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([\d.]+)['\"]", xml)}
    if not day or "USD" not in per_eur:
        raise ValueError("Unexpected ECB response")
    usd_per_eur = per_eur["USD"]
    rates = {"EUR": round(usd_per_eur, 6), "USD": 1.0}
    for code, units_per_eur in per_eur.items():
        if code != "USD" and units_per_eur:
            rates[code] = round(usd_per_eur / units_per_eur, 8)
    return day.group(1), rates


def get_rates(cache_dir: Path, fetch: Callable[[], str] | None = None) -> dict:
    """Best available USD rates: live ECB > cached ECB > static table."""
    cache = Path(cache_dir) / CACHE_FILE
    try:
        if fetch is None and os.environ.get("PI_FX_OFFLINE"):
            raise OSError("dated rates disabled (PI_FX_OFFLINE)")
        day, ecb = parse_ecb((fetch or _fetch_ecb)())
        info = {"date": day, "source": ECB_SOURCE, "retrieved": date.today().isoformat()}
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({**info, "ecb": ecb}, indent=2), encoding="utf-8")
        except OSError:
            pass
    except Exception:  # noqa: BLE001 - offline, blocked, or format change: fall back
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            day, ecb = cached["date"], cached["ecb"]
            info = {"date": day, "source": f"{ECB_SOURCE} (cached copy, offline at run time)",
                    "retrieved": cached.get("retrieved")}
        except (OSError, ValueError, KeyError):
            return {"date": None, "source": STATIC_SOURCE, "retrieved": None,
                    "rates": dict(STATIC_TO_USD), "static_currencies": sorted(STATIC_TO_USD)}
    rates = {**STATIC_TO_USD, **ecb}
    return {**info, "rates": rates, "static_currencies": sorted(set(STATIC_TO_USD) - set(ecb))}


# ---------------------------------------------------------------------------------------
# Your own rates. Saved in the output folder (fx_manual.json). "keep" rates are used by every
# new run until removed; the others only by the next run, then they are cleared.
# ---------------------------------------------------------------------------------------
MANUAL_FILE = "fx_manual.json"
_CODE = re.compile(r"^[A-Z]{3}$")


def valid_code(code: str) -> str:
    code = str(code or "").strip().upper()
    if not _CODE.match(code):
        raise ValueError("A currency is a three-letter code such as TRY or PLN.")
    return code


def load_manual(cache_dir: Path) -> dict:
    try:
        data = json.loads(Path(cache_dir, MANUAL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    rates = {}
    for code, entry in (data.get("rates") or {}).items():
        try:
            value = float(entry.get("usd_per_unit"))
        except (TypeError, ValueError, AttributeError):
            continue
        if _CODE.match(str(code)) and 0 < value < 1e6:
            rates[code] = {"usd_per_unit": value, "keep": bool(entry.get("keep", True)),
                           "note": str(entry.get("note") or ""), "set_at": entry.get("set_at")}
    return {"rates": rates, "history": list(data.get("history") or [])[-200:]}


def _save_manual(cache_dir: Path, data: dict) -> None:
    path = Path(cache_dir, MANUAL_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(20):  # OneDrive / antivirus can hold the file for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    raise OSError("Could not save your exchange rates (the file is in use by another program).")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_manual(cache_dir: Path, code: str, usd_per_unit: float | None, *, keep: bool = True,
               note: str = "") -> dict:
    """Set (or with None remove) your own rate: USD per one unit of ``code``."""
    code = valid_code(code)
    data = load_manual(cache_dir)
    if usd_per_unit is None:
        if code in data["rates"]:
            data["rates"].pop(code)
            data["history"].append({"at": _stamp(), "currency": code, "action": "removed"})
    else:
        value = float(usd_per_unit)
        if not (0 < value < 1e6) or value != value:
            raise ValueError("The rate must be a positive number.")
        value = float(f"{value:.12g}")  # keeps e.g. 1 USD = 26,300 VND exact when shown again
        data["rates"][code] = {"usd_per_unit": value, "keep": bool(keep),
                               "note": str(note or "").strip()[:300], "set_at": _stamp()}
        data["history"].append({"at": _stamp(), "currency": code, "action": "set",
                                "usd_per_unit": value, "keep": bool(keep),
                                "note": str(note or "").strip()[:300]})
    data["history"] = data["history"][-200:]
    _save_manual(cache_dir, data)
    return data


def with_manual(info: dict, cache_dir: Path) -> dict:
    """The rates of ``info`` with your own rates on top (listed under "manual")."""
    manual = load_manual(cache_dir)["rates"]
    if not manual:
        return info
    return {**info, "rates": {**info["rates"], **{c: e["usd_per_unit"] for c, e in manual.items()}},
            "manual": manual,
            "static_currencies": [c for c in info.get("static_currencies") or [] if c not in manual]}


def rates_for_new_run(cache_dir: Path, fetch: Callable[[], str] | None = None) -> dict:
    """Rates a new run uses: ECB / cached / static, then your own rates. Rates meant for the
    next run only are used here and then cleared."""
    info = with_manual(get_rates(cache_dir, fetch), cache_dir)
    once = [c for c, e in (info.get("manual") or {}).items() if not e["keep"]]
    if once:
        data = load_manual(cache_dir)
        for code in once:
            data["rates"].pop(code, None)
            data["history"].append({"at": _stamp(), "currency": code, "action": "used once"})
        try:
            _save_manual(cache_dir, data)
        except OSError:
            pass
    return info


def save_for_run(run_dir: Path, fx: dict) -> None:
    Path(run_dir, RUN_FILE).write_text(json.dumps(fx, indent=2), encoding="utf-8")


def load_for_run(run_dir: Path) -> dict | None:
    try:
        return json.loads(Path(run_dir, RUN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def apply(frame: pd.DataFrame, rates: dict[str, float]) -> pd.DataFrame:
    """Recompute price_usd from price_value and currency_code with one rate table for all
    platforms (Amazon's scraper otherwise uses its own table)."""
    if frame.empty or "price_value" not in frame.columns or "currency_code" not in frame.columns:
        return frame
    out = frame.copy()
    rate = out["currency_code"].astype(str).str.upper().map(rates)
    converted = (pd.to_numeric(out["price_value"], errors="coerce") * rate).round(2)
    out["price_usd"] = converted.where(rate.notna(), out.get("price_usd"))
    return out


def describe(fx: dict | None) -> str:
    if not fx:
        return "USD conversion: static rates (run made before dated rates were recorded)"
    when = f" of {fx['date']}" if fx.get("date") else ""
    extra = (f"; static rates for {', '.join(fx['static_currencies'])}"
             if fx.get("date") and fx.get("static_currencies") else "")
    if fx.get("manual"):
        extra += f"; your own rates for {', '.join(sorted(fx['manual']))}"
    if fx.get("repriced"):
        extra += f"; USD prices updated {str(fx['repriced'][-1].get('at', ''))[:10]}"
    return f"USD conversion: {fx['source']}{when}{extra}"
