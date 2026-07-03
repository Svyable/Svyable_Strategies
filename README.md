# Svyable Strategies

Svyable Strategies is a daily cross-sectional alpha research, portfolio-management, and broker-operations platform derived from the strongest price-action ideas in [`Svyable/Q23_QUANT_SYSTEM_2`](https://github.com/Svyable/Q23_QUANT_SYSTEM_2).

```text
validated market panel
  -> governed factor library
  -> complete registered strategy portfolios
  -> causal chimera portfolios
  -> immutable candidate board
  -> deterministic / agent PM selection
  -> user-approved canonical portfolio
  -> Tastytrade sandbox execution and reconciliation
```

The objective is effective systematic trading, not complexity for its own sake: differentiated alpha sources, controlled beta participation, robust volatility and turbulence avoidance, honest transaction costs, observable decisions, and one safe execution boundary.

This README is the canonical project narrative and operating guide. Detailed institutional positioning and evidence standards are in [`docs/institutional_alpha_platform.md`](docs/institutional_alpha_platform.md).

## Current truth

Svyable is **paper-operational research and execution infrastructure**. It is not yet a live-capital track record.

Implemented:

- Vendor-agnostic daily OHLCV panel with validation, caching, and point-in-time processing discipline.
- Price-action, residual, defensive, reversal, liquidity, behavioral, and clearly labeled daily-flow proxy factors.
- Purged causal IC weighting with uncertainty, hit-rate, coverage, and redundancy controls.
- Complete strategy registry: every strategy owns factors, construction, concentration, risk, cost, cadence, and maturity.
- Correlation-cluster caps, score/equal/HRP/blended seat weighting, no-trade bands, and ADV-aware execution inputs.
- Volatility targeting, drawdown controls, structural turbulence, absorption ratio, breadth, panic state, and own-book kill switch.
- Fixed, inverse-volatility, and alpha/risk chimera portfolios with causal component-weight histories.
- Deterministic, manual, and two-phase agent selection with immutable candidate hashes and explicit user approval.
- Institutional scorecards covering alpha, beta, capture, tails, risk, turnover, and costs.
- Streamlit Strategy Selector, Factor Governance, Institutional Alpha Lab, broker, rebalance, and audit surfaces.
- Typed community `tastytrade` SDK adapter with sandbox preflight, submission, polling, cancellation, fills, slippage, delayed-fill recovery, reconciliation, and audit.

Not true yet:

- No live-capital performance is claimed.
- Production bulk submission from Streamlit remains disabled.
- The strategy and chimera registry has not yet accumulated a sustained Tastytrade sandbox operating record.
- Seed-universe historical tests remain survivorship-biased unless explicitly labeled point-in-time.
- Institutional metrics are engineering evidence, not promised future returns.

## Alpha architecture

The factor stack stays inside the current daily OHLCV and liquidity contract.

### Trend and continuation

- 12-1, intermediate, residual, and short residual momentum
- frog-in-the-pan / information-continuity momentum
- multi-horizon risk-adjusted trend
- residual trend t-statistic
- trend consistency, persistence, acceleration, and quality
- 52-week-high proximity, breakout, and volume-confirmed breakout
- efficiency ratio, EMA slope, and CAPM alpha

### Reversal and statistical state

- short-term and residual reversal
- Ornstein-Uhlenbeck z-score, predicted return, and momentum/reversion blend
- mean-reversion speed and disposition-state signals

### Defensive, beta, and resilience

- inverse volatility, downside volatility, and range volatility
- low beta, beta stability, and idiosyncratic volatility
- conditional downside-beta resilience
- upside/downside beta asymmetry
- drawdown and overnight-gap resilience
- low market correlation and correlation-shock resilience
- liquidity, turnover stability, skew, kurtosis, and lottery-risk controls

### Flow and nonlinear research

- daily-bar OFI, VPIN, Kyle, BVC, execution-quality, and flow-persistence proxies remain shadow research
- optional purged histogram-gradient-boosting ML sleeve for nonlinear interactions

Adding a factor does not silently change every portfolio. A strategy uses only its explicit factor set.

## Strategy registry

A strategy is a complete executable mandate, not a loose factor profile.

| Strategy | Institutional role | Default |
|---|---|---:|
| `q23_neural_alpha` | nonlinear broad alpha ensemble | Yes |
| `q23_hybrid_alpha` | diversified core alpha | Yes |
| `q23_concentrated` | 7–10-name high-conviction flagship | Yes |
| `q23_momentum_quality` | medium-horizon continuation | Yes |
| `q23_ou_mean_reversion` | short-horizon statistical reversal | Yes |
| `q23_defensive_alpha` | drawdown and beta defense | Yes |
| `q23_low_turnover` | capacity and implementation core | Yes |
| `q23_alpha_beta` | calm-regime beta participation with asymmetric defense | Yes |
| `q23_crash_resilient_momentum` | momentum alpha with crash controls | Yes |
| `q23_residual_alpha` | beta-stripped stock-selection alpha | Yes |
| `q23_dispersion_alpha` | cross-sectional relative-value opportunity | Yes |
| `q23_flow_alpha` | daily-bar microstructure research proxy | Experimental / off |

Definitions live in `engine/svyable/strategy_registry.py`.

Each mandate specifies:

- factor membership and sleeves;
- seats, concentration, and correlation-cluster caps;
- score and weight smoothing;
- no-trade band and transaction-cost assumptions;
- target and stressed volatility;
- turbulence thresholds and permitted risk-on boost;
- rebalance cadence and minimum holding period;
- maturity, pitch role, and regime profile.

## Chimera portfolios

A chimera is a convex combination of complete registered portfolios, materialized and evaluated as one candidate book.

| Chimera | Components | Method |
|---|---|---|
| `chimera_flagship_shield` | concentrated flagship + defensive alpha | fixed |
| `chimera_trend_reversion` | momentum quality + OU reversal | fixed |
| `chimera_all_weather` | hybrid + defensive + low turnover | fixed |
| `chimera_adaptive` | flagship + trend + reversal + defensive | inverse volatility |
| `chimera_institutional_alpha` | alpha/beta + crash-managed momentum + residual + defensive | alpha/risk |
| `chimera_opportunity_stack` | concentrated + dispersion + reversal + capacity | alpha/risk |

Dynamic chimeras use only lagged component returns. Component weights are bounded, smoothed, and persisted through time. Historical portfolio weights and transaction costs are rebuilt after component trade netting; today’s allocation is never applied retroactively to the full backtest.

Users may define additional chimeras through persisted policy data. The GUI and agent select only materialized candidate IDs; neither may author security weights.

## Volatility, turbulence, and beta control

The risk stack combines:

1. EWMA portfolio-volatility targeting;
2. market drawdown throttling;
3. a trailing-volatility overlay;
4. robust Mahalanobis cross-asset turbulence;
5. absorption ratio / systemic coupling;
6. market breadth deterioration;
7. a high-volatility drawdown panic state;
8. strategy-specific correlation-cluster caps;
9. an own-book drawdown kill switch.

The composite regime multiplier primarily removes exposure. A small, separately capped beta boost is allowed only when breadth is strong, turbulence is quiet, and the panic state is inactive. Defensive mandates disable that boost and use stricter floors.

Regime artifacts expose turbulence percentile, absorption, breadth, panic signal, composite risk, throttle, boost, and final multiplier.

## Candidate selection

Every enabled strategy runs through the full backtest and artifact pipeline. Eligible chimeras are then built from those results.

The selector compares:

- causal expected next-day alpha and confidence;
- cash-aware one-way turnover and largest required change;
- estimated costs and turnover penalty;
- current-position overlap;
- recent return, Sharpe, volatility, and drawdown;
- cadence, minimum-hold lock, and kill-switch state;
- cost-aware utility versus `hold_current`.

`hold_current` is always available. Evaluating daily does not imply trading daily.

### Position source

The daily job first attempts a read-only Tastytrade account snapshot. Candidate turnover is measured from actual equity holdings when available and from the last canonical target otherwise. The starting-position snapshot is bound to the candidate-board hash.

## Institutional scorecard

Every strategy and chimera persists:

- annualized return and volatility;
- Sharpe, Sortino, Calmar, and information ratio;
- maximum drawdown, skew, kurtosis, and daily tail ratio;
- regression alpha and market beta;
- market correlation;
- upside and downside capture and capture spread;
- active return and active volatility;
- position count, gross exposure, turnover, and cost evidence.

The **Institutional Alpha Lab** displays the candidate frontier, alpha-versus-beta plot, NAV evidence, current target weights, factor inventory, regime history, and causal chimera allocation history.

## Selection modes and approval

Policy lives at:

```text
engine/outputs/strategy_selection/policy.json
```

### Deterministic

Selects and activates the highest eligible cost-aware candidate, subject to switch and rebalance buffers.

### Manual

Selects one configured enabled registered strategy when it passes all gates.

### Agent

Agent mode is deliberately two-phase:

1. deterministic code writes an immutable strategy-and-chimera board;
2. the PM agent reviews board metrics and candidate artifacts;
3. the agent writes one hash-matched eligible proposal;
4. the GUI presents the proposal and supporting evidence;
5. the user approves or rejects it;
6. deterministic activation validates the date, hash, candidate, and eligibility;
7. exactly one canonical portfolio is emitted.

The agent may choose a strategy, chimera, or `hold_current`. It may not edit weights, factors, code, or policy during the morning review.

See `ops/CLAUDE_LOOP.md`.

## Canonical artifacts

Candidate board:

```text
outputs/strategy_selection/<tag>/candidate_board.csv
outputs/strategy_selection/<tag>/candidate_board.json
outputs/strategy_selection/<tag>/selection.json
outputs/strategy_selection/<tag>/agent_decision_template.json
outputs/strategy_selection/<tag>/activation.json
```

Per-candidate evidence may include:

```text
weights_today.csv
weights_history.csv
pnl_diag.csv
institutional_metrics.csv
factor_catalog.csv
regime.csv
component_weights_history.csv
execution_inputs.csv
meta.json
morning_report.md
```

Activated canonical portfolio:

```text
outputs/svyable_nasdaq_lo/<tag>/
```

Tastytrade consumes only the canonical activated path.

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

Evaluate and activate in deterministic/manual mode:

```bash
python -m svyable.strategy_daily --start 2020-01-01
```

Agent proposal and approved activation:

```bash
python -m svyable.strategy_daily --start 2020-01-01
# Review in Strategy Selector and Institutional Alpha Lab
python -m svyable.strategy_activate
```

Evaluate without activation:

```bash
python -m svyable.strategy_daily --start 2020-01-01 --evaluate-only
```

Research:

```bash
python -m svyable.cli --start 2020-01-01 backtest --trials 20
python -m svyable.cli --start 2020-01-01 factors
python -m svyable.cli --start 2020-01-01 walkforward
```

Launch the console:

```bash
python -m svyable.ui
```

Pages:

- **Strategy Selector** — recipes, policies, chimeras, candidate board, proposal, approval, activation
- **Factor Governance** — maturity, ICIR, hit rate, breadth, coverage, and weights
- **Institutional Alpha Lab** — alpha/beta frontier, captures, regime, factors, portfolio, and chimera history
- **Overview / Strategy** — operational health and canonical portfolio
- **Broker / Rebalance / Audit** — Tastytrade state, preflight, sandbox execution, fills, and reconciliation

## Safety invariants

- Sandbox is the default.
- Production bulk submission remains disabled.
- Candidate and component weights are deterministic and immutable after hashing.
- The agent selects only an eligible candidate ID.
- User approval is required before agent-mode activation.
- Strategy/chimera activation is one-time and idempotent per board.
- Actual broker positions are read-only during selection.
- `hold_current` is always available.
- Minimum-hold, cadence, turnover, alpha, cost, regime, and kill-switch gates apply before activation.
- Missing quotes, stale artifacts, missing ADV, or liquidity violations block broker preflight.
- Every order is normalized, audited, and broker-preflighted.
- Duplicate batches and duplicate transactions are blocked.
- `SVYABLE_ENABLE_LIVE=false` remains the default until production gates pass.

## Research and performance language

- **Q23 research result** — predecessor-harness evidence.
- **Svyable candidate backtest** — historical engineering evidence for one registered mandate.
- **Selection estimate** — causal comparison forecast, not a promised return.
- **Sandbox result** — produced through paper/sandbox execution.
- **Live result** — produced with real capital. None are claimed here.

Reference Q23 proof point: `q23_neural_alpha`, 2025 under contest constraints — 63.58% annual return, Sharpe 3.545, maximum drawdown -5.67%, and 58.02% net of the contest cost model. It motivates the port; it is not a live Svyable result.

## Production gates

No live-capital path until:

- point-in-time universe and survivorship controls cover the operating history;
- every mandate has walk-forward, subperiod, sensitivity, and capacity evidence;
- factor and strategy correlations are understood in calm and stressed regimes;
- multiple-testing controls accompany strategy and factor selection;
- candidate selection is reproducible from policy, inputs, artifacts, and hashes;
- Tastytrade authentication, fills, fees, slippage, delayed transactions, and reconciliation are reliable;
- a sustained sandbox record demonstrates holds, switches, chimeras, partial fills, and failure recovery.

## Repository map

```text
README.md                                      canonical narrative and operations guide
docs/institutional_alpha_platform.md           institutional architecture and evidence standard
engine/svyable/factor_institutional.py          beta, trend, and resilience extensions
engine/svyable/strategy_registry.py             complete strategy mandates
engine/svyable/strategy_blend.py                causal chimera engine
engine/svyable/strategy_selector.py             candidate board and PM policy
engine/svyable/turbulence.py                    turbulence, absorption, breadth, and panic
engine/svyable/pipeline.py                      reusable candidate pipeline and artifacts
engine/svyable/metrics.py                       institutional performance scorecard
engine/svyable/tastytrade_sdk.py                typed broker adapter
engine/svyable/pages/1_Strategy_Selector.py     proposal and approval GUI
engine/svyable/pages/2_Factor_Governance.py     factor governance GUI
engine/svyable/pages/3_Alpha_Lab.py             institutional observability GUI
engine/tests/                                   offline regression suite
ops/CLAUDE_LOOP.md                              morning agent and approval contract
```

## Next actions

1. Run all strategy and chimera candidates against the configured Tastytrade sandbox account.
2. Accumulate daily proposal, approval, hold/switch, turnover, fill, and slippage evidence.
3. Calibrate alpha, cost, component bounds, and switch buffers from that operating record.
4. Add point-in-time universe history and formal capacity/market-impact studies.
5. Retire or promote factors, strategies, and chimeras only through reviewed walk-forward evidence.
