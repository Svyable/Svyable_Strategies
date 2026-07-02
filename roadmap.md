# Svyable Roadmap — Strategy, Harness, Company

Status: v1.0 (2026-07-01)
Reads with: [strategy.md](strategy.md) (the alpha spec, incl. §11 contest-unlock analysis and §12 the NASDAQ long-only flagship) and [plan.md](plan.md) (connector architecture).

Reference proof point: q23_neural_alpha, full-year 2025 under contest constraints — 63.58% annual, Sharpe 3.545, MaxDD −5.67%, 58.02% net of (contest-model) costs. The method works handcuffed; the roadmap is about removing the handcuffs safely and building a durable operation around it.

---

## Phase 1 — The generic harness (`svyable-engine`)  [~now → +2 months]

Build the portable package that strategy.md specifies. This is a rewrite-by-extraction, not a port of Q23's file tree.

**Deliverables**
1. `svyable_engine/` Python package, zero Quantiacs imports:
   - `panel.py` — canonical Panel schema (time × asset OHLCV + computed liquidity mask) + validators (gap detector, NaN audit, universe-drift check).
   - `factors/` — flat registry of pure functions `f(panel, params) → DataArray` (~70 factors from strategy.md §4). One file per family, one test per factor (shape, causality — factor at t must not change when future rows change, sign orientation).
   - `weighting.py` — rank-IC meta-learner: EWMA, horizon+1 purge shift, positive-only, correlation penalty, min-weight floor, **causal** recency boost.
   - `sleeves.py` — sleeve scoring at per-sleeve horizons, sleeve corr penalty, stress prior.
   - `construct.py` — seats → softmax tilt → capped-simplex projection with the new bound set (risk-contribution cap + ADV cap + weight ceiling), EWMA weight smoothing, TC gate.
   - `risk.py` — vol-target budget, dd throttle, independent overlay, kill-switch series.
   - `artifacts.py` — the full §6 evidence chain + config-hash provenance.
   - `providers/` and `brokers/` — the two protocols from plan.md; ship with `QuantiacsProvider` (regression anchor) and one commercial EOD provider (Polygon/EODHD/Norgate — pick by point-in-time universe quality, §12.1 needs it).
2. **Regression gate**: `svyable-engine` re-running neural_alpha's config against Quantiacs data must reproduce the 2025 reference weights within float tolerance. That is the proof the extraction lost nothing.
3. **Walk-forward CLI**: `svyable backtest --walk-forward` produces the rolling out-of-sample report; no parameter change merges without it (strategy.md §8.5).

**Exit criteria**: regression gate green; `svyable_nasdaq_lo` backtests running on the commercial provider with own point-in-time NASDAQ universe.

## Phase 2 — Paper loop  [+2 → +4 months]

1. Alpaca (or broker-sandbox) adapter + `rebalancer.py` (target weights × equity vs positions → orders with ADV spill-over).
2. The full daily loop (strategy.md §7) on a scheduler: ingest → validate → compute → persist → diff → gate → execute → reconcile → report. Every step alerting on failure; a missed run is a paged incident, not a silent skip.
3. Run `svyable_nasdaq_lo` on paper for ≥ 60 trading days. Measure: implementation shortfall per fill (seeds the real TC model), live-vs-shadow-backtest tracking (±30bps/day target), operational uptime.
4. Retune the smoothing/TC-gate stack against *measured* paper costs (the +4%/yr unlock from strategy.md §11.2 #4 gets sized honestly here).

**Exit criteria**: 60 clean days, tracking within tolerance, measured cost model in place, kill-switch tested by fire-drill (deliberately trip it).

## Phase 3 — Live pilot, small capital  [+4 → +7 months]

1. Real broker adapter (tastytrade or Schwab per plan.md — start Schwab app approval during Phase 1, it's the long pole; IBKR if portfolio margin at 2.0× leverage is wanted from day one).
2. Trade `svyable_nasdaq_lo` with small personal capital. Position caps at the conservative end (10% of ADV rule at small AUM is unbinding — the point is process, not P&L).
3. Daily reconciliation dashboard page; monthly letter-to-self: performance vs QQQ, IC health, factor-weight drift, cost analysis. This becomes the track-record artifact.
4. Unlock schedule (deliberately staged, one variable at a time, each gated on a clean month):
   - M1: real costs + MOC execution (pure implementation, no strategy change)
   - M2: universe breadth to full screen (~600–1,200 names)
   - M3: risk-based caps replace flat 10–12% weight cap
   - M4: dispersion-adaptive seats
   - M5+: leverage toward 2.0× only if live Sharpe ≥ 2 over the trailing quarter

## Phase 4 — Scale & second book  [+7 → +12 months]

1. `svyable_core` (L/S sleeve ensemble) goes live once shorting ops (locates, borrow-cost feed into the TC model) exist — the short book must pay for its own frictions, which the contest never charged.
2. `svyable_micro` shadow book: GLFT sleeve on real intraday data (upgrade the OFI/VPIN/Kyle proxies to actual trade data — strategy.md §11.2 #5).
3. Capacity study: at what AUM does the median position hit 5% ADV? (Rough expectation: NASDAQ >$25M-ADV universe supports low-nine-figures gross before slippage eats the edge — verify with the measured impact model, don't trust the prior.)
4. Data expansion through the IC gate (strategy.md §8.10): fundamentals (Daloopa) → quality/value sleeve becomes real; alt-data (Quiver) as shadow factors for ≥ 1 quarter before promotion.

## Phase 5 — The company  [+12 months →]

Sequenced by regulatory weight, lightest first:
1. **Proprietary capital + published track record** (GIPS-style discipline even if unaudited at first; the Phase-3 monthly letters are the seed).
2. **Friends/family SMAs** via the broker's advisor rails (RIA registration when AUM/state thresholds require — get counsel before the first external dollar).
3. **Fund wrapper** only when justified: ≥ 18–24 months live record, capacity study done, admin/audit/compliance costs (~$100k+/yr) < 1% of target AUM.
4. Throughout: the **harness is the moat**, not any single config. The IC meta-learner + sleeve architecture + evidence-chain tooling is what lets Svyable add factors, universes, and asset classes faster than the alpha decays. Treat `svyable-engine` as the product; strategies are content.

---

## Standing research agenda (parallel to all phases)

| Priority | Item | Why |
|---|---|---|
| 1 | Point-in-time NASDAQ universe quality | Breadth is the cheapest multiplier (§11.2 #2) and garbage universes silently fake alpha |
| 2 | Measured-cost calibration + faster smoothing retune | +~4%/yr sitting in a config file |
| 3 | Risk-contribution caps + conviction sizing | The 10%-cap giveback at the top of the book |
| 4 | Intraday data → GLFT family | Same formulas, strictly better inputs |
| 5 | Fundamentals sleeve (IC-gated) | Only factor family with zero real representation today |
| 6 | Regime research: does the stress prior need a vol-regime term in addition to drawdown? | dd is a lagging trigger; realized-vol acceleration may lead it |
| 7 | Deflated-Sharpe / PBO reporting in the walk-forward CLI | Keeps us honest as config count grows |

## Operating principles (non-negotiable)

1. **One variable at a time** — every unlock ships alone, gated on a clean month.
2. **Shadow everything** — no factor, provider, or broker goes live without a shadow period whose tracking is measured.
3. **The backtest is a hypothesis; the reconciliation report is the fact.**
4. **Evidence chain before orders** — if artifacts didn't write, the run didn't happen, no trades.
5. **Sized to survive being wrong** — kill-switch thresholds are set from backtest stats *before* go-live and never loosened mid-drawdown.
