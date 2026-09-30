#!/bin/bash
# Price Lens - the previous (Streamlit) app, kept as a fallback.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Run setup_mac.command first (double-click it)."
  read -r -p "Press Return to close."
  exit 1
fi
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
.venv/bin/python -m streamlit run apps/unified_app.py
