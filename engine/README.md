# Svyable Engine

The engine is a reusable daily alpha and portfolio harness for registered Q23-derived strategies. It computes complete candidate portfolios, compares them under a persisted PM policy, and emits one canonical portfolio for the Tastytrade workflow.

The top-level [`README.md`](../README.md) is canonical.

## Core layout

```text
svyable/
  panel.py                     canonical OHLCV panel and validation
  factors.py                   Q23-derived factor registry
  factor_library.py            maturity metadata and factor computation
  weighting.py                 purged causal IC state and factor allocation
  sleeves.py                   sleeve ensembles and stress priors
  ml.py                        optional purged nonlinear ML sleeve
  construct.py                 seats, tilt, projection, smoothing, no-trade bands
  risk.py                      volatility budget, drawdown throttle, overlays
  strategy_registry.py         complete named strategy recipes
  strategy_selector.py         candidate board and cost-aware selection
  strategy_activation.py       validated one-time canonical activation
  strategy_daily.py            scheduled candidate evaluation runner
  strategy_activate.py         activation CLI for agent mode
  pipeline.py                  reusable per-strategy orchestration
  tastytrade_sdk.py            typed Tastytrade broker adapter
  execution_control.py         ADV-aware planning, polling, reconciliation
  execution_quality.py         fills, fees, venues, and slippage
  ledger.py                    SQLite operational evidence
  streamlit_app.py             operations console
pages/
  1_Strategy_Selector.py       registry, policy, candidate board, activation
  2_Factor_Governance.py       IC and factor-governance evidence
```

## Setup

```bash
cd engine
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

## Daily workflow

Deterministic or manual mode:

```bash
python -m svyable.strategy_daily --start 2020-01-01
```

Agent mode:

```bash
python -m svyable.strategy_daily --start 2020-01-01
# Review outputs/strategy_selection/<tag>/candidate_board.csv
# Write outputs/strategy_selection/agent_decision.json
python -m svyable.strategy_activate
```

Evaluation without activation:

```bash
python -m svyable.strategy_daily --start 2020-01-01 --evaluate-only
```

The scheduled wrapper is `../ops/run_daily.sh`.

## Research and validation

```bash
python -m svyable.cli --start 2020-01-01 backtest --trials 20
python -m svyable.cli --start 2020-01-01 factors
python -m svyable.cli --start 2020-01-01 walkforward
python -m svyable.cli --out /tmp/svyable-smoke smoke
```

## Operations console

```bash
python -m svyable.ui
```

The selector GUI manages registered strategies and policy. It never edits raw weights. The agent and GUI may select only an eligible candidate ID from the immutable board. Tastytrade consumes only `outputs/svyable_nasdaq_lo/<tag>/` after activation.

## Safety

- Sandbox is the default.
- Candidate turnover uses actual Tastytrade positions when read-only broker access is available.
- `hold_current` is always available.
- Minimum-hold, cadence, turnover, expected-alpha, cost, risk, and kill-switch gates apply before selection.
- Agent decisions require the exact board date and hash.
- A board activates once; a later different decision is rejected.
- Production bulk submission remains disabled.

## Honesty ledger

- Seed-universe historical backtests may be survivorship-biased.
- Expected alpha is a causal candidate-comparison estimate, not a forecast guarantee.
- Daily-bar flow factors are proxies, not true order-book measurements.
- A registered strategy becomes operationally trusted only after walk-forward evidence and a sustained sandbox record.
