# Running Svyable as a daily PM loop

The design principle is strict: **deterministic code computes complete candidate portfolios; the PM agent may choose only among those candidates.** The agent never creates weights, edits factors, changes parameters, or bypasses execution controls during the morning loop.

## Layer 1 — deterministic candidate evaluation

```bash
cd ~/Svyable_Strategies/engine
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
cp ../ops/com.svyable.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.svyable.daily.plist
```

Every weekday, `ops/run_daily.sh` executes:

```bash
python -m svyable.strategy_daily --start 2020-01-01
```

The job refreshes one shared market panel, evaluates every enabled strategy in the registry, and writes:

```text
outputs/strategy_selection/<tag>/candidate_board.csv
outputs/strategy_selection/<tag>/candidate_board.json
outputs/strategy_selection/<tag>/selection.json
outputs/strategy_selection/<tag>/agent_decision_template.json
```

Each candidate is a complete portfolio recipe with its own factors, construction, risk, cadence, and cost assumptions. The board includes expected next-day alpha, confidence, estimated cost, one-way turnover, current-position overlap, volatility, drawdown, cadence state, hold lock, and cost-aware utility.

Selection policy lives at:

```text
outputs/strategy_selection/policy.json
```

Supported modes:

- `deterministic` — rank candidates and activate immediately;
- `manual` — use the configured registered strategy when it passes eligibility gates;
- `agent` — emit the board, then wait for a fresh hash-matched agent decision.

## Layer 2 — Claude or PM strategy decision

In agent mode, schedule the PM review after the candidate board exists:

```text
Svyable strategy-selection review.

1. Read the newest outputs/strategy_selection/*/candidate_board.csv.
2. Consider only rows where eligible=true.
3. Compare expected alpha, cost, turnover, overlap, cadence, volatility,
   drawdown, and utility. Prefer hold_current when no candidate has a robust
   edge after costs.
4. Never edit weights, factors, strategy code, or policy during this review.
5. Write outputs/strategy_selection/agent_decision.json with the exact board
   as_of date, candidate_set_hash, an eligible candidate_id, confidence, and
   concise rationale.
6. Run: python -m svyable.strategy_activate
7. Confirm that outputs/svyable_nasdaq_lo/<tag>/weights_today.csv and
   morning_report.md were created.
8. Append the decision and rationale to journal/YYYY-MM.md.
```

Required decision schema:

```json
{
  "as_of": "2026-07-03",
  "candidate_set_hash": "board hash",
  "candidate_id": "q23_hybrid_alpha",
  "confidence": 0.75,
  "reason": "Best expected alpha after cost with acceptable turnover and overlap."
}
```

`strategy_activate` rejects stale dates, mismatched hashes, unknown candidates, and ineligible selections. It writes exactly one canonical portfolio under `outputs/svyable_nasdaq_lo/`, which is the only path consumed by the Tastytrade rebalance workflow.

## Layer 3 — portfolio and execution review

After activation, inspect the canonical morning report and broker plan:

1. Confirm selected strategy, action, expected alpha, estimated cost, and turnover.
2. Review target weights, budget, concentration, factor/sleeve trust, and kill-switch state.
3. Run the Tastytrade dry-run/preflight from the Streamlit Rebalance page.
4. Keep execution human-triggered until the sandbox operating record and production gates pass.
5. After fills, reconcile intended, submitted, filled, and actual positions; backfill delayed transactions if necessary.

## Hard rules

- The agent chooses a registered candidate ID, never raw weights.
- Candidate weights are immutable after the board hash is produced.
- A strategy switch must clear its minimum-hold rule, turnover cap, expected-alpha floor, and cost-aware switch buffer.
- `hold_current` is always available and is preferred when the expected edge is weak.
- Strategy definitions and selector policy change only through reviewed code/config changes, never during the morning loop.
- If evaluation fails, yesterday's canonical weights remain in force.
- If agent activation fails, no new canonical weights are emitted and the human is paged.
- Tastytrade consumes only the canonical selected portfolio, never candidate directories.

## Trading-day timeline

| Time | What | Who |
|---|---|---|
| 07:30 | Refresh panel and evaluate registered strategy portfolios | deterministic code |
| 07:40 | Review candidate board and write hash-matched decision | Claude / PM |
| 07:45 | Validate and activate one canonical portfolio | deterministic code |
| 07:50 | Review morning report and Tastytrade dry-run plan | Claude / PM |
| 08:30 | Deadline: selected weights and reviewed order plan | — |
| 09:28 | Human-triggered sandbox/order submission during validation era | human + code |
| 16:15 | Fill, slippage, drift, and reconciliation review | code + Claude / PM |
