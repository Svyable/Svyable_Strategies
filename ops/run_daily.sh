#!/bin/zsh
# Svyable daily PM run — evaluates registered strategies, selects one canonical
# portfolio, and produces the weights consumed by the Tastytrade workflow.
set -euo pipefail

ENGINE_DIR="${SVYABLE_ENGINE_DIR:-$HOME/Svyable_Strategies/engine}"
LOG_DIR="$ENGINE_DIR/logs"
mkdir -p "$LOG_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/daily_$STAMP.log"

cd "$ENGINE_DIR"

ping_hc() {
  if [[ -n "${SVYABLE_HEALTHCHECK_URL:-}" ]]; then
    curl -fsS -m 10 --retry 3 "${SVYABLE_HEALTHCHECK_URL}$1" >/dev/null || true
  fi
}

echo "=== svyable multi-strategy daily $STAMP ===" | tee -a "$LOG"
if ".venv/bin/python" -m svyable.strategy_daily --start 2020-01-01 2>&1 | tee -a "$LOG"; then
  echo "OK $STAMP" >> "$LOG_DIR/heartbeat.log"
  ping_hc ""
else
  rc=$?
  echo "FAILED rc=$rc $STAMP" >> "$LOG_DIR/heartbeat.log"
  ping_hc "/fail"
  osascript -e 'display notification "Svyable daily PM run FAILED — check logs" with title "Svyable"' || true
  exit $rc
fi

find "$LOG_DIR" -name 'daily_*.log' -mtime +30 -delete || true
