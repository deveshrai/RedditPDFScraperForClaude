#!/bin/bash
# Reddit -> PDF launcher (double-click in Finder, or run ./run.command)
#  - finds a Python that has a modern Tk (8.6+); Apple's built-in Python does not
#  - installs Python+Tk via Homebrew if none is found
#  - creates a private .venv and installs requirements.txt (re-runs if it changes)
#  - installs Playwright's Chromium only if Google Chrome isn't installed

cd "$(dirname "$0")" || exit 1

pause_exit() {
  echo
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit "${1:-1}"
}

# Python >= 3.9 whose tkinter is Tk 8.6+
has_tk() {
  "$1" -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 9) and tkinter.TkVersion >= 8.6 else 1)' >/dev/null 2>&1
}

find_python() {
  local c
  for c in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 /usr/local/bin/python3.10 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    "$(command -v python3 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] || continue
    [ "$c" = "/usr/bin/python3" ] && continue   # Apple's Python: Tk 8.5, blank windows
    has_tk "$c" && { echo "$c"; return 0; }
  done
  return 1
}

PY="$(find_python)"

if [ -z "$PY" ]; then
  echo "No Python with Tk 8.6+ found."
  BREW="$(command -v brew || ls /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -n1)"
  if [ -n "$BREW" ]; then
    echo "Installing Python + Tk with Homebrew (python-tk@3.11)..."
    "$BREW" install python-tk@3.11 || pause_exit 1
    PY="$(find_python)"
  fi
  if [ -z "$PY" ]; then
    echo
    echo "Couldn't find or install a suitable Python."
    echo "Install Homebrew (https://brew.sh) and re-run this, or install Python from"
    echo "https://www.python.org/downloads/macos/ (it bundles Tk 8.6)."
    pause_exit 1
  fi
fi
echo "Using Python: $PY"

# Private virtual environment (rebuilt if its Python no longer has a good Tk)
if [ -d .venv ] && ! has_tk .venv/bin/python; then
  echo "Rebuilding .venv..."
  rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv .venv || pause_exit 1
fi
VPY=".venv/bin/python"

# Install requirements when requirements.txt is new or changed
REQ_HASH="$(shasum requirements.txt | cut -d' ' -f1)"
if [ "$(cat .venv/.req_hash 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "Installing dependencies..."
  "$VPY" -m pip install -q --upgrade pip
  "$VPY" -m pip install -r requirements.txt || pause_exit 1
  echo "$REQ_HASH" > .venv/.req_hash
fi

# Browser: use installed Google Chrome, otherwise fetch Playwright's Chromium once
if [ ! -d "/Applications/Google Chrome.app" ] && [ ! -d "$HOME/Applications/Google Chrome.app" ] \
   && [ ! -f .venv/.chromium_installed ]; then
  echo "Google Chrome not found - installing Playwright's Chromium (one-time)..."
  "$VPY" -m playwright install chromium || pause_exit 1
  touch .venv/.chromium_installed
fi

"$VPY" main.py
status=$?
[ $status -ne 0 ] && pause_exit $status
exit 0
