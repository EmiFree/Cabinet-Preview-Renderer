#!/bin/sh
# Cabinet Preview Renderer launcher for macOS / Linux. Needs Python 3.8+ (python3).
HERE="$(cd "$(dirname "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else
  echo "ERROR: Python 3.8+ not found. macOS: run 'xcode-select --install'. Linux: install the python3 package." >&2
  exit 9
fi
exec "$PY" "$HERE/tools/cpr.py" "$@"
