# Svyable Tape Acceleration alpha note

This note documents the new daily OHLCV factor family and its first strategy mandate. It is research infrastructure, not a live-capital performance claim.

## Factor thesis

Tape Acceleration targets names where short-horizon price, range, gap, and volume behavior are changing faster than the broader trend books capture.

| Factor | Sleeve | Idea |
| --- | --- | --- |
| `liquidity_squeeze_breakout` | momentum | Prior-high breakout after compressed range, confirmed by returning dollar volume. |
| `pullback_reclaim` | momentum | Existing trend pulls back, then reclaims short moving averages with a strong close. |
| `gap_reversal_pressure` | meanrev | Overnight gap is rejected intraday; oriented toward the reversal. |
| `opening_drive_continuation` | momentum | Overnight gap and intraday drive point the same way with participation. |
| `exhaustion_reversal` | meanrev | Stretched 5-day move shows close-location and volume evidence of exhaustion. |
| `range_volume_acceleration` | momentum | Three-day return acceleration is confirmed by expanding range, volume, and directional persistence. |

All six factors are causal daily-bar transforms and are registered as shadow/incubation factors until they earn evidence through purged IC, hit-rate, coverage, and candidate-board performance.

## Strategy mandate

`svyable_tape_acceleration` blends the six Tape Acceleration factors with institutional trend, resilience, existing frontier price-action controls, residual trend, liquidity, idiosyncratic-risk, and turnover controls.

The mandate is deliberately cost-aware:

- no ML sleeve;
- blended seat weighting;
- 20 base seats, 16 minimum, 28 maximum;
- 9.5% max position;
- 3.2% no-trade band;
- 15.5% target volatility;
- 9.5% stressed target volatility;
- 2-day minimum hold.

## Diagnostics before trust

The strategy now has a non-trading diagnostics layer via `strategy_alpha_diagnostics.py`:

- `factor_snapshot()` checks recent factor coverage, latest dispersion, latest top/bottom names, and stage metadata.
- `factor_correlation_matrix()` flattens recent factor-score panels into a cross-factor correlation matrix.
- `redundancy_warnings()` flags highly correlated factor pairs.
- `strategy_alpha_diagnostics()` packages the above for a registered strategy.

These diagnostics do not estimate future returns, choose weights, or activate portfolios. They are an incubation guardrail for the PM and agent before the strategy competes for capital through the normal candidate-board process.

## Promotion path

1. The strategy runs as a regular candidate.
2. Purged IC and factor-health artifacts decide which factors deserve weight.
3. Shadow factors have no guaranteed floor.
4. The candidate board, meta harness, guard, receipt, and audit process remain the only route to canonical activation.
