#!/bin/zsh
# Svyable daily PM selector/context-pack run.
#
# Scope:
#   - materialize the effective model universe from seed + index-change ledger;
#   - refresh market data;
#   - evaluate registered strategies/chimeras;
#   - write immutable candidate board + agent context pack;
#   - ping heartbeat endpoints and retain local logs.
#
# It intentionally does NOT write PM decisions, activate portfolios, or submit
# broker orders. Those remain human-approved follow-up steps.
set -euo pipefail
umask 077

ENGINE_DIR="${SVYABLE_ENGINE_DIR:-$HOME/Svyable_Strategies/engine}"

if [[ ! -d "$ENGINE_DIR" ]]; then
  echo "Missing engine directory: $ENGINE_DIR" >&2
  exit 127
fi

cd "$ENGINE_DIR"

# Load local non-committed configuration for launchd runs. The repo's
# .env.example uses simple KEY=value lines, which zsh can source safely here.
if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

ENVIRONMENT="${SVYABLE_ENV:-sandbox}"
PROVIDER="${SVYABLE_PROVIDER:-yf}"
START_DATE="${SVYABLE_START_DATE:-2020-01-01}"
OUT_ROOT="${SVYABLE_OUTPUT_ROOT:-outputs}"
STRICT_DAILY="${SVYABLE_STRICT_DAILY:-true}"
RUN_HEALTH="${SVYABLE_RUN_HEALTH_AFTER_DAILY:-true}"
PYTHON_BIN="${SVYABLE_PYTHON:-$ENGINE_DIR/.venv/bin/python}"
LOG_DIR="${SVYABLE_LOG_DIR:-$ENGINE_DIR/logs}"
UNIVERSE_SEED="${SVYABLE_UNIVERSE_SEED:-universe_nasdaq_seed.txt}"
INDEX_EVENTS="${SVYABLE_INDEX_EVENTS:-universe_index_events.csv}"
UNIVERSE_AS_OF="${SVYABLE_UNIVERSE_AS_OF:-$(date +%F)}"
EFFECTIVE_UNIVERSE="${SVYABLE_EFFECTIVE_UNIVERSE:-$OUT_ROOT/universe/effective_universe.txt}"

mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$LOG_DIR/daily_$STAMP.log"
HEARTBEAT="$LOG_DIR/heartbeat.log"

_truthy() {
  local value="${1:l}"
  [[ "$value" == "1" || "$value" == "true" || "$value" == "yes" || "$value" == "y" || "$value" == "on" ]]
}

ping_hc() {
  if [[ -n "${SVYABLE_HEALTHCHECK_URL:-}" ]]; then
    curl -fsS -m 10 --retry 3 "${SVYABLE_HEALTHCHECK_URL}$1" >/dev/null || true
  fi
}

notify_failure() {
  osascript -e 'display notification "Svyable daily PM run FAILED — check engine/logs and launchd stderr" with title "Svyable"' >/dev/null 2>&1 || true
}

on_error() {
  local rc=$?
  echo "FAILED rc=$rc $STAMP env=$ENVIRONMENT provider=$PROVIDER out=$OUT_ROOT" | tee -a "$LOG" >> "$HEARTBEAT"
  ping_hc "/fail"
  notify_failure
  exit "$rc"
}
trap on_error ERR

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing executable Python: $PYTHON_BIN" >&2
  echo "Create it with: cd $ENGINE_DIR && uv venv .venv --python 3.14 && uv pip install --python .venv/bin/python -e '.[all]'" >&2
  exit 127
fi

echo "=== svyable daily PM selector $STAMP ===" | tee -a "$LOG"
echo "engine=$ENGINE_DIR env=$ENVIRONMENT provider=$PROVIDER out=$OUT_ROOT start=$START_DATE strict=$STRICT_DAILY" | tee -a "$LOG"

ping_hc "/start"

if [[ -f "$INDEX_EVENTS" ]]; then
  echo "=== materialize effective universe as_of=$UNIVERSE_AS_OF ===" | tee -a "$LOG"
  materialize_cmd=(
    "$PYTHON_BIN" -m svyable.universe
    --seed "$UNIVERSE_SEED"
    --events "$INDEX_EVENTS"
    --out "$EFFECTIVE_UNIVERSE"
    --as-of "$UNIVERSE_AS_OF"
  )
  "${materialize_cmd[@]}" 2>&1 | tee -a "$LOG"
else
  EFFECTIVE_UNIVERSE="$UNIVERSE_SEED"
  echo "index event ledger missing; using seed universe: $UNIVERSE_SEED" | tee -a "$LOG"
fi

daily_cmd=(
  "$PYTHON_BIN" -m svyable.strategy_daily
  --env "$ENVIRONMENT"
  --provider "$PROVIDER"
  --start "$START_DATE"
  --out "$OUT_ROOT"
  --universe "$EFFECTIVE_UNIVERSE"
)

if _truthy "$STRICT_DAILY"; then
  daily_cmd+=(--strict)
fi

printf 'command:' | tee -a "$LOG"
printf ' %q' "${daily_cmd[@]}" | tee -a "$LOG"
printf '\n' | tee -a "$LOG"

"${daily_cmd[@]}" 2>&1 | tee -a "$LOG"

if _truthy "$RUN_HEALTH"; then
  echo "=== svyable health ===" | tee -a "$LOG"
  "$PYTHON_BIN" -m svyable.cli --env "$ENVIRONMENT" --out "$OUT_ROOT" health 2>&1 | tee -a "$LOG"
fi

echo "OK $STAMP env=$ENVIRONMENT provider=$PROVIDER out=$OUT_ROOT" | tee -a "$LOG" >> "$HEARTBEAT"
ping_hc ""

find "$LOG_DIR" -name 'daily_*.log' -mtime +30 -delete || true
trap - ERR
