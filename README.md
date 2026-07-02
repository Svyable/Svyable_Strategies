# Svyable Strategies

Svyable Strategies is the canonical home for converting the best ideas from [`Svyable/Q23_QUANT_SYSTEM_2`](https://github.com/Svyable/Q23_QUANT_SYSTEM_2) into a vendor-agnostic, broker-connected systematic trading operation.

```text
Q23 research alpha -> Svyable engine -> Tastytrade sandbox loop -> production-gated operation
```

Q23 is the predecessor research harness and the source of the strongest strategy ideas: factor libraries, IC-weighted alpha, ensemble sleeves, portfolio construction, cost-aware diagnostics, and PM review artifacts. Svyable Strategies keeps the useful research logic, removes Quantiacs-only assumptions, adds operational controls, and converts target weights into auditable Tastytrade order plans.

This README is the canonical project narrative, capability ledger, setup guide, and safety policy. When another document conflicts with it, this file wins.

## Current truth

Svyable Strategies is **paper-operational research infrastructure**, not a live-capital system.

Implemented today:

- Daily vendor-agnostic alpha engine in `engine/`.
- Canonical OHLCV panel and validation layer.
- Implemented subset of the broader Q23 factor library.
- Purged, causal IC weighting and sleeve meta-learning.
- Portfolio construction, risk budgeting, turnover controls, and morning artifacts.
- Persisted execution inputs: closing prices, dollar ADV, and the liquidity mask.
- Local paper broker, rebalancer, reconciliation, SQLite ledger, and health reporting.
- Tastytrade connectivity for account state, quotes, broker preflight, order lifecycle, and audit evidence.
- Tastytrade trade-history normalization with fill prices, fees, venues, and signed slippage.
- Streamlit operations console for strategy, broker, rebalance, order supervision, reconciliation, execution quality, and audit.
- Fully isolated sandbox and production output roots.

Not true yet:

- No live-capital performance is claimed.
- Production bulk submission from Streamlit is disabled.
- A sustained sandbox operating record has not yet been established.
- Deep-history seed-universe backtests remain survivorship-biased unless explicitly labeled as point-in-time.
- Live operation remains blocked until every production gate below passes.

## Canonical architecture

```text
DataProvider
  -> Panel(time x asset OHLCV)
  -> Factor registry
  -> Purged IC meta-learner
  -> Sleeve ensemble
  -> Composite score
  -> Seat selection / tilt / projection
  -> Risk stack
  -> Target weights
  -> Persisted execution inputs (price / ADV / liquidity)
  -> Rebalancer diff and ADV participation cap
  -> Broker preflight
  -> Tastytrade sandbox execution
  -> Order polling and trade-history capture
  -> Fill slippage / fees / venue evidence
  -> Reconciliation + ledger + dashboard + human PM review
```

The invariant is that strategy math does not care which vendor supplied the data or which broker receives an order. Vendor and broker details stay behind adapters.

## Relationship to Q23

| Layer | Q23 role | Svyable Strategies role |
|---|---|---|
| Research alpha | Source of the best ideas and proofs | Preserve, simplify, test, and port |
| Data | Quantiacs-centered research harness | Vendor-agnostic `DataProvider` model |
| Factors | Broad experimental library | Flat, testable, promotable registry |
| Weighting | IC/meta-learning research logic | Purged and causal production-shaped implementation |
| Portfolio | Contest/research portfolio construction | Broker-ready target weights |
| Execution | Stops at artifacts | Rebalancer, preflight, sandbox execution, fills, slippage, reconciliation |
| Review | CSV/dashboard research artifacts | Morning report, ledger, Streamlit console, health, drift, execution quality |

The immediate conversion target is Tastytrade: translate Q23-derived daily alpha targets into safe, reviewable, sandbox-first order plans.

## Capability status

| Capability | Status | Canonical note |
|---|---:|---|
| Q23 strategy ideas | Research source | Preserve concepts, not every implementation detail |
| Vendor-agnostic engine | Implemented | `engine/` is the active codebase |
| Factor library | Partially implemented | The Q23 research scope is larger than the promoted engine subset |
| IC meta-learning | Implemented | Purged and causal; no look-ahead shortcuts |
| Portfolio construction | Implemented | Scores to target weights with caps, smoothing, and no-trade logic |
| Risk stack | Implemented | Vol target, drawdown throttle, overlays, and kill-switch concepts |
| Execution-input artifact | Implemented | Daily price, dollar ADV, and liquidity state travel with each run |
| Tastytrade SDK adapter | Implemented / gated | Typed community SDK path for dashboard and order workflow |
| Legacy Tastytrade REST adapter | Retained | Supports existing DXLink, universe, and CLI integration during migration |
| Fill-quality ledger | Implemented | Transaction ID, broker order, quantity, price, reference, slippage, fees, and venue |
| Streamlit console | Implemented | Observability, ADV-aware plans, preflight, sandbox execution, polling, cancellation, reconciliation, fill quality, audit |
| Production Streamlit rebalance | Disabled | Requires completed gates and a sustained sandbox operating record |
| CLI rebalancer | Implemented / validating | Reference automation path while the dashboard operating record develops |
| PIT universe | Accumulating / gate | Live snapshots are honest from collection start; deep history remains incomplete |
| Live capital | Not active | Requires all gates below |

## Streamlit operations console

The console is a local, single-user PM surface. It reads the same strategy artifacts and SQLite ledger as the CLI and uses backend service boundaries so order construction never lives in the UI code.

### Install

```bash
cd engine
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Populate `engine/.env` with your own Tastytrade OAuth grant and account number:

```text
TASTY_CLIENT_SECRET=...
TASTY_REFRESH_TOKEN=...
TASTY_ACCOUNT_NUMBER=...
TASTY_IS_TEST=true
SVYABLE_ENV=sandbox
SVYABLE_OUTPUT_ROOT=outputs
SVYABLE_ENABLE_LIVE=false
```

Never commit `.env`. The repository ignores it.

### Launch

Run a current daily strategy build first so the dashboard has fresh targets and execution inputs:

```bash
cd engine
source .venv/bin/activate
svyable daily
python -m svyable.ui
```

Direct Streamlit launch is also supported:

```bash
streamlit run svyable/streamlit_app.py
```

The server binds to `127.0.0.1:8501` by default. Override with `SVYABLE_STREAMLIT_ADDRESS` and `SVYABLE_STREAMLIT_PORT` only when network exposure is intentional and separately secured.

### Dashboard surfaces

- **Overview** — run health, warnings, shadow NAV, paper equity, tracking drift, fill count, and slippage health.
- **Strategy** — latest targets, gross budget, sleeve trust, IC health, factor weights, metadata, and morning report.
- **Broker** — masked account identity, balances, positions, same-day orders, order-status lookup, guarded cancellation, reconciliation, and quotes.
- **Rebalance** — target-vs-position plan using persisted ADV/liquidity state, live quote validation, broker preflight, sandbox submission, polling, transaction capture, and post-order reconciliation.
- **Audit** — order ledger, fill-level slippage and fees, operational events, and append-only Tastytrade intent/preflight/response records.

### Dashboard safety invariants

- Sandbox is the default (`TASTY_IS_TEST=true`).
- The planner blocks on stale execution artifacts, missing quotes, missing ADV, or liquidity-mask violations.
- ADV participation caps are applied before broker preflight.
- Every order is normalized and validated in the backend.
- Every order is broker-preflighted before submission.
- Any broker warning or error blocks submission.
- Submitted sandbox orders are polled and followed by broker-vs-target reconciliation.
- Fill capture is linked by broker order ID and scored against the plan reference price.
- Positive slippage means worse execution for both buys and sells.
- Fill-capture failures are logged as operational warnings rather than silently discarded.
- Intent, preflight, response, cancellation, and fill evidence are persisted locally.
- Account numbers are masked in read-only dashboard views.
- Sandbox submission and cancellation require acknowledgement and typed confirmation phrases.
- Production cancellation requires the configured account number.
- Production bulk submission from Streamlit remains disabled.
- `SVYABLE_ENABLE_LIVE=false` remains the default and must stay false until the production gates pass.

## Tastytrade adapter split

Two adapters coexist during migration:

- `svyable/tastytrade.py` — the existing low-level REST path used by DXLink candles, universe snapshots, and current CLI workflows.
- `svyable/tastytrade_sdk.py` — the typed community SDK path used by the Streamlit dashboard and its broker-preflight workflow.

This is deliberate. It avoids destabilizing the working data/universe path while the SDK adapter is validated. Consolidation should happen only after parity tests cover authentication, quotes, accounts, positions, orders, transactions, universe snapshots, and DXLink token behavior.

## Production gates

No live-capital operation until all three gates pass.

### Gate 1 - Data correctness

- Point-in-time universe data is wired into the daily path.
- Staleness checks understand market holidays and provider lag.
- Restatements and vendor changes are detected and logged.
- Every backtest states data source, range, universe, and survivorship status.

### Gate 2 - Strategy reproducibility

- Golden weights protect behavior-changing edits.
- Causality tests prevent future leakage.
- Walk-forward reports accompany parameter changes.
- Factor promotion requires IC/IR, hit-rate, stability, and OOS evidence.

### Gate 3 - Execution safety

- Tastytrade authentication and token refresh are reliable.
- Pre-trade checks enforce leverage, cash, ADV participation, and position limits.
- Intended, preflighted, submitted, filled, and actual positions reconcile.
- Fill slippage, fees, and venue data are observable and reviewed.
- Shadow-vs-paper drift is visible and within an accepted operating band.
- Failure escalation and a dead-man heartbeat are operational.
- A sustained sandbox record demonstrates repeatable daily operation.

## Daily operating loop

1. **Session/bootstrap** — validate credentials, tokens, account, and universe state.
2. **Daily compute** — build the panel and emit targets plus price/ADV/liquidity evidence.
3. **PM review** — inspect data health, risk, drift, factors, targets, and proposed orders.
4. **Broker preflight** — estimate buying-power and fee effects; block on warnings/errors.
5. **Sandbox execution** — submit, poll, capture fills, score slippage, record account equity, and reconcile.
6. **Production operation** — unavailable until every gate passes.

## Performance language

- **Q23 research result** — produced by the predecessor harness.
- **Svyable engineering validation** — verifies mechanics and may use biased/incomplete data.
- **Paper result** — produced by sandbox, local paper, or simulated fills.
- **Live result** — produced with real capital. None are claimed here.

Reference Q23 proof point: `q23_neural_alpha`, 2025 under full contest constraints — 63.58% annual, Sharpe 3.545, MaxDD -5.67%, and 58.02% net of contest-model costs. This motivates the conversion effort; it is not a live Svyable result.

## Development discipline

- Strategies are configs where possible, not forks.
- Vendor details remain behind adapters.
- Sandbox, production, caches, ledgers, and artifacts remain isolated.
- Any weight-changing edit preserves golden weights or deliberately re-blesses them with evidence.
- No result is quoted without data source, range, universe, and execution status.
- UI convenience never bypasses rebalancer, broker-preflight, ledger, or audit boundaries.

## Repository map

```text
README.md                          canonical narrative, setup, status, and gates
engine/svyable/                    active strategy and operations implementation
engine/svyable/streamlit_app.py    dashboard composition
engine/svyable/dashboard_*.py      dashboard services and views
engine/svyable/execution_control.py ADV-aware planning, polling, reconciliation
engine/svyable/execution_quality.py fill normalization and signed slippage
engine/svyable/tastytrade_sdk.py   typed community-SDK broker adapter
engine/svyable/tastytrade.py       retained REST/DXLink-compatible adapter
engine/tests/                      offline and regression tests
ops/CLAUDE_LOOP.md                 scheduled review/supervision loop
```

## Next actions

1. Run a secret-managed sandbox integration test against the configured account.
2. Add retry/backfill logic for transaction history that appears after the initial poll window.
3. Add explicit slippage budgets and escalation thresholds by order size/liquidity bucket.
4. Accumulate point-in-time universe snapshots and source historical membership data.
5. Establish a sustained paper operating record before considering any live-capital path.
