# Svyable strategy run — PM one-pager

Single-page validation briefing: what strategy, what risk state, what regime, which sleeves and factors are live, and the resulting book. Generated deterministically by `tests/test_regression.py`.

## 1 · Provenance & reproducibility contract

- strategy: `svyable_nasdaq_lo` v`0.3.0`
- weights_hash: `c132cbad488181078e704c64`  ·  config_hash: `052a518c0c903d14`
- provider: `SyntheticProvider(n_assets=40, n_days=600, seed=3)`
- config: `nasdaq_lo_config(min_adv=0, min_price=0, ml_enabled=False, seats_base=15, seats_min=10, seats_max=20)`
- as-of (synthetic) date: `2020-04-17`
- positions: `11`  ·  gross book / total weight: `0.81709000`
- factor universe: `99` factors registered (see §6)

> Not a live-capital recommendation. This is the deterministic CI behaviour contract for the pinned synthetic provider/configuration; the weights_hash is the hard regression gate.

## 2 · Risk posture (today)

| Control | Value | Setting |
| --- | ---: | --- |
| Gross book (leverage budget) | 0.817 | cap 1.500 / floor 0.400 |
| Realized vol (EWMA, ann.) | 19.61% | target 18.00% · stressed 12.00% → regime: stressed |
| Vol-overlay multiplier | 0.901 | clip (0.5, 1.25) on 63d vol |
| Regime throttle | 1.000 | risk-off floor 0.450 |
| Circuit breaker | armed (clear) | trip 10.00% dd × 1.500 → lev 0.000 |
| Seats live / turnover | 11 / 4.60% | no-trade band 4.00% |

## 3 · Regime stack (causal turbulence / breadth / panic)

- modules: turbulence=on (win 504, on≥p90), breadth (win 126), panic (vol z-on 1.0 / dd-on 8.00%)

| Signal | Reading | Interpretation |
| --- | ---: | --- |
| Turbulence percentile | 0.469 | structural dislocation vs 252d |
| Breadth | 0.823 | participation (low = narrow) |
| Absorption ratio | 0.533 | top-20% eigenvalue crowding |
| Market drawdown | 0.000 | own-market peak-to-trough |
| Market vol (ann.) / z | 0.167 / -0.096 | panic vol gauge |
| Panic signal | 0.000 | 0 = calm, 1 = full de-risk |
| **Net regime multiplier** | **0.988** | whole-book exposure scalar (ready=1.000) |

## 4 · Price-action Markov regime (price path only)

First-order Markov chain over vol-standardised daily market returns — *no factors, no fundamentals*. State = today's return in units of trailing 63d volatility, bucketed at z ∈ {-1.5, -0.5, 0.5, 1.5}. Estimated on 578 causal day-to-day transitions.

- **Current state: `Up`**  ·  self-persistence `0.265`  ·  expected dwell `1.4` trading days  ·  next-step entropy `2.07` bits
- modal forward path (argmax each step): Up → Flat → Flat → Flat → Flat → Flat

**Most-likely state distribution, h days ahead (row = horizon; bold = modal):**

| h | Crash | Down | Flat | Up | Surge |
| ---: | ---: | ---: | ---: | ---: | ---: |
| +1 | 0.062 | 0.191 | **0.383** | 0.265 | 0.099 |
| +2 | 0.046 | 0.195 | **0.394** | 0.284 | 0.080 |
| +3 | 0.047 | 0.196 | **0.394** | 0.282 | 0.081 |
| +4 | 0.047 | 0.196 | **0.394** | 0.282 | 0.081 |
| +5 | 0.047 | 0.196 | **0.394** | 0.282 | 0.081 |
| _∞ (stationary)_ | _0.047_ | _0.196_ | _0.394_ | _0.282_ | _0.081_ |

**Empirical transition matrix P (row = from-state → col = to-state):**

