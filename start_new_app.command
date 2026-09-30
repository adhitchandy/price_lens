#!/bin/bash
# Price Lens - start the app on a Mac (double-click this file).
# Your browser opens by itself. Keep this window open; close it to stop the app.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Run setup_mac.command first (double-click it)."
  read -r -p "Press Return to close."
  exit 1
fi
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
echo "Starting Price Lens. Your browser opens by itself."
echo "Keep this window open while you use the app; close it to stop the app."
echo
.venv/bin/python -m price_lens.webapp || read -r -p "The app stopped with an error (see above). Press Return to close."
