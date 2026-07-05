# Svyable Leadership Quality research note

This note documents the Leadership Quality factor family and first strategy mandate. It is research infrastructure, not a live-capital performance claim.

## Gap identified

Svyable already has fast Tape Acceleration factors and residual Alpha Catalyst factors. The missing sleeve was a slower, steadier leadership book: names that persistently lead on residual return, repair drawdowns quickly, break out from tighter bases, and show upside participation without noisy churn.

## New factors

| Factor | Sleeve | Idea |
| --- | --- | --- |
| `residual_leadership_persistence` | momentum | Residual leadership persists across 21-day and 63-day horizons with positive hit-rate support. |
| `tight_base_breakout_quality` | momentum | Breakout from a lower-range base confirmed by volume and strong close location. |
| `drawdown_repair_velocity` | momentum | Fast recovery from a medium-term drawdown with strong close location. |
| `trend_efficiency_stability` | momentum | Medium-term trend advances efficiently rather than through noisy churn. |
| `upside_volume_asymmetry` | momentum | Dollar-volume participation is stronger on up days than down days. |
| `quiet_accumulation_pressure` | momentum | Positive drift during lower-range sessions with steady dollar-volume support. |

## Strategy mandate

`svyable_leadership_quality` combines the six Leadership Quality factors with Alpha Catalyst, Tape Acceleration, residual alpha, institutional trend, resilience, liquidity, and idiosyncratic-risk controls.

The mandate is intentionally slower and more selective than the faster tape books:

- no ML sleeve;
- blended seat weighting;
- 18 base seats, 14 minimum, 24 maximum;
- 8.5% max position;
- 26% cluster cap;
- 4% no-trade band;
- 14.5% target volatility;
- 8.5% stressed target volatility;
- 4 bps cost assumption;
- 4-day minimum hold.

## Why this fills a useful gap

Tape Acceleration targets short-to-medium horizon bursts. Alpha Catalyst targets beta-stripped acceleration, breakouts, and reversal/absorption catalysts. Leadership Quality adds a durable participation lens that should be less dependent on one-day tape events and more tolerant of normal leadership pullbacks.

## Promotion path

1. Run as a normal registry candidate.
2. Compare its candidate-board utility and turnover versus Alpha Catalyst and Tape Acceleration.
3. Use factor-health and strategy alpha diagnostics to monitor coverage, IC, dispersion, and redundancy.
4. Promote individual factors only after evidence improves; keep shadow factors from receiving any guaranteed floor until then.
