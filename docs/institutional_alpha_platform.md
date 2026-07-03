# Svyable institutional alpha platform

## Positioning

Svyable is a daily cross-sectional research, portfolio-management, and broker-operations platform built around explicit price-action characteristics, causal validation, complete strategy mandates, adaptive chimera portfolios, and one controlled Tastytrade execution boundary.

The platform is designed to demonstrate the engineering and research qualities expected in an institutional systematic process:

- reproducible signal definitions;
- separation of research, portfolio construction, selection, and execution;
- causal and point-in-time calculations;
- multiple-testing and IC governance;
- explicit turnover, cost, liquidity, and concentration controls;
- observable alpha, beta, capture, tail, and regime behavior;
- immutable morning proposals and human-approved activation;
- complete audit trails from candidate weights to fills and reconciliation.

It does not claim an institutional track record. Backtests, candidate estimates, sandbox results, and live results must remain separately labeled.

## Alpha architecture

### Price-action factors

The active daily-data contract supports independent signal families rather than a single monolithic score:

- classic and residual momentum;
- intermediate and multi-horizon trend;
- trend consistency, significance, breakout, and volume confirmation;
- short-term and residual reversal;
- Ornstein-Uhlenbeck state and predicted reversion;
- low volatility, idiosyncratic volatility, downside risk, and beta stability;
- downside beta, upside/downside beta asymmetry, and correlation-shock resilience;
- drawdown and overnight-gap resilience;
- liquidity, implementation quality, and turnover stability;
- clearly labeled daily-bar flow proxies;
- optional nonlinear interactions through the purged ML sleeve.

Every factor is oriented consistently, cross-sectionally normalized, evaluated on eligible pairwise observations, purged by forecast horizon, and assigned proven or shadow maturity.

### Complete strategy mandates

A registered strategy owns its factor set, construction parameters, target volatility, concentration, cluster caps, cadence, transaction-cost assumptions, and regime behavior.

Institutional additions include:

- **Alpha + Beta Capture** — broad upside participation with beta-asymmetry and resilience controls;
- **Crash-Resilient Momentum** — trend alpha combined with downside-beta, gap, drawdown, and correlation-shock protection;
- **Residual Alpha** — beta-stripped trend and reversal with low-correlation and idiosyncratic-risk controls;
- **Dispersion Alpha** — adaptive breadth and relative-value stock selection when cross-sectional opportunity is wide.

These complement the concentrated flagship, diversified hybrid, neural ensemble, momentum, OU reversal, defensive, low-turnover, and experimental flow books.

## Chimera portfolios

A chimera is a convex combination of complete registered portfolios, not an arbitrary weight-editing surface.

Supported methods:

- **fixed** — static mandate allocation;
- **inverse volatility** — causal risk balancing from lagged component returns;
- **alpha/risk** — inverse volatility adjusted by clipped lagged Sharpe evidence and a component-diversification multiplier.

Dynamic component weights are:

1. estimated only from lagged returns;
2. projected onto explicit minimum and maximum bounds;
3. smoothed to control allocation turnover;
4. applied historically before blended P&L is calculated;
5. costed as one netted portfolio;
6. persisted as `component_weights_history.csv`.

The morning agent may select a materialized chimera candidate, but it may not author component or security weights. User approval and hash-validated activation remain required in agent mode.

## Volatility and turbulence control

The risk stack combines:

- EWMA portfolio volatility targeting;
- market and own-book drawdown controls;
- robust Mahalanobis turbulence;
- absorption ratio / systemic coupling;
- cross-sectional market breadth;
- a high-volatility drawdown panic state;
- portfolio correlation-cluster caps;
- a final own-book kill switch.

The composite regime multiplier primarily removes risk. A small separately capped boost is available only when market breadth is strong, turbulence is quiet, and the panic state is inactive. Individual strategy mandates can disable the boost or use stricter floors and thresholds.

## Institutional scorecard

Every strategy and chimera persists a common scorecard:

- annualized return and volatility;
- Sharpe, Sortino, Calmar, and information ratio;
- maximum drawdown and daily tail ratio;
- regression alpha and market beta;
- market correlation;
- upside and downside capture;
- capture spread;
- active return and active volatility;
- turnover, costs, gross exposure, and position count.

The Streamlit **Institutional Alpha Lab** presents the candidate frontier, alpha-versus-beta plot, regime state, factor inventory, target weights, NAV evidence, and causal chimera allocation history.

## Morning PM loop

1. Refresh and validate the shared market panel.
2. Read actual Tastytrade positions when available.
3. Evaluate every enabled complete strategy.
4. Materialize every eligible chimera from component results.
5. Persist the immutable candidate board and institutional artifacts.
6. Let deterministic policy or the PM agent recommend one eligible candidate.
7. Review the proposal in the GUI, including regime, alpha/beta, capture, cost, and turnover evidence.
8. Activate once through the hash-validated approval boundary.
9. Preflight the canonical target against Tastytrade and liquidity controls.
10. Reconcile fills, fees, slippage, drift, and delayed transactions.

## Evidence required before an institutional claim

- point-in-time universe coverage and survivorship controls;
- walk-forward and subperiod stability for every strategy mandate;
- sensitivity to formation windows, costs, and rebalance rules;
- capacity estimates based on realistic ADV participation and market impact;
- factor and strategy correlation through calm and stressed regimes;
- deflated-Sharpe or comparable multiple-testing controls;
- documented sandbox execution across holds, switches, and partial fills;
- reproducibility from immutable configs, inputs, and artifact hashes;
- a clearly separated live-capital record before any live-performance statement.
