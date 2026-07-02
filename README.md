# Svyable Strategies

Svyable Strategies is the canonical home for converting the best ideas from [`Svyable/Q23_QUANT_SYSTEM_2`](https://github.com/Svyable/Q23_QUANT_SYSTEM_2) into a vendor-agnostic, broker-connected systematic trading operation.

The project’s north star is simple:

```text
Q23 research alpha -> Svyable engine -> Tastytrade paper loop -> production-gated live operation
```

Q23 is the predecessor research harness. It proved the core ideas: factor libraries, IC-weighted alpha, ensemble sleeves, portfolio construction, cost-aware diagnostics, and PM review artifacts. Svyable Strategies is the conversion layer: it keeps the useful research logic, removes Quantiacs-only assumptions, adds execution plumbing, and turns daily target weights into broker-ready orders.

## Current truth

Svyable Strategies is **paper-operational research infrastructure**, not a live-capital system yet.

What exists today:

- A working `engine/` package for daily alpha generation.
- A canonical panel model for OHLCV data.
- A flat factor registry with the currently implemented subset of the broader Q23 strategy ideas.
- Purged IC weighting with causal shifts and recency weighting.
- Sleeve ensemble construction, optional ML sleeve, risk stack, construction logic, and morning reports.
- Broker abstractions plus local paper execution and Tastytrade integration work.
- Sandbox and production environment separation for outputs, caches, and ledgers.
- Golden-weight and causality-oriented testing discipline.

What is not true yet:

- It is not trading live capital.
- It does not yet have production-grade point-in-time NASDAQ universe data wired as the default live record.
- Performance claims are not live results.
- Current seed-universe backtests are engineering validation unless explicitly labeled otherwise.
- Tastytrade execution must remain dry-run or paper-gated until the production gates below are passed.

## Canonical architecture

```text
DataProvider
  ↓
Panel(time x asset OHLCV)
  ↓
Factor registry
  ↓
Purged IC meta-learner
  ↓
Sleeve ensemble
  ↓
Composite score
  ↓
Seat selection / tilt / projection
  ↓
Risk stack: vol target x drawdown throttle x overlays
  ↓
Target weights
  ↓
Rebalancer diff
  ↓
BrokerConnector
  ↓
Tastytrade orders / fills / reconciliation
  ↓
Ledger + morning report + human PM review
```

The invariant: strategy math should not care which vendor supplied the data or which broker receives the order. Vendors belong behind adapters. The research logic belongs in the engine.

## Relationship to Q23

`Q23_QUANT_SYSTEM_2` is the research source of truth for the best alpha ideas. It is valuable because it contains a mature Quantiacs-oriented research harness and the strategy concepts we want to preserve.

Svyable Strategies exists to convert those ideas into a real operating system:

| Layer | Q23 role | Svyable Strategies role |
|---|---|---|
| Research alpha | Source of best ideas and proofs | Preserve, simplify, and port the ideas |
| Data | Quantiacs-centered, contest/research oriented | Vendor-agnostic `DataProvider` model |
| Factors | Broad experimental library | Implemented, testable, promotable registry |
| Weighting | IC/meta-learning research logic | Causal production-shaped implementation |
| Portfolio | Contest/research portfolio construction | Broker-ready target weights |
| Execution | No real broker loop | Tastytrade-oriented broker connector and rebalancer |
| Review | CSV/dashboard artifacts | Morning report, ledger, health, reconciliation |

The immediate conversion target is **Tastytrade**: convert daily alpha targets into safe, auditable, dry-run-first order plans, then paper execution, then gated live execution.

## Capability status

| Capability | Status | Canonical note |
|---|---:|---|
| Q23 strategy ideas | Proven research source | Preserve the best concepts, not every implementation detail |
| Vendor-agnostic engine | Implemented | `engine/` is the active codebase |
| OHLCV panel model | Implemented | Current engine normalizes daily market data into a panel |
| Factor library | Partially implemented | Broader Q23 spec is larger than the implemented engine subset |
| IC meta-learning | Implemented | Must remain purged/causal; no look-ahead shortcuts |
| Sleeve ensemble | Implemented | Includes defensive/momentum/mean-reversion/microstructure families and optional ML sleeve |
| Portfolio construction | Implemented | Converts scores into target weights with caps, smoothing, and no-trade logic |
| Risk stack | Implemented | Vol targeting, drawdown throttle, overlays, kill-switch concepts |
| Local paper broker | Implemented | Offline safety harness for order lifecycle testing |
| Tastytrade connector | In progress / gated | Integration path exists, but production submission stays gated |
| Rebalancer | Implemented / validating | Converts target weights to share orders with audit trail and reconciliation |
| PIT universe | Production gate | Required before quoting strategy results as production-quality |
| Live capital | Not active | Requires all gates below |

## Production gates

No live-capital trading until all three gates pass.

### Gate 1 - Data correctness

- Point-in-time universe data is wired into the daily path.
- Staleness checks understand market holidays and provider lag.
- Restatements or vendor changes are detected and logged.
- Every reported backtest labels its universe, data source, date range, and survivorship-bias status.

### Gate 2 - Strategy reproducibility

- Golden weights protect behavior-changing edits.
- Causality tests prevent future leakage.
- Walk-forward reports accompany parameter changes.
- Any factor promotion is justified by IC/IR, hit rate, stability, and OOS behavior.

### Gate 3 - Execution safety

- Tastytrade authentication and token refresh are reliable.
- Order generation is dry-run-first and auditable.
- Pre-trade checks enforce leverage, cash, ADV participation, and position limits.
- Reconciliation compares intended, submitted, filled, and actual broker positions.
- Shadow-vs-live drift is visible before capital is at risk.

## Operating loop

The intended daily loop is:

1. **Session/bootstrap** - validate credentials, refresh broker/data tokens, snapshot account and universe state.
2. **Daily compute** - build the panel, compute factors, produce target weights, create the morning report.
3. **Human PM review** - inspect weights, risk, drift, unusual factor behavior, and proposed orders.
4. **Dry-run order plan** - generate broker-ready orders without submitting by default.
5. **Paper execution** - submit only in paper/sandbox mode while validating fills and reconciliation.
6. **Production execution** - allowed only after all production gates are satisfied.

Timing labels should always distinguish **bootstrap**, **daily compute**, **review**, and **broker deadline**. Avoid mixing clock times without saying which step they refer to.

## Repository map

```text
README.md              canonical project narrative and status
strategy.md            target alpha specification and Q23 idea map
plan.md                architecture and migration rationale
roadmap.md             remaining build sequence and research agenda
production.md          production-readiness gates and operating controls
engine/                active Svyable engine implementation
engine/README.md       package-level usage and implementation details
ops/CLAUDE_LOOP.md     daily review/supervision loop
```

This README is the canonical status document. Other documents may contain deeper detail, historical rationale, or aspirational specifications, but this file wins when documents disagree.

## Performance language

Use precise labels:

- **Q23 research result** - came from the predecessor research harness.
- **Svyable engineering validation** - verifies the engine works, but may use biased or incomplete data.
- **Paper result** - came from broker/paper execution or simulated fills.
- **Live result** - came from real capital. None are claimed here yet.

Reference proof point from Q23: `q23_neural_alpha`, 2025 under full contest constraints - 63.58% annual, Sharpe 3.545, MaxDD -5.67%, 58.02% net of contest-model costs.

That number motivates the conversion effort. It is not a live Svyable Strategies result.

Current engine validation snapshot from the existing docs: full 6.5-year x 128-asset pipeline runs in roughly five seconds on a MacBook-class machine; the walk-forward fragility scan was marked robust on the tested real-data snapshot; seed-universe backtests remain survivorship-biased unless PIT universe data is explicitly used.

## Development discipline

- Strategies are configs where possible, not forks.
- All vendor details live behind adapters.
- Default mode is sandbox/paper/dry-run.
- Main branch represents the production-intended record.
- Any weight-changing code edit must either preserve golden weights or deliberately re-bless them with a clear reason.
- No result should be quoted without its data source, date range, universe definition, and execution status.

## Next actions

1. Finish the Tastytrade paper loop: auth, order preview, submit/cancel/status, fills, reconciliation, and ledger evidence.
2. Wire point-in-time NASDAQ universe data into the default production path.
3. Promote Q23 ideas into the engine one family at a time, using IC tearsheets and walk-forward reports as promotion gates.
4. Harden observability: health checks, run ledger, shadow-vs-live drift, dead-man heartbeat, and failure escalation.
5. Run the full system in paper mode long enough to establish stable daily operations before enabling any live-capital path.
