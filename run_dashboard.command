#!/bin/bash
# Svyable Strategies — double-click to launch the Streamlit operations console.
# macOS equivalent of a run_streamlit.bat. Reads engine/.env for host/port/posture.
set -euo pipefail

# Resolve repo root = directory this script lives in, regardless of where it's launched from.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/engine"

if [ ! -x ".venv/bin/python" ]; then
  echo "ERROR: engine/.venv not found. Create it, then: .venv/bin/pip install -r requirements.txt"
  read -r -p "Press Return to close..." _
  exit 1
fi

echo "Launching Svyable console  (Ctrl-C to stop)..."
exec .venv/bin/python -m svyable.ui
