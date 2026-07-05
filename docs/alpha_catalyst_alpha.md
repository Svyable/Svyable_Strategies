# Svyable Alpha Catalyst research note

This note documents the residual Alpha Catalyst factor family and first strategy mandate. It is research infrastructure, not a live-capital performance claim.

## Goal

Increase candidate-board alpha pressure by adding signals that are less dependent on broad market beta than plain trend. The book targets idiosyncratic acceleration, residual breakouts, failed downside moves, and volatility-transition participation.

## New factors

| Factor | Sleeve | Idea |
| --- | --- | --- |
| `residual_momentum_acceleration` | momentum | Five-day beta-stripped return acceleration versus the recent 21-day pace. |
| `residual_breakout_confirmation` | momentum | Residual cumulative-return breakout confirmed by dollar-volume participation. |
| `downside_absorption_reversal` | meanrev | Recent downside is absorbed by strong closes, intraday follow-through, and volume. |
| `failed_breakdown_reclaim` | meanrev | Price probes below the prior monthly low and reclaims it with a strong close. |
| `idiosyncratic_trend_quality` | momentum | Residual trend IR with directional persistence and a beta-dependence penalty. |
| `volatility_transition_alpha` | momentum | Positive residual thrust as range exits compression into expansion. |

## Strategy mandate

`svyable_alpha_catalyst` combines the six Alpha Catalyst factors with Tape Acceleration, residual-alpha factors, institutional trend, resilience, liquidity, and idiosyncratic-risk controls.

The mandate is designed to be more selective and cost-aware than a raw high-turnover alpha sleeve:

- no ML sleeve;
- blended seat weighting;
- 18 base seats, 14 minimum, 26 maximum;
- 9% max position;
- 28% cluster cap;
- 3% no-trade band;
- 15% target volatility;
- 9% stressed target volatility;
- 4.5 bps cost assumption;
- 2-day minimum hold.

## Why this is a direct alpha upgrade

The existing Tape Acceleration layer hunts for fast OHLCV tape changes. Alpha Catalyst adds a residual/idiosyncratic lens so the engine can prefer names whose acceleration and breakouts are not just market beta. It also adds explicit reversal signals for failed downside probes and absorption, which gives the candidate board more ways to find stock-specific alpha in choppy tape.

## Promotion path

1. Run as a default candidate in the normal strategy registry.
2. Let purged IC, hit-rate, coverage, and factor-health artifacts decide which new factors earn weight.
3. Use strategy alpha diagnostics to watch coverage, dispersion, and factor redundancy.
4. Allow activation only through the existing candidate board, context pack, guarded decision, review chain, and canonical activation rails.
