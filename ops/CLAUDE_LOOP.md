# Running Svyable as a Claude loop

The design principle: **deterministic code computes the weights; Claude reviews,
explains, and escalates.** The morning numbers must never depend on an LLM being
available or agreeing with itself — launchd guarantees the weights exist by
07:35 ET; the Claude layer adds judgment on top.

## Layer 1 — deterministic job (required)

```bash
# one-time install
cd ~/Svyable_Strategies/engine
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python numpy pandas pyarrow yfinance scikit-learn scipy
cp ../ops/com.svyable.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.svyable.daily.plist
```

Every weekday 07:30 local (set the Mac to ET, or adjust the plist):
`run_daily.sh` → `svyable daily` → refresh data cache → validate → pipeline →
artifacts + `outputs/svyable_nasdaq_lo/LATEST.md` (the morning report).
Failures fire a macOS notification and land in `engine/logs/heartbeat.log`.

## Layer 2 — Claude morning review (the agentic loop)

Create a Claude Code scheduled task (or run `/loop` in a session) with this prompt:

```
Svyable morning review. Working dir: ~/Svyable_Strategies.

1. Read engine/outputs/svyable_nasdaq_lo/LATEST.md and engine/logs/heartbeat.log.
2. If the last heartbeat is FAILED or older than today (weekday): diagnose from
   engine/logs/daily_*.log, attempt one re-run of ops/run_daily.sh, and report
   what happened. Do not hand-edit weights — ever.
3. If the report shows DEGRADED data, kill switch TRIPPED, a single position
   > 15%, turnover > 25%, or any sleeve IC below -0.05: summarize the issue,
   what the engine already did about it, and what (if anything) needs a human.
4. Otherwise reply with a 5-line digest: budget, seats, top 5 weights with
   deltas, sleeve trust ranking, and yesterday's shadow-book return vs the
   equal-weight benchmark.
5. Append the digest to journal/YYYY-MM.md (create if missing).
```

Schedule it 07:50 ET weekdays — after launchd has run, before the 08:30
deadline — via the Claude Code `schedule` skill (`/schedule`) or a cron-based
scheduled task. In an interactive session, `/loop` with the same prompt and a
~1h cadence works for a trading-day babysit.

### Hard rules for the agent layer
- Claude never computes or modifies weights; it reads artifacts.
- Claude may re-run `ops/run_daily.sh` (idempotent, writes a new tag) but never
  edits engine config mid-loop. Config changes go through a human + a
  walk-forward report (strategy.md §8.5).
- If both the 07:30 job and the re-run fail, the standing instruction is:
  **yesterday's weights remain in force** (the no-trade default) and the human
  gets paged in the digest.

## Layer 3 — execution (built: paper today, Alpaca-paper next)

`svyable rebalance` consumes the latest `weights_today.csv`, plans integer-share
orders (ADV caps, sells-first, lev_cap pre-trade check), logs every plan to
`outputs/svyable_nasdaq_lo/orders/`, and reconciles after fills.

- `--broker paper` (default): offline JSON paper account — safe for the loop.
- `--broker alpaca`: Alpaca **paper** endpoint (live is deliberately not reachable
  from the CLI); needs `ALPACA_KEY_ID` / `ALPACA_SECRET_KEY` env vars.
- Dry run is the default; `--execute` is required to submit anything.

The Claude loop MAY run the dry-run and include the planned orders in the digest.
The `--execute` step stays human-triggered until the roadmap Phase-3 gate.

## Timeline on a trading day (all ET)

| Time | What | Who |
|---|---|---|
| ~04:00 | yfinance has final prior-day EOD | vendor |
| 07:30 | launchd fires `run_daily.sh` → weights + report (~1 min on M4) | code |
| 07:50 | Claude review: health checks, digest, journal | agent |
| 08:30 | **deadline: weights in hand** | — |
| 09:28 | (manual era) place MOC orders / (later) rebalancer submits | human → code |
| 16:15 | optional: Claude EOD note — fills vs targets, reconciliation | agent |
