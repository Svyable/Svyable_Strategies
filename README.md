# Svyable Strategies

Svyable Strategies converts the strongest price-action and portfolio ideas from [`Svyable/Q23_QUANT_SYSTEM_2`](https://github.com/Svyable/Q23_QUANT_SYSTEM_2) into a flexible daily strategy platform with one canonical Tastytrade execution path.

```text
shared market panel
  -> registered Q23 strategy candidates
  -> complete candidate portfolios
  -> cost-aware PM/agent selection
  -> one canonical target portfolio
  -> Tastytrade sandbox execution and reconciliation
```

The goal is not maximum conceptual complexity. The goal is an effective, inspectable system that can backtest distinct strategies, compare their next-day opportunity against their trading cost and current holdings, select one safely, and improve through reviewed daily iterations.

This README is the canonical project narrative, operating guide, capability ledger, and safety policy. When another document disagrees, this file wins.

## Current truth

Svyable Strategies is **paper-operational research and execution infrastructure**. It is not yet a live-capital system.

Implemented:

- Vendor-agnostic daily OHLCV panel with validation and caching.
- Q23-derived price-action, behavioral, defensive, reversal, and daily-flow factors.
- Purged causal IC weighting, sleeve ensembles, portfolio construction, and risk budgeting.
- First-class strategy registry: each strategy owns its factor set, horizons, smoothing, seats, no-trade band, risk budget, cadence, and maturity.
- Daily evaluation of multiple complete candidate portfolios on one shared data panel.
- Cost-aware strategy selection using expected alpha, turnover, estimated trading cost, current-position overlap, risk, cadence, and minimum-hold rules.
- Deterministic, manual, and two-phase agent selection modes.
- Read-only Tastytrade positions used for turnover/rebalance calculations when credentials are available; canonical prior targets are the fallback.
- One canonical selected portfolio under `outputs/svyable_nasdaq_lo/` for all Tastytrade execution workflows.
- Streamlit strategy-selector, factor-governance, broker, rebalance, and audit surfaces.
- Typed community `tastytrade` SDK adapter, sandbox preflight/submission, polling, cancellation, fill capture, slippage, backfill, reconciliation, and audit.
- Duplicate strategy activation, duplicate rebalance batches, duplicate transactions, stale decisions, and ineligible agent decisions are blocked.

Not true yet:

- No live-capital performance is claimed.
- Production bulk submission from Streamlit is disabled.
- The registered strategy set has not yet accumulated a sustained Tastytrade sandbox operating record.
- Historical seed-universe tests remain survivorship-biased unless explicitly labeled point-in-time.
- Agent-selected portfolios remain subject to deterministic eligibility and execution gates.

## Strategy registry

A strategy is a complete executable recipe, not merely a factor profile.

The active registry includes:

| Strategy | Purpose | Default |
|---|---|---:|
| `q23_neural_alpha` | Broad Q23 behavioral/price-action ensemble with nonlinear ML sleeve | Yes |
| `q23_hybrid_alpha` | Balanced momentum, defensive, OU/reversal, and daily-flow ensemble | Yes |
| `q23_concentrated` | Contest-identity flagship: 7-10 names at roughly 10% apiece, full Q23 ensemble, concentration via construction | Yes |
| `q23_momentum_quality` | Trend continuation and momentum-quality strategy | Yes |
| `q23_ou_mean_reversion` | Faster residual reversal and OU strategy | Yes |
| `q23_defensive_alpha` | Lower-risk, lower-volatility stressed-regime candidate | Yes |
| `q23_low_turnover` | Slow-moving ensemble with wider no-trade bands | Yes |
| `q23_flow_alpha` | Daily-bar order-flow proxy strategy | Experimental / off |

Definitions live in `engine/svyable/strategy_registry.py`. Adding a factor to the factor registry does not silently alter every strategy. A factor affects a strategy only when that strategy explicitly includes it.

Each registered strategy specifies:

- Factors and sleeves
- Portfolio seats and concentration
- Score and weight smoothing
- No-trade band
- Target volatility and risk limits
- Expected rebalance cadence
- Minimum holding period before switching
- Transaction-cost assumptions
- Maturity and default-enabled state

## Daily strategy selection

Every candidate is run through the full pipeline and produces its own target weights, backtest diagnostics, risk state, factor evidence, and execution inputs.

The selector compares:

- Causal expected next-day alpha
- Alpha confidence and observation history
- One-way turnover from current holdings, including the cash leg
- Largest required weight change
- Estimated transaction cost
- Sign-aware current-position overlap
- Recent 63-day and 252-day return
- Recent Sharpe, volatility, and drawdown
- Typical recent turnover
- Trading-session rebalance cadence
- Minimum-hold lock
- Kill-switch state

A `hold_current` candidate is always included. A strategy switch must beat holding after costs and the configured switch buffer. Choosing daily does **not** imply trading daily.

### Position source

The selector first attempts a read-only Tastytrade account snapshot. When available, candidate turnover is measured against actual equity positions. If broker state is unavailable, it falls back to the last canonical selected target.

The exact starting-position snapshot is bound to the candidate-board hash and reused during activation.

## Selection modes

Policy is persisted at:

```text
engine/outputs/strategy_selection/policy.json
```

### Deterministic

The selector activates the highest eligible cost-aware utility candidate. It holds the existing portfolio unless a candidate clears the switch/rebalance buffer.

### Manual

The configured enabled strategy is selected when it passes all eligibility gates. The GUI never permits direct weight editing.

### Agent

Agent mode is deliberately two-phase:

1. Deterministic code evaluates candidates and writes an immutable board.
2. Claude or another PM agent chooses one eligible `candidate_id`.
3. Deterministic activation validates the date, board hash, candidate identity, and eligibility.
4. One canonical portfolio is emitted.

The agent may choose a strategy. It may not construct weights, edit factors, mutate config, or bypass risk/execution controls.

Candidate artifacts:

```text
outputs/strategy_selection/<tag>/candidate_board.csv
outputs/strategy_selection/<tag>/candidate_board.json
outputs/strategy_selection/<tag>/selection.json
outputs/strategy_selection/<tag>/agent_decision_template.json
outputs/strategy_selection/<tag>/activation.json
```

Canonical activated artifacts:

```text
outputs/svyable_nasdaq_lo/<tag>/weights_today.csv
outputs/svyable_nasdaq_lo/<tag>/weights_history.csv
outputs/svyable_nasdaq_lo/<tag>/execution_inputs.csv
outputs/svyable_nasdaq_lo/<tag>/morning_report.md
outputs/svyable_nasdaq_lo/<tag>/meta.json
```

Tastytrade reads only the canonical path. Candidate directories are never executable order sources.

## Architecture

```text
DataProvider
  -> shared Panel(time x asset OHLCV)
  -> shared compatible factor caches
  -> Strategy Registry
      -> Q23 Neural Alpha candidate
      -> Hybrid candidate
      -> Momentum candidate
      -> OU/reversal candidate
      -> Defensive candidate
      -> Low-turnover candidate
  -> per-strategy IC / sleeves / construction / risk / backtest
  -> immutable Candidate Board
  -> deterministic, manual, or hash-validated agent selection
  -> idempotent activation
  -> canonical target weights + price / ADV / liquidity evidence
  -> target-vs-actual rebalance plan
  -> ADV caps and Tastytrade broker preflight
  -> sandbox submission / polling / fills
  -> slippage / fees / reconciliation / ledger / PM review
```

Strategy math remains independent of the data vendor and broker. Broker details stay behind adapters, and strategy selection stays separate from order construction.

## Install

```bash
cd engine
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Populate `engine/.env`:

```text
TASTY_CLIENT_SECRET=...
TASTY_REFRESH_TOKEN=...
TASTY_ACCOUNT_NUMBER=...
TASTY_IS_TEST=true
SVYABLE_ENV=sandbox
SVYABLE_OUTPUT_ROOT=outputs
SVYABLE_ENABLE_LIVE=false
SVYABLE_SLIPPAGE_WARN_BPS=15
SVYABLE_SLIPPAGE_CRITICAL_BPS=30
```

Never commit `.env`.

## Run

### Evaluate and select automatically

```bash
cd engine
source .venv/bin/activate
python -m svyable.strategy_daily --start 2020-01-01
```

In deterministic or manual mode, this evaluates candidates and activates one canonical portfolio.

### Agent mode

```bash
python -m svyable.strategy_daily --start 2020-01-01
# Agent or PM reviews candidate_board.csv and writes agent_decision.json
python -m svyable.strategy_activate
```

The activation command rejects stale hashes, unknown or ineligible candidates, and attempts to change an already activated board.

### Evaluate without activation

```bash
python -m svyable.strategy_daily --start 2020-01-01 --evaluate-only
```

### Backtest and research

```bash
python -m svyable.cli --start 2020-01-01 backtest --trials 20
python -m svyable.cli --start 2020-01-01 factors
python -m svyable.cli --start 2020-01-01 walkforward
```

### Launch the PM console

```bash
python -m svyable.ui
```

The Streamlit multipage console includes:

- **Strategy Selector** — inspect recipes, edit policy, rerun candidates, review the board, write a decision, and activate
- **Factor Governance** — factor maturity, ICIR, hit rate, breadth, coverage, and weights
- **Overview** — run health, drift, warnings, and execution quality
- **Strategy** — canonical selected portfolio and morning report
- **Broker** — account, positions, orders, quotes, cancellation, and reconciliation
- **Rebalance** — ADV-aware target-vs-actual plan, broker preflight, and sandbox submission
- **Audit** — orders, fills, slippage, fees, delayed-fill backfill, and operational events

## Safety invariants

- Sandbox is the default.
- The agent selects only registered candidates; it never supplies weights.
- Candidate boards are immutable and hash-addressed.
- Strategy activation is idempotent and one-time per board.
- Actual broker positions are read-only during selection.
- `hold_current` is always available.
- Minimum-hold, cadence, turnover, alpha, kill-switch, and cost-aware buffer gates apply before selection.
- Stale execution artifacts, missing quotes, missing ADV, and liquidity violations block broker preflight.
- ADV participation limits apply before order submission.
- Every sandbox order is normalized, audited, and broker-preflighted.
- Broker warnings or errors block submission.
- Duplicate rebalance batches and duplicate fill transactions are blocked.
- Production bulk submission remains disabled.
- `SVYABLE_ENABLE_LIVE=false` remains the default until all production gates pass.

## Factor and IC principles

The factor stack intentionally emphasizes effective price action rather than accumulating complexity for its own sake.

- Missing observations remain missing during IC estimation.
- IC is evaluated only on pairwise-valid tradable assets.
- IC is purged before it can affect weights.
- Factor trust accounts for IC mean, uncertainty, hit rate, coverage, and redundancy.
- Daily-bar OFI/VPIN/Kyle/BVC measures remain clearly identified as proxies.
- Shadow factors and the ML sleeve have no guaranteed allocation.
- Strategy definitions choose which factors matter; research additions do not silently alter production candidates.

See `docs/factor_governance.md`.

## Daily PM loop

1. Refresh and validate the shared panel.
2. Read actual Tastytrade positions when available.
3. Compute all enabled registered candidate portfolios.
4. Write the immutable candidate board.
5. Select deterministically, manually, or through a hash-validated agent decision.
6. Activate exactly one canonical portfolio.
7. Review the canonical morning report and Tastytrade dry-run plan.
8. Human-trigger sandbox execution during the validation era.
9. Poll, capture/backfill fills, score slippage, and reconcile actual positions.
10. Feed the evidence into the next reviewed strategy iteration.

The detailed agent contract is in `ops/CLAUDE_LOOP.md`.

## Production gates

No live-capital operation until:

### Data correctness

- Point-in-time universe data covers the operating history.
- Staleness, holidays, restatements, and vendor changes are observable.
- Every result states source, range, universe, and survivorship status.

### Strategy reproducibility

- Each registered strategy has walk-forward and sensitivity evidence.
- Behavior-changing edits are protected by regression/golden tests.
- Candidate selection is reproducible from board, policy, state, and position snapshot.
- Agent choices remain within the immutable candidate set.

### Execution safety

- Tastytrade authentication and refresh are reliable.
- Intended, preflighted, submitted, filled, and actual positions reconcile.
- Slippage, fees, delayed fills, and drift are observable.
- Failure escalation and heartbeat monitoring are operational.
- A sustained sandbox record demonstrates repeatability across strategy switches and holds.

## Performance language

- **Q23 research result** — produced by the predecessor harness.
- **Svyable candidate backtest** — historical engineering/research evidence for a registered strategy.
- **Selection estimate** — causal forecast used to compare candidates; not a promised return.
- **Sandbox result** — produced through paper/sandbox execution.
- **Live result** — produced with real capital. None are claimed here.

Reference Q23 proof point: `q23_neural_alpha`, 2025 under contest constraints — 63.58% annual, Sharpe 3.545, MaxDD -5.67%, and 58.02% net of contest-model costs. It motivates the port; it is not a live Svyable result.

## Repository map

```text
README.md                                   canonical narrative and operations guide
engine/svyable/strategy_registry.py         complete registered strategy recipes
engine/svyable/strategy_selector.py         candidate evaluation and policy selection
engine/svyable/strategy_activation.py       validated one-time canonical activation
engine/svyable/strategy_daily.py            weekday candidate runner
engine/svyable/strategy_activate.py         activation CLI
engine/svyable/pipeline.py                  reusable strategy pipeline
engine/svyable/factors.py                   Q23-derived flat factor registry
engine/svyable/weighting.py                 purged causal IC implementation
engine/svyable/tastytrade_sdk.py            typed community-SDK broker adapter
engine/svyable/execution_control.py          planning, polling, and reconciliation
engine/svyable/execution_quality.py          fill normalization and slippage
engine/svyable/pages/1_Strategy_Selector.py  PM/agent strategy GUI
engine/svyable/pages/2_Factor_Governance.py  factor governance GUI
engine/tests/                                offline regression suite
ops/CLAUDE_LOOP.md                           scheduled agent/PM contract
```

## Next actions

1. Run the registered candidate board against the real Tastytrade sandbox account.
2. Accumulate daily candidate, selection, hold/switch, turnover, and execution evidence.
3. Calibrate selector alpha/cost/switch buffers from the sandbox record rather than intuition.
4. Add or retire Q23 strategy recipes through reviewed registry changes and walk-forward evidence.
5. Establish a sustained sandbox operating record before considering any live-capital path.
