from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

from price_lens.marketplaces.amazon.constants import AMAZON_DOMAINS
from price_lens.marketplaces.ebay.constants import EBAY_MARKETPLACES
from price_lens.marketplaces.zalando.constants import ZALANDO_MARKETPLACES


def _firefox_path() -> str | None:
    executable = shutil.which("firefox") or shutil.which("firefox.exe")
    if executable:
        return executable
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Mozilla Firefox" / "firefox.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Mozilla Firefox" / "firefox.exe",
        Path("/Applications/Firefox.app/Contents/MacOS/firefox"),  # macOS
        Path.home() / "Applications" / "Firefox.app" / "Contents" / "MacOS" / "firefox",
    ]
    return str(next((path for path in candidates if path.is_file()), "")) or None


def run_doctor(output_dir: Path = Path("output")) -> tuple[bool, list[tuple[str, str, str]]]:
    checks: list[tuple[str, str, str]] = []
    checks.append(("Python", "passed", sys.version.split()[0]))
    selenium_available = importlib.util.find_spec("selenium") is not None
    checks.append(
        (
            "Selenium",
            "passed" if selenium_available else "failed",
            "installed" if selenium_available else
            ("run setup_windows.bat" if os.name == "nt" else "run setup_mac.command"),
        )
    )
    firefox = _firefox_path()
    checks.append(
        (
            "Firefox",
            "passed" if firefox else "failed",
            firefox or "not found; install Mozilla Firefox",
        )
    )
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix="doctor_", delete=True):
            pass
        checks.append(("Output directory", "passed", str(output_dir.resolve())))
    except OSError as exc:
        checks.append(("Output directory", "failed", str(exc)))
    checks.extend(
        [
            ("Amazon adapter", "passed", f"{len(AMAZON_DOMAINS)} marketplaces"),
            ("eBay adapter", "passed", f"{len(EBAY_MARKETPLACES)} marketplaces"),
            ("Zalando adapter", "passed", f"{len(ZALANDO_MARKETPLACES)} marketplaces"),
        ]
    )
    return all(status == "passed" for _, status, _ in checks), checks

