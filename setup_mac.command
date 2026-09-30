#!/bin/bash
# Price Lens - one-time setup on a Mac (double-click this file).
# Creates a private Python environment in .venv and installs the app into it.
cd "$(dirname "$0")" || exit 1
echo "Setting up Price Lens in: $(pwd)"
echo

# Find Python 3.10 or newer (the one that ships with macOS is too old).
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer was not found."
  echo "Install it from https://www.python.org/downloads/macos/ and run this file again."
  read -r -p "Press Return to close."
  exit 1
fi
echo "Using $("$PY" --version) ($PY)"

# A .venv copied from Windows (it has Scripts\ instead of bin/) cannot be used on a Mac.
if [ -d .venv ] && [ ! -x .venv/bin/python ]; then
  echo "Replacing a Python environment copied from another computer..."
  rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment..."
  "$PY" -m venv .venv || { read -r -p "Could not create .venv. Press Return to close."; exit 1; }
fi

echo "Installing Price Lens (this takes a few minutes the first time)..."
.venv/bin/python -m pip install --upgrade pip || { read -r -p "Install failed. Press Return to close."; exit 1; }
.venv/bin/python -m pip install -e . || { read -r -p "Install failed. Press Return to close."; exit 1; }

chmod +x start_new_app.command start_app.command 2>/dev/null

echo
echo "Checking the setup..."
if ! .venv/bin/python -m price_lens.cli doctor; then
  echo
  echo "Setup finished, but something needs attention (see above)."
  echo "Most often: install Firefox from https://www.mozilla.org/firefox/"
  read -r -p "Press Return to close."
  exit 1
fi
echo
echo "Setup complete. Start the app by double-clicking start_new_app.command."
read -r -p "Press Return to close."
