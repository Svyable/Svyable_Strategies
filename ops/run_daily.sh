#!/bin/zsh
# Svyable daily run — produces target weights + morning report before 8:30 AM ET.
# Invoked by launchd (com.svyable.daily.plist) or manually / by the Claude loop.
set -euo pipefail

ENGINE_DIR="${SVYABLE_ENGINE_DIR:-$HOME/Svyable_Strategies/engine}"
LOG_DIR="$ENGINE_DIR/logs"
mkdir -p "$LOG_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/daily_$STAMP.log"

cd "$ENGINE_DIR"

# Holiday/weekend awareness lives in the CLI (svyable.calendar); it exits 0 with a skip note.

# External dead-man's switch (healthchecks.io or similar): set SVYABLE_HEALTHCHECK_URL
# in ~/.zshenv. If no ping arrives by the configured grace time, THEY alert you —
# which also covers "the laptop was asleep at 07:30".
ping_hc() {  # $1: "" for success, "/fail" for failure
  if [[ -n "${SVYABLE_HEALTHCHECK_URL:-}" ]]; then
    curl -fsS -m 10 --retry 3 "${SVYABLE_HEALTHCHECK_URL}$1" >/dev/null || true
  fi
}

echo "=== svyable daily $STAMP ===" | tee -a "$LOG"
if ".venv/bin/python" -m svyable.cli --start 2020-01-01 daily 2>&1 | tee -a "$LOG"; then
  echo "OK $STAMP" >> "$LOG_DIR/heartbeat.log"
  ping_hc ""
else
  rc=$?
  echo "FAILED rc=$rc $STAMP" >> "$LOG_DIR/heartbeat.log"
  ping_hc "/fail"
  # local notification so a silent failure is never silent
  osascript -e 'display notification "Svyable daily run FAILED — check logs" with title "Svyable"' || true
  exit $rc
fi

# prune logs older than 30 days
find "$LOG_DIR" -name 'daily_*.log' -mtime +30 -delete || true
