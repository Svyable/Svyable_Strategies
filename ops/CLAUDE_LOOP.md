# Running Svyable as a daily PM loop

The design principle is strict: **deterministic code computes complete candidate portfolios; the PM agent may choose only among those candidates.** The agent never creates security weights, edits factors, changes parameters, or bypasses execution controls during the morning loop.

## Layer 1 — deterministic candidate evaluation

```bash
cd ~/Svyable_Strategies/engine
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -r requirements.txt
cp ../ops/com.svyable.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.svyable.daily.plist
```

Every weekday, `ops/run_daily.sh` executes:

```bash
python -m svyable.strategy_daily --start 2020-01-01
```

The job refreshes one shared market panel, evaluates every enabled registered strategy, materializes eligible chimera portfolios, and writes:

```text
outputs/strategy_selection/<tag>/candidate_board.csv
outputs/strategy_selection/<tag>/candidate_board.json
outputs/strategy_selection/<tag>/selection.json
outputs/strategy_selection/<tag>/agent_decision_template.json
```

Every candidate is a complete portfolio with its own factors, construction, risk, cadence, and cost assumptions. Candidate directories also persist:

```text
institutional_metrics.csv
pnl_diag.csv
weights_today.csv
factor_catalog.csv                 # individual strategies
component_weights_history.csv      # dynamic chimeras
regime.csv                          # registered strategies
```

The board includes expected next-day alpha, confidence, estimated cost, cash-aware one-way turnover, current-position overlap, volatility, drawdown, cadence state, hold lock, and cost-aware utility.

Selection policy lives at:

```text
outputs/strategy_selection/policy.json
```

Supported modes:

- `deterministic` — rank candidates and activate immediately;
- `manual` — use the configured enabled registered strategy when eligible;
- `agent` — emit the board, then wait for a fresh hash-matched proposal and human approval.

## Layer 2 — Claude or PM proposal

In agent mode, schedule the PM review after the candidate board exists:

```text
Svyable institutional strategy-selection review.

1. Read the newest outputs/strategy_selection/*/candidate_board.csv.
2. Consider only rows where eligible=true.
3. For the strongest single strategies and chimeras, read each output_dir's
   institutional_metrics.csv. For dynamic chimeras also read
   component_weights_history.csv.
4. Compare expected alpha, regression alpha, beta, information ratio,
   upside/downside capture, capture spread, volatility, drawdown, tail ratio,
   turnover, estimated cost, overlap, cadence, and regime state.
5. A chimera earns selection only when its diversification, capture profile,
   stability, and netted implementation improve on its components. Do not select
   a blend merely because it contains more strategies.
6. Prefer hold_current when no candidate has a robust edge after costs, when the
   regime multiplier is defensive, or when a proposed switch depends on a weak
   short sample.
7. Never edit weights, factors, strategy code, or policy during this review.
8. Write outputs/strategy_selection/agent_decision.json with the exact board
   as_of date, candidate_set_hash, one eligible candidate_id, confidence, and a
   concise evidence-based rationale.
9. Present the proposal in the Strategy Selector and Institutional Alpha Lab for
   user approval. Do not activate without approval.
10. After approval, run: python -m svyable.strategy_activate
11. Confirm outputs/svyable_nasdaq_lo/<tag>/weights_today.csv and
    morning_report.md were created.
12. Append the proposal, approval, and rationale to journal/YYYY-MM.md.
```

Required decision schema:

```json
{
  "as_of": "2026-07-03",
  "candidate_set_hash": "board hash",
  "candidate_id": "chimera_institutional_alpha",
  "confidence": 0.75,
  "reason": "Best alpha/capture profile after costs with stable causal component weights."
}
```

`strategy_activate` rejects stale dates, mismatched hashes, unknown candidates, ineligible selections, and attempts to change a board after activation. It writes exactly one canonical portfolio under `outputs/svyable_nasdaq_lo/`, the only path consumed by Tastytrade.

## Layer 3 — portfolio and execution review

After activation:

1. Confirm selected strategy or chimera, action, expected alpha, estimated cost, turnover, alpha/beta scorecard, and current regime multiplier.
2. Review target weights, budget, concentration, correlation-cluster caps, factor/sleeve trust, and kill-switch state.
3. Run the Tastytrade dry-run/preflight from the Streamlit Rebalance page.
4. Keep execution human-triggered until the sandbox operating record and production gates pass.
5. After fills, reconcile intended, submitted, filled, and actual positions; backfill delayed transactions when necessary.

## Hard rules

- The agent chooses an immutable candidate ID, never security weights.
- Candidate weights are immutable after the board hash is produced.
- Dynamic chimera component histories are causal, lagged, bounded, and persisted.
- A switch must clear minimum-hold, cadence, turnover, alpha, kill-switch, and cost-aware buffer gates.
- `hold_current` is always available and preferred when evidence is weak.
- Strategy definitions and policy change only through reviewed code/config changes, never during the morning review.
- If evaluation fails, yesterday's canonical weights remain in force.
- If proposal validation or activation fails, no new canonical weights are emitted.
- Tastytrade consumes only the canonical selected portfolio, never candidate directories.

## Trading-day timeline

| Time | What | Who |
|---|---|---|
| 07:30 | Refresh panel; evaluate strategies and chimeras | deterministic code |
| 07:40 | Review frontier, institutional metrics, regime, and blend history | Claude / PM |
| 07:45 | Present one proposal for approval | Claude / PM → user |
| 07:50 | Validate and activate approved canonical portfolio | deterministic code |
| 08:00 | Review morning report and Tastytrade dry-run plan | Claude / PM |
| 08:30 | Deadline: approved weights and reviewed order plan | — |
| 09:28 | Human-triggered sandbox submission during validation era | human + code |
| 16:15 | Fill, slippage, drift, and reconciliation review | code + Claude / PM |