| from \ to | Crash | Down | Flat | Up | Surge |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Crash** | 0.037 | 0.222 | 0.370 | 0.333 | 0.037 |
| **Down** | 0.053 | 0.221 | 0.363 | 0.301 | 0.062 |
| **Flat** | 0.035 | 0.189 | 0.417 | 0.272 | 0.088 |
| → **Up** | 0.062 | 0.191 | 0.383 | 0.265 | 0.099 |
| **Surge** | 0.042 | 0.167 | 0.417 | 0.312 | 0.062 |

## 5 · Sleeve allocation & live IC health

Sleeves are meta-learned by trailing information coefficient; an untrusted (shadow) sleeve is allowed to bleed to zero, a proven sleeve keeps an anti-collapse floor.

| Sleeve | Live wt | IC-IR | Hit | mean-IC | Horizons | Stress prior | Trust |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| momentum | 0.7156 | 1.017 | 82.54% | 0.104 | 21/63 | -0.60 | proven |
| defensive | 0.0948 | -0.079 | 58.73% | -0.008 | 21 | 0.80 | proven |
| meanrev | 0.0948 | 0.119 | 66.67% | 0.016 | 5/21 | 0.40 | proven |
| micro | 0.0948 | -0.105 | 41.27% | -0.013 | 5/21 | 0.20 | proven |
| ml | — | — | — | — | 21 | 0.00 | shadow · disabled (ml_enabled=False) |

## 6 · Factor stack (what is switched on)

- **99** factors active — **43 proven** (guaranteed floor 1.20%) + **56 shadow** (no floor; earn weight via IC or decay out).

| Sleeve | Proven | Shadow | Total |
| --- | ---: | ---: | ---: |
| defensive | 17 | 7 | 24 |
| liquidity | 0 | 1 | 1 |
| meanrev | 7 | 8 | 15 |
| micro | 0 | 8 | 8 |
| momentum | 19 | 28 | 47 |
| resilience | 0 | 4 | 4 |

**Top 8 factors driving the dominant `momentum` sleeve today:**

- `fip_momentum` (proven, wt 0.081) — 12-1 momentum weighted by information continuity.
- `vol_scaled_momentum` (shadow, wt 0.076) — Classic skipped momentum divided by trailing realized volati…
- `momentum_divergence` (shadow, wt 0.072) — Cumulative beta-driven share of trailing 12-1 momentum.
- `mom_12_1` (proven, wt 0.071) — Q23 legacy implementation
- `momentum_quality` (proven, wt 0.058) — Q23 legacy implementation
- `multi_horizon_trend` (proven, wt 0.053) — Risk-adjusted 1/3/6/12-month trend rewarded for sign agreeme…
- `capm_alpha` (proven, wt 0.040) — Q23 legacy implementation
- `trend_consistency` (proven, wt 0.039) — Q23 legacy implementation

## 7 · Construction & universe

- seats: live `11` (adaptive True; base 15, min 10, max 20, disp-slope 4.0)
- position bounds: max 15.00% / min 0.50% · softmax tilt α 0.60 · seat weighting `score`
- smoothing: score 4d · weight-EMA α 0.40 · no-trade band 4.00%
- cluster caps: corr>0.70 over 126d capped at 40.00%
- universe filters: price ≥ $0.00 · ADV ≥ $0 over 21d
- costs assumed: 3.0 bps + 5.00% ADV participation cap

## 8 · Holdings (weights contract)

| Rank | Symbol | Weight | Weight % |
| ---: | --- | ---: | ---: |
| 1 | SYN012 | 0.12256350 | 12.2564% |
| 2 | SYN032 | 0.12256350 | 12.2564% |
| 3 | SYN036 | 0.12256350 | 12.2564% |
| 4 | SYN015 | 0.11264141 | 11.2641% |
| 5 | SYN037 | 0.06968374 | 6.9684% |
| 6 | SYN024 | 0.05783581 | 5.7836% |
| 7 | SYN008 | 0.05356175 | 5.3562% |
| 8 | SYN027 | 0.04935727 | 4.9357% |
| 9 | SYN013 | 0.04494853 | 4.4949% |
| 10 | SYN005 | 0.03634857 | 3.6349% |
| 11 | SYN026 | 0.02502242 | 2.5022% |
