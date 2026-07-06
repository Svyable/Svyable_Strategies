# Cold-start handling for new listings and fast index inclusions

This workflow covers names like `SPCX`: a very new listing or fast index entrant
that may have valid short-horizon alpha information before it has a full 63/126/252-day history.

## Design principle

Do not wait blindly, and do not pretend sparse history is mature evidence.

The harness now separates three questions:

1. **Can the symbol trade?** Existing price/ADV liquidity gates answer this.
2. **Is there enough signal evidence to rank it?** Available factor coverage answers this.
3. **How much can the book own?** Age-ramped and risk-adjusted caps answer this.

## Mechanics

### 1. Available-signal scoring

`weighting.composite_score()` treats missing signals as unavailable information,
not as zero evidence. Scores are normalized by the factor-weight mass that is
actually present for each asset/date.

That lets a new symbol express valid 5/10/21-day information without being
mechanically diluted by missing 126/252-day factors.

### 2. Cold-start confidence

`cold_start.py` computes:

- `trading_age`: available close bars per asset;
- `factor_coverage`: share of selected factor signals available today;
- `score_multiplier`: `sqrt(age_confidence * factor_coverage)`;
- `max_pos_multiplier`: per-asset position-cap multiplier;
- `range_vol`: Garman-Klass OHLC range-volatility proxy;
- `risk_cap_multiplier`: early high-volatility brake for sparse histories.

Below `cold_start_min_trading_days`, a name receives zero cold-start cap. From
`cold_start_min_trading_days` to `cold_start_full_trading_days`, the cap ramps
from `cold_start_min_cap_mult` toward full size. Mature names retain normal caps.

### 3. Per-asset construction caps

`construct.build_unit_weights()` accepts `max_pos_mult`, so a new name can rank
high but still cannot exceed its age/risk-adjusted cap.

## Defaults

```python
cold_start_enabled = True
cold_start_min_trading_days = 10
cold_start_full_trading_days = 63
cold_start_min_factor_coverage = 0.10
cold_start_min_cap_mult = 0.25
cold_start_vol_win = 21
cold_start_vol_min_periods = 5
cold_start_vol_cap_floor = 0.50
```

With `max_pos = 15%`, the initial cap for a newly eligible name starts around
`3.75%` before the volatility brake, then ramps toward the full cap as history
matures.

## What this is not

This is not a symbol-specific IC shortcut. IC remains factor-level,
cross-sectional, purged, and coverage-aware. The cold-start layer only controls
how much trust and capital a sparse-history asset receives while factor evidence
is incomplete.

It also is not a full covariance model. Early range-volatility is used as a
simple risk proxy. A future enhancement can add shrinkage covariance or peer
borrowed beta/correlation estimates once there is a clear validation harness for
that additional complexity.

## Operator review

Daily runs write `cold_start_diagnostics.csv` alongside the usual artifacts.
Review columns:

- `trading_age`
- `factor_coverage`
- `score_multiplier`
- `max_pos_multiplier`
- `range_vol`
- `risk_cap_multiplier`
- `eligible_by_cold_start`

For an SPCX-like name, the desired behavior is:

1. pending / not eligible before enough trade bars exist;
2. eligible at small size once short-history evidence and liquidity are present;
3. gradual increase in cap as history reaches 63 trading days;
4. normal treatment after full cold-start maturity.
