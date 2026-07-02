# Svyable Core Strategy — Distilled Alpha Specification

Status: v1.0 (2026-07-01)
Source: Full audit of the 12 strategies in `Q23_QUANT_SYSTEM 2` (nasnys_v4, qs23_hybrid_alpha, q23_composer_v1/v2, q23_neural_alpha v1/v2, gtp51max, gpt52v4, ou_v1, glft_v1/v2/v3, benchmarks)
Companion doc: [plan.md](plan.md) — vendor-agnostic data/broker connector architecture. This doc is the *what to compute*; plan.md is the *how to plug it in*.

---

## 0. Thesis

Q23's edge was never any single strategy. Every one of the 12 strategies is the **same five-stage pipeline** with a different factor menu and parameter set:

```
Panel(time, asset) OHLCV
   → Factor Library          (cross-sectional z-scored signals)
   → Adaptive Signal Weighting (rank-IC meta-learner decides which factors to trust today)
   → Composite Score          (time, asset)
   → Portfolio Constructor    (seats → tilt → constraint projection → smoothing → TC gate)
   → Risk Budget              (vol targeting × drawdown throttle × overlays)
   → Target Weights           (time, asset) + gross budget (time)
```

That pipeline **is** the alpha harness. It is 100% derivable from daily OHLCV + a liquidity mask, which means it runs against *any* data vendor and hands a plain target-weight vector to *any* broker. Everything below is broker/data-agnostic by construction.

The distilled strategy — **`svyable_core`** — is the best surviving combination of ideas across all 12 Q23 strategies, with the known defects fixed (§8).

---

## 1. What each Q23 strategy contributed (and what we keep)

| Strategy | Core idea | Verdict — what survives into svyable_core |
|---|---|---|
| **nasnys_v4** | 24-factor IC-weighted long-only, NAS+NYS, vol-target budget | The proven baseline factor menu (defensive + residual momentum + technical). Keep as the backbone of the Defensive and Momentum sleeves. |
| **qs23_hybrid_alpha** | Same engine, single exchange, daily rebalance, tuned smoothing | Confirms the pipeline generalizes across universes with only config changes. Keep: config-only strategy variants (no code forks). |
| **q23_composer_v1** | 32 factors + **minimum factor-weight floor** (re-normalized) | Keep the min-weight floor — prevents the IC learner from collapsing onto 2–3 recently-hot factors; measurably improves IC health. |
| **q23_composer_v2** | 36 factors, asymmetric L/S (18L/6S), prop-mass side split, IC **recency boost** | Keep asymmetric L/S and prop-mass side budgeting. The recency boost is directionally right but implemented with look-ahead — reimplement causally (§8.1). |
| **q23_neural_alpha v1/v2** | 15 novel behavioral/microstructure factors; v2 = curated 40-factor ensemble tuned from cross-strategy lessons | Keep all 15 novel factors (§4.5–4.6) and, more importantly, the v2 *method*: evolve strategies by combining measured best traits (v2 explicitly imported GTP51MAX's DD control, V4's momentum, Composer's balance). |
| **gtp51max** | **Correlation-aware IC weighting** + independent vol/DD **risk overlays** stacked on top of vol targeting | Keep both. The corr penalty (down-weight factors redundant with the rest of the ensemble) and the belt-and-suspenders overlay produced the lowest MaxDD of the fleet (−3.75%). |
| **gpt52v4** | **Four-sleeve ensemble** (momentum / mean-reversion / microstructure / defensive), per-sleeve IC weighting at sleeve-appropriate horizons, sleeve-level corr penalty, **stress prior** shifting weight to defensive/MR in drawdowns | The single best structural idea in the codebase. svyable_core adopts the sleeve architecture wholesale (§5). |
| **ou_v1** | Ornstein-Uhlenbeck parameter estimation (θ, μ, σ, half-life) via rolling AR(1); half-life-adaptive momentum/reversal blend; L/S 15/10 | Keep the OU factor family (§4.3) — especially `ou_momentum_blend`, which resolves the momentum-vs-reversal conflict per-asset instead of per-strategy. |
| **glft_v1/v2/v3** | Market-microstructure factors from daily bars: OFI, VPIN toxicity proxy, Kyle's lambda, BVC, inventory proxy, execution quality, adverse-selection decomposition | Keep the v3 superset (24 factors) as the Microstructure sleeve (§4.4). These are the least crowded signals in the library. |
| **benchmarks** | Equal-weight / market-cap universes always computed alongside | Keep: every run must emit benchmark curves or performance claims are unverifiable. |

---

## 2. The alpha principles (the essence)

These eight principles are what actually generate and protect the returns. Any reimplementation, in any language against any API, must preserve them.

1. **Cross-sectional, not time-series, prediction.** Every factor is a *ranking* of assets against each other today (robust z-score across the asset dimension, clipped ±5). We never predict absolute returns — only which assets beat which. This is what makes the signals robust to regime level-shifts.

2. **No factor is trusted a priori — the IC meta-learner allocates trust.** Factor weights = EWMA-smoothed rank-IC (Spearman correlation of factor values vs forward returns, computed cross-sectionally per day), clipped (±0.20–0.25 guardrail), **shifted one day** (today's weights use only yesterday's information), clamped positive, normalized to sum 1. A factor that stops working automatically bleeds to zero weight; nobody has to notice.

3. **Diversify the signal, not just the portfolio.** Penalize a factor's weight by its average absolute correlation with the other factors (blend strength ~0.30, diversification floor ~0.20–0.25), and floor every factor's weight (~1–2%) so the ensemble never collapses onto the recent winner. Apply the same penalty a second time *across sleeves*.

4. **Match the evaluation horizon to the signal's half-life.** Momentum sleeves are scored on 21d/63d forward returns; mean-reversion and microstructure sleeves on 5d/21d; defensive on 21d. Averaging IC weights across the sleeve's own horizons (gpt52v4's `_sleeve_score`) beats the single fixed 21d horizon used everywhere else in Q23.

5. **Regime awareness through priors, not switches.** The stress prior scales sleeve weights continuously with market drawdown depth (stress = dd/10% capped at 1): momentum ×(1 − 0.6·stress), mean-reversion ×(1 + 0.4·stress), microstructure ×(1 + 0.2·stress), defensive ×(1 + 0.8·stress). No binary regime classifier to get whipsawed by — exposure *tilts* smoothly.

6. **Turnover is an expense line, not an afterthought.** Three layers keep it down: score smoothing (3–4 day SMA), weight smoothing (EWMA blend, α ≈ 0.30–0.38 new / rest previous), and a TC-aware rebalance gate (skip the trade when expected alpha doesn't clear modeled cost). Costs are modeled as ATR-proportional (spread/impact scale with volatility), not flat bps.

7. **Risk is budgeted top-down, then guard-railed.** Position weights are unit-normalized first; a separate scalar **budget** series (gross exposure per day) applies vol targeting (target ÷ realized EWMA vol, clamped to [lev_min, lev_cap]) times a drawdown throttle (1 − 0.6–0.7·dd, floored at 0.5). Then an *independent* overlay (realized-vol scaler × dd throttle, clipped [0.5, 1.25]) multiplies the result. Redundancy is the point: the overlay caught what vol targeting missed.

8. **Determinism and auditability.** Same inputs → same weights (explicit ordering, no RNG in the trading path). Every run writes the full evidence chain: raw IC, smoothed IC, factor weights, composite score, weights, budget, per-day diagnostics, factor exposures, and a meta JSON with every config knob. If you can't reconstruct *why* the book held X on date T, the run doesn't count.

---

## 3. Canonical data contract

The entire system consumes exactly one input shape — any vendor adapter (see plan.md §B.2) just has to produce it:

```
Panel:
  dims:   (time: daily bars, asset: universe members)
  fields: open, high, low, close, vol (share volume)
  mask:   is_liquid (0/1, point-in-time tradability — delistings excluded as of each date)
derived internally:
  ret     = close.pct_change()
  returns must be survivorship-bias-free (universe membership as-of each date)
```

Rules learned from Q23's Quantiacs/Marketstack merge that carry over to any vendor pair:
- **Point-in-time universes or nothing** — a factor library this large will happily overfit to survivorship ghosts.
- **Gap-fill recent days from a second (live) source; never restate history from it.** Detect the gap, merge on the seam, log which rows came from which vendor.
- **One canonical symbol identity layer.** Every vendor and broker maps through it (Q23's `symbol_mapper` generalizes).
- If `is_liquid` is missing, degrade to `volume > 0` — but log it as degraded.

---

## 4. The factor library (canonical taxonomy, ~70 factors)

All factors: computed per (time, asset), robust cross-sectionally z-scored, sign-oriented so **higher = more attractive to own**. Formulas below use daily bars only.

### 4.1 Defensive / low-risk (the ballast — 9)
| Factor | Definition |
|---|---|
| `inv_vol` | 1 / rolling σ(ret) |
| `inv_idio` | 1 / σ(residual ret after market beta removal, ~52d) |
| `inv_down` | 1 / downside semi-deviation (~52d) — the Sortino lens |
| `low_beta` | −rolling market beta (~126d) |
| `low_corr` | −rolling correlation to market (~52d) |
| `beta_stability` | −σ(rolling beta) — stable exposure is itself a quality |
| `liquidity` | rolling dollar ADV (63d) |
| `amihud_inv` | −Amihud illiquidity = −mean(|ret| / dollar_vol) |
| `micro_noise` | −high-frequency noise proxy (short-window return reversals) |

### 4.2 Momentum / trend (the engine — 15)
| Factor | Definition |
|---|---|
| `resid_mom` (+ `_short`, `_long`, `_mix`) | momentum of *residual* (beta-stripped) returns at 21/84/126d — momentum without the market's momentum |
| `ret_2_12m` | classic 12-1 momentum (skip most recent month) |
| `breakout` | Donchian-style distance above rolling 63d high band |
| `slope` | EMA(16) vs EMA(42) trend slope |
| `ma_cloud` | position of price vs stack of MAs |
| `prox_52w_high` | close / 252d max — anchoring underreaction |
| `rel_sector_mom` | momentum vs cross-sectional (sector-proxy) mean |
| `cross_momentum` | cross-asset relative momentum rank |
| `vol_breakout` | volatility expansion in trend direction |
| `calm_flow` | high return per unit vol (quiet accumulation) |
| `trend_consistency` | fraction of positive days over window — path quality, not just endpoint |
| `momentum_acceleration` | Δ momentum (2nd derivative of price) |
| MTF family (`mtf_alignment`, `mtf_alignment_strength`, `mtf_slope`, `mtf_ic_momentum`, `mtf_ic_regime`, `hloc_close_position`, `hloc_range_expansion`, `hloc_momentum_quality`) | multi-timeframe (week/month/quarter/year) trend agreement; alignment across horizons = conviction |

### 4.3 Mean-reversion / OU (the counter-engine — 10)
| Factor | Definition |
|---|---|
| `srev` / `lrev` | −5d / −21d return (short/long reversal) |
| `ou_zscore_short` / `ou_zscore_med` | −z of log-price vs OU equilibrium μ, from rolling AR(1): X_t = a + b·X_{t−1}; θ = −ln b, μ = a/(1−b), half-life = ln2/θ (21d / 63d windows) |
| `ou_predicted_return` | θ·(μ − X): expected drift toward equilibrium — reversion *speed × distance* in one number |
| `ou_halflife_signal` | 1/(half-life+1): fast reverters carry stronger signals |
| `ou_reversion_strength` | θ ranked cross-sectionally |
| `ou_equilibrium_dist` | blended (0.3 short + 0.7 med) normalized distance below equilibrium |
| `ou_regime_indicator` | −|half-life − cross-sectional median|: assets behaving like the market's typical reverter are most reliable |
| `ou_momentum_blend` | **the standout**: per-asset blend w = normalized half-life; w·momentum + (1−w)·reversal. Long-half-life assets get momentum treatment, short-half-life get reversal — the momentum-vs-reversion argument settled per-asset, adaptively |

### 4.4 Microstructure / order-flow (the uncrowded edge — 24, GLFT v3 superset)
All from daily bars — signed volume = sign(Δclose)·volume as the trade-direction proxy.
| Factor | Definition |
|---|---|
| `ofi_short/med/momentum` | order-flow imbalance = Σ signed_vol / Σ vol over 5/21d; momentum = short − long OFI |
| `flow_toxicity` (VPIN proxy) | −|buy_vol − sell_vol| / total over ~42–50d: avoid names where flow is one-sided/informed |
| `toxic_momentum` | −Δ toxicity (5d vs 21d): deteriorating flow quality is a leading exit signal |
| `kyle_lambda` | −cov(ret, signed_vol)/var(signed_vol): low price-impact names are cheaper to trade and less adversely selected |
| `volume_clock_ofi` | OFI measured in dollar-volume time instead of calendar time |
| `bvc_imbalance` | bulk-volume classification: (close−low)/(high−low) splits volume into buy/sell |
| `impact_asymmetry` | volume-weighted up-day impact − down-day impact |
| `inventory_signal` / `inventory_risk_prem` | −EWMA(signed_vol) as market-maker inventory proxy; σ of it as risk premium |
| `spread_adjusted_mom` | 21d momentum − 2× estimated spread (ln(H/L) proxy): momentum net of implementation friction |
| `mm_edge` | composite: 0.4·low-toxicity + 0.3·vol + 0.3·short-reversal (where a market maker would quote tighter) |
| `amihud_hybrid` | 0.4·(−Amihud) + 0.3·(−spread) + 0.3·volume-normalcy |
| `mtf_ofi_alignment` | sign agreement of OFI across 5/21/63d × magnitude — flow consensus |
| `sector_rel_flow` | OFI − cross-sectional mean OFI |
| `regime_toxicity` | −(own VPIN / rolling market VPIN): low toxicity *relative to the regime* |
| `market_flow_mom` | own OFI aligned with market-wide flow acceleration |
| `exec_quality` | equal blend: low spread, low impact, high relative volume, low toxicity |
| `adverse_decomp` | noise-variance share of total variance (1 − informed share): high noise = safe to provide liquidity |
| `optimal_spread` | GLFT formula δ* ≈ σ² + 2·ln(1+1/k) vs actual ln(H/L) spread: positive gap = spread underpriced |
| `flow_persistence` | autocorr(OFI) × OFI: persistent flow = follow it, mean-reverting flow = fade it |
| `reservation_signal` | Avellaneda-Stoikov-style reservation price shift from inventory × σ² |

### 4.5 Behavioral (research-backed, from neural_alpha — 3)
| Factor | Definition | Basis |
|---|---|---|
| `attention_momentum` | sign(ret) · (vol/ADV − 1) · |ret z|, smoothed 10d | Barber & Odean 2008 |
| `disposition_alpha` | −(close − 52w-midpoint)/midpoint, gated by positive short momentum — buy paper-loss names that started recovering | Grinblatt & Han 2005 |
| `anchoring_bias` | 0.6·(close/52w-high) + 0.4·((close−52w-low)/(range)) | Bhattacharya 2012 |

### 4.6 Signal-quality / regime / cross-sectional (the refiners — 9)
| Factor | Definition |
|---|---|
| `efficiency_ratio` | Kaufman ER × trend sign: |net move| / Σ|daily moves| — trend vs chop |
| `information_flow` | (up-day dollar-impact − down-day)/total |
| `mean_reversion_speed` | −autocorr of deviations from EMA trend |
| `momentum_quality_ratio` | rolling mean(ret)/σ(ret) annualized — the Sharpe *of the asset's own momentum* |
| `momentum_persistence` | rolling autocorr(ret, 42d) |
| `momentum_divergence` | (residual mom − price mom)/σ: alpha-driven moves > beta-driven moves |
| `vol_of_vol` | −σ(σ(ret)): unstable risk is a cost |
| `skewness_factor` / `kurtosis_factor` | +rolling skew (63d); −rolling kurtosis — prefer upside asymmetry, penalize fat tails |
| `regime_momentum` | sigmoid(vol-spike ratio) blends short-mom vs long-mom weights per asset |
| `cross_sectional_dispersion` | relative return × dispersion level — press bets when the cross-section pays for discrimination |
| `liquidity_momentum` | residual momentum × relative-ADV weight |

### 4.7 Quality / value placeholders (3 — thin today, first expansion target)
`quality_score`, `value_score`, `value_mom`, `quality_defensive` — currently price-derived proxies. When a fundamentals provider lands (plan.md Phase 1), these become the first real fundamental factors, validated through the same IC gate as everything else.

---

## 5. svyable_core: the distilled strategy

Adopt gpt52v4's sleeve ensemble as the flagship architecture, upgraded with the fixes in §8.

### 5.1 Sleeves
| Sleeve | Members | IC horizons | Stress multiplier |
|---|---|---|---|
| **Momentum** | §4.2 + momentum-quality refiners | 21d, 63d | 1 − 0.60·stress |
| **Mean-Reversion** | §4.3 + `mean_reversion_speed`, `disposition_alpha` | 5d, 21d | 1 + 0.40·stress |
| **Microstructure** | §4.4 + `information_flow`, `efficiency_ratio`, `liquidity_momentum`, `amihud_inv` | 5d, 21d | 1 + 0.20·stress |
| **Defensive** | §4.1 + quality/value + risk/regime refiners | 21d | 1 + 0.80·stress |

stress = clip(market_drawdown / 0.10, 0, 1), drawdown measured on the equal-weight universe curve over a 126d window.

### 5.2 Signal flow
1. **Within each sleeve**: correlation-aware IC weights per horizon (λ=0.95, clip ±0.25, corr penalty 0.30, diversification floor 0.25, min factor weight 1.2%), averaged across the sleeve's horizons → sleeve score.
2. **Across sleeves**: rank-IC of each sleeve score vs 21d forward returns, shifted 1 day, EWMA λ=0.94 → × sleeve-correlation penalty (strength 0.35, floor 0.25) → × stress multiplier → positive-normalized with sleeve min weight 12%.
3. **Composite** = Σ sleeve_weight × sleeve_score.

### 5.3 Portfolio construction (per day, causally)
1. Smooth composite score (4d SMA), mask by liquidity.
2. Select seats: **16 long / 6 short** (asymmetric — longs earn, shorts hedge), side budgets by proportional score mass (~75/25 typical).
3. Within side: shift scores non-negative, normalize, apply **softmax tilt** (α=0.88) toward conviction.
4. Project each side onto the **capped simplex**: per-name bounds [min_pos=0.15–0.2%, max_pos=8%], side sums exact.
5. **Smooth vs yesterday**: w = 0.34·target + 0.66·previous, re-tilt at half strength, re-project.
6. **TC gate**: if expected alpha (cross-sectional score dispersion) doesn't clear the modeled cost of the trade (ATR-based, ~8bps equivalent), keep yesterday's weights (re-projected to today's feasible set).

### 5.4 Risk budget (gross exposure per day)
1. Realized portfolio vol = EWMA(λ=0.95) of unit-weight portfolio returns, annualized.
2. Base leverage = target_vol / realized_vol, target 15% (11% in high-vol regime), clamped [0.40, 1.55].
3. × drawdown throttle: 1 − 0.70·dd (126d window), floored 0.50.
4. Final weights = unit weights × budget, re-projected to caps.
5. **Independent overlay** (gtp51max): realized-vol scaler (63d, target 15%, hard brake above 22%) × dd throttle, clipped [0.5, 1.25], applied to weights *and* budget.

### 5.5 Benchmarks
Always co-compute: universe equal-weight, universe cap-weight, and (where mappable) SPX/NDX equal- and cap-weight. Report active return, not just absolute.

---

## 6. PM tooling & observability (keep all of it)

Q23's output discipline is genuinely good practice — every run, tagged `{strategy_id}_{timestamp}`, emits:

| Artifact | Contents | Why the PM needs it |
|---|---|---|
| `weights` (wide CSV) | time × asset target weights | the actual deliverable; input to the execution rebalancer |
| `budget` | gross exposure per day | shows what the risk stack did |
| `factor_weights` | factor × time | *which signals the meta-learner trusts right now* — the single best health dashboard |
| `ic_raw` / `ic_smooth` | factor × time IC series | early-warning: factor decay shows here months before P&L |
| `portfolio_diag` | daily ret, turnover, TC drag, vol, dd, Sharpe/Sortino/Calmar | the P&L truth table, net of costs |
| `factor_exposure` | portfolio-weighted factor loadings over time | style-drift detection |
| `factor_vectors` | snapshot: per-asset factor values, score, weight, return | "why do we own X today" in one row |
| `meta.json` | every config knob, factor list, date range, data-source provenance | reproducibility contract |

Dashboard pages worth carrying over: overview equity curves vs benchmarks, rebalance blotter (yesterday→today diffs), IC health, factor exposure timeline, risk analytics, per-stock drilldown. New for live trading (plan.md Phase 3+): reconciliation view (engine target vs broker actual) and order audit log.

**Operational registry pattern**: strategies self-register into a `StrategyRegistry` keyed by `strategy_id`; an `enabled_strategies.json` toggles them without code changes; every strategy is config + factor list, never a pipeline fork. Keep exactly this.

---

## 7. The operating loop (any broker, any data API)

Daily cycle (after market close for EOD data; the loop is schedule-driven):

```
1. INGEST      DataProvider.get_prices() → canonical Panel; gap-fill from live provider
2. VALIDATE    gap detector, NaN/zero-volume audit, universe drift check — refuse to trade on bad data
3. COMPUTE     factor library → sleeve scores → IC weights → composite → target weights + budget
4. PERSIST     write full artifact set (§6) BEFORE any order leaves the building
5. DIFF        rebalancer: target weights × account equity vs BrokerConnector.get_positions() → order list
6. GATE        pre-trade checks: per-name cap, gross/net caps, TC gate, kill-switch (live dd breach → flatten-or-freeze)
7. EXECUTE     submit orders; record acks/fills
8. RECONCILE   post-fill positions vs targets; alert on drift > tolerance
9. REPORT      append to P&L/diagnostics; dashboard refresh
```

Steps 1–4 are exactly today's Q23 engine. Steps 5–9 are the execution layer specified in plan.md §B.3. The only genuinely new business logic is the rebalancer diff (weights → orders); everything else is adapters.

---

## 8. Improvements over the Q23 implementations

Fixes and upgrades to bake into svyable_core rather than port as-is:

1. **Causal recency boost** (bug fix). composer_v2 boosts factor weights by the mean IC of the *last 21 days of the entire dataset*, applied to all historical dates — look-ahead in backtests and inconsistent behavior live. Replace with a rolling version: boost_t = normalized mean of ic_smooth over (t−21, t−1]. Same idea, no future data.
2. **Purged IC estimation.** IC at time t uses 21d *forward* returns, so ic_raw at t overlaps fwd windows up to t+21; the 1-day shift is not enough to fully de-overlap when smoothing. Shift IC by (horizon + 1) days, not 1, before EWMA — costs a little responsiveness, removes a subtle optimism bias in every backtest.
3. **One factor library, flat registry.** Q23 scattered factor implementations across per-strategy subclasses (OUFactorLibrary, NeuralAlphaFactorLibrary, GLFTv3FactorLibrary) with duplicated copies of `ou_*` and `glft_*` in the shared file. Svyable: every factor is a pure function `f(panel, params) → DataArray`, registered by name in one flat registry; strategies are only (factor list, params, construction config).
4. **Turnover budget.** Add an explicit annualized-turnover cap per sleeve alongside the TC gate — the gate is per-day greedy and can still churn; a budget makes cost an explicit constraint.
5. **Walk-forward validation as a first-class command.** Q23 tuned parameters on full-sample backtests (the v2 configs openly cite full-sample stats). Svyable rule: any parameter change ships only with a rolling out-of-sample walk-forward report, and Sharpe claims are deflated for the number of configurations tried.
6. **Vectorize the per-day loop.** Portfolio construction loops over days in Python (fine at 1500 days × 500 assets, painful beyond). Keep the loop for the stateful parts (smoothing, TC gate) but batch the projection math.
7. **Config-hash provenance.** meta.json gains a hash of the resolved config + factor-library version + data snapshot ID, so any weights file is exactly reproducible.
8. **Execution-aware sizing (live).** Cap any single day's order in a name at a fraction of its ADV (the liquidity data is already computed for `amihud_inv`); spill the remainder to the next day. Backtests assumed frictionless fills at close.
9. **Live kill-switch tied to the same throttle math.** The drawdown throttle already computes portfolio dd daily; wire the same series to a hard rule live (e.g., realized dd > 1.5 × backtest MaxDD → cut gross to lev_min and page the PM). Risk logic that only exists in the backtest is decoration.
10. **Fundamentals/alt-data enter through the IC gate.** New factor families (Daloopa fundamentals, Quiver alt-data per plan.md) get zero prior trust: computed, z-scored, IC-tracked in shadow for a quarter, and only then eligible for sleeve membership. The meta-learner is the immune system — use it.

---

## 9. Default parameter sheet (tuned consensus across the fleet)

| Parameter | Value | Notes |
|---|---|---|
| Universe | liquid US equities, 2 exchanges, point-in-time | any vendor |
| Rebalance | daily EOD | pipeline is frequency-agnostic down to the bar size |
| Long / short seats | 16 / 6 | asymmetric; long-only variant: 20/0 |
| max_pos / min_pos | 8% / 0.15% | per name, of gross |
| target_vol | 15% base / 11% high-vol | annualized |
| lev range | 0.40 – 1.55 | gross |
| dd throttle | win 126d, stretch 0.70, floor 0.50 | 126 beats 252 (faster response, neural_v2 lesson) |
| overlay | vol win 63d, max_vol 22%, clip [0.5, 1.25] | independent layer |
| IC | λ=0.95 (factor), 0.94 (sleeve), clip 0.20–0.25, shift = horizon+1 | positive-only weights |
| corr penalty | 0.30 factor / 0.35 sleeve; floors 0.25 | |
| min weights | 1.2% factor / 12% sleeve | |
| score smooth / weight smooth / tilt | 4d SMA / α=0.34 / softmax α=0.88 | turnover control |
| stress prior | dd cap 10%; mom −0.60, MR +0.40, micro +0.20, def +0.80 | |
| TC model | ATR(14) × 0.05 × |Δw| (sim); broker-calibrated live | flat-bps/tiered available |
| Forward horizons | mom 21/63, MR 5/21, micro 5/21, def 21 | per sleeve |

---

## 10. Svyable v1 lineup

1. **`svyable_nasdaq_lo`** — long-only NASDAQ flagship (§12). First strategy to trade real capital.
2. **`svyable_core`** — the §5 L/S sleeve ensemble, evolved from the reference strategy (§11.1). Second book once shorting ops are in place.
3. **`svyable_micro`** — Microstructure sleeve standalone (GLFT v3 set) as a live research book; least crowded factors, watch its standalone IC.
4. **`svyable_bench_*`** — equal/cap-weight benchmarks + QQQ/NDX, always on.

Everything else from Q23 (nasnys_v4, composers, neural v1/v2, ou_v1, glft v1/v2, gtp51max) is subsumed: their surviving ideas are inside svyable_core's sleeves, and keeping them as separate live strategies would just be running the same pipeline with weaker configurations.

---

## 11. Unlocking alpha beyond the Quantiacs contest rules

The whole Q23 harness was tuned *inside* contest constraints that do not exist in a real account. The reference run proving the method works — **q23_neural_alpha, 2025 full year: 63.58% annual, Sharpe 3.545, Sortino 6.276, MaxDD −5.67%, win rate 58.8%, 22.09% avg daily turnover, 5.57%/yr TC drag (58.02% net)** — achieved that *with the handcuffs on*. Below, each contest constraint, where it lives in the code, and what removing it is worth.

### 11.1 Reference configuration (what produced the dashboard numbers)
q23_neural_alpha v1: 32 factors (15 novel behavioral/microstructure + 17 proven), 12L/8S seats, max_pos 12%, target vol 18% (12% volatile), lev 0.4–1.8, IC λ=0.94, softmax tilt 0.90, weight smooth α=0.35, dd throttle win 252. Ran at 93.5% gross / 40.8% net. Treat this as the tuned starting point that all unlocks below modify.

### 11.2 The constraint-by-constraint unlock list

| # | Contest constraint (where it lives) | Real-world reality | Unlock and expected effect |
|---|---|---|---|
| 1 | **10% per-name cap** (`MAX_POS`=0.10–0.12 everywhere; hard-coded into the capped-simplex bounds) | No regulatory per-name cap; only risk appetite and liquidity | Replace the flat weight cap with **risk-based caps**: cap each name's *contribution to portfolio risk* (e.g., ≤20% of total risk) plus an ADV liquidity cap (§11.3). Lets the softmax tilt actually express conviction — today the tilt routinely wants >12% in the top name and gets clipped, flattening the score-to-weight mapping precisely where the signal is strongest. Top-of-book conviction is where rank-IC alpha concentrates; this is the single biggest structural giveback in the current design. |
| 2 | **Universe = Quantiacs NDX/SPX lists** (`load_ndx_data`/`load_spx_data`, ~100–500 names, `is_liquid` contest flag) | Any listed stock you can borrow/trade | **Breadth is the cheapest alpha multiplier**: IR ≈ IC × √breadth. Expanding from ~100 NDX names to ~800–1,500 liquid NASDAQ names is a 3–4× breadth increase with the *same* factor IC — and mid-caps are less crowded, so cross-sectional IC typically *rises*. Requires own point-in-time universe construction (§12.1). |
| 3 | **Leverage cap 1.5–1.8× gross** (`LEV_CAP`; contest booksize normalized to 1.0, `pm_gross_target=1.0`) | Reg-T 2×; portfolio margin ~4–6× | Let vol targeting run true instead of being clamped: when realized vol is 9% and target is 18%, the engine wants 2.0× and the contest cap forces 1.8×. Raise `lev_cap` modestly (2.0–2.5× with portfolio margin) and let the dd throttle/overlays — not an arbitrary constant — bound risk. Do **not** chase max leverage; the throttle math was validated at ≤1.8×. |
| 4 | **Quantiacs TC model: 0.05 × ATR(14) × turnover** (`TransactionCostScheme.QUANTIACS_ATR`) | Real execution on liquid NASDAQ names: ~1–3bps with limit/VWAP orders vs the ~10bps-equivalent the contest charges | The dashboard's 5.57%/yr TC drag is a *contest fiction*. At realistic 2–3bps effective cost the same turnover costs ~1.1–1.7%/yr → **+4%/yr net, immediately, with zero strategy change**. Second-order unlock: the smoothing stack (score SMA, weight EWMA, TC gate) was tuned against inflated costs — with real costs calibrated from actual fills, the engine can afford to track its signal faster (lower smoothing, quicker seat swaps), recovering alpha currently sacrificed to phantom costs. |
| 5 | **One decision per day at the close, fill assumed at close** (EOD `xarray` pipeline; no order types) | Full execution toolkit: MOC/MOO, VWAP slicing, limit ladders, multi-day work-outs | Near-term: execute at MOC so fills match the signal timestamp (removes an un-modeled overnight slip). Later: split parent orders across the day, and feed *actual intraday* trade data into the GLFT factor family — every OFI/VPIN/Kyle-lambda factor in §4.4 is currently a daily-bar *proxy* for a quantity that real tick data measures directly. That family gets strictly sharper with better data, no formula changes. |
| 6 | **Free, unconstrained shorting** (contest fills any short at close, zero borrow) | Borrow fees, locates, squeeze risk, short-side margin | This one cuts the other way — the contest *flattered* the short book. Going **long-only for the flagship (§12) eliminates the entire liability**: no borrow cost, no locate ops, no squeeze tail-risk, simpler margin. The reference run's net exposure was already +40.8% — the book made its money long. |
| 7 | **Booksize normalized to 1.0, weights are the deliverable** (`OutputWriter` CSVs) | An account has cash, dividends, corporate actions, settlement | Add a cash sleeve as a first-class asset (un-deployed budget earns T-bill yield ~4–5% instead of the contest's implicit 0%), dividend accrual (NASDAQ ~0.8%/yr — free, uncounted return in the contest), and corporate-action handling in the execution layer. |
| 8 | **Fixed 20-seat top-N** (`TOPN_BASE`; tuned so 20 × ~10% cap ≈ fully invested under the cap) | Seat count is free | With the cap unlocked, make seat count **dispersion-adaptive**: concentrate (12–15 names) when cross-sectional score dispersion is high (the signal discriminates), widen (25–35) when it's flat. Q23 already computes `cross_sectional_dispersion` as a factor — reuse it as a *construction* input. |
| 9 | **Contest scoring window drove tuning** (Sharpe-ranked contest, fixed evaluation period) | The business objective is compounding net wealth at acceptable dd, with capacity | Retune the target-vol/leverage pair for geometric growth (Kelly-tempered, ~½-Kelly) rather than contest Sharpe rank. At Sharpe ~3 even conservatively deflated, optimal vol is well above 18% — but scale *only* as live results confirm backtest IC (§ roadmap). |

### 11.3 New constraint set (replacing contest rules with real ones)

Real life removes the contest's rules but adds its own — encode these as first-class, not afterthoughts:

- **Liquidity cap**: position ≤ X% of 21d ADV (start: 5%); daily trade in a name ≤ 10% of its ADV, remainder spills to next day.
- **Risk-contribution cap**: no name > 20% of portfolio risk (vol-scaled, correlation-aware) — this is what replaces the 10% weight cap, and it auto-tightens for volatile names, which the flat cap never did.
- **Live kill-switch**: realized dd > 1.5× backtest MaxDD → cut to `lev_min`, page the PM (strategy.md §8.9).
- **Execution-cost feedback loop**: measured implementation shortfall per fill feeds back into the TC model monthly; the TC gate uses *measured*, not assumed, costs.
- **Capacity monitor**: track (position size ÷ ADV) distribution; alpha decays when the book pushes >5–10% of ADV in its median name.

---

## 12. `svyable_nasdaq_lo` — the long-only NASDAQ flagship

Goal: beat QQQ decisively, net of real costs, at comparable-or-lower drawdown, on infrastructure that works with any data provider and any broker. Long-only is not a compromise — it deletes borrow costs, locate ops, and squeeze risk (§11.2 #6), and the reference book's alpha was predominantly long anyway.

### 12.1 Universe
- NASDAQ-listed common stocks (exclude ADRs initially, exclude SPACs/units), price > $5, 21d dollar-ADV > $25M.
- Point-in-time membership reconstructed from listing data — **own the universe file**; do not inherit a vendor's index list (that was the contest's job). Target ~600–1,200 names.
- Liquidity mask = own ADV/price screen; `is_liquid` becomes a computed field, not a vendor flag.

### 12.2 Signal (unchanged science, retuned application)
The §5 sleeve ensemble, long-only orientation:
- **Sleeves**: Momentum and Defensive carry the book; Mean-Reversion and Microstructure act as *timing refiners* (their scores adjust entry/exit and sizing rather than earning seats on their own — in long-only, MR's main job is "don't add to a name mid-air-pocket").
- Stress prior unchanged: momentum weight bleeds to defensive as market dd deepens — in long-only this is the primary crash defense alongside the budget throttle.
- All §8 fixes apply (causal recency boost, purged IC shift = horizon+1, flat factor registry).

### 12.3 Construction
- Seats: dispersion-adaptive 15–30 (§11.2 #8), long-only, softmax tilt α=0.90 (reference value — conviction is the point).
- Per-name bounds: min 0.5%; max = min(15% weight, 20% of portfolio risk, 5% of 21d ADV). The 15% hard ceiling is a sanity bound, not a binding constraint — the risk cap should bind first.
- Smoothing/TC gate retuned against **measured** broker costs (§11.2 #4); expect meaningfully faster signal tracking than the contest-tuned α=0.35.

### 12.4 Risk budget
- Target vol 18% base / 12% stressed (QQQ itself runs ~18–22%; you don't beat the index by running at 12%).
- Leverage 0.4–2.0× (portfolio margin), dd throttle win 126d, stretch 0.70, floor 0.45, plus the independent gtp51max overlay.
- Cash sleeve earns T-bill yield whenever budget < 1.0.
- Optional (execution-layer, not signal-layer): index-hedge module that can short QQQ futures/buy puts when the kill-switch trips — keeps the *stock book* long-only while allowing a portfolio-level brake. Broker-agnostic: it's just one more instrument in the rebalancer.

### 12.5 Success criteria (published before launch, judged out-of-sample)
- Rolling 12m: return > QQQ + 8% net of all costs; MaxDD ≤ QQQ's; Sharpe ≥ 2 live.
- IC health: composite rank-IC positive in ≥ 60% of months; no sleeve pinned at min weight for > 1 quarter without a research review.
- Tracking honesty: live daily returns within ±30bps of the shadow backtest run on identical data ≥ 90% of days (else the port has a bug, not the market).

---

## 13. SOTA upgrades that still run at home (daily bars, one MacBook)

Additions to the Q23-derived core, selected on three criteria: peer-reviewed or widely replicated, computable from daily OHLCV on consumer hardware, and complementary (not redundant) to the existing sleeves. All are implemented in `engine/` (see README) unless marked *research*.

| Upgrade | What it is | Research basis | Where it lands |
|---|---|---|---|
| **Overnight/intraday return decomposition** | Split close-to-close return into overnight (close→open) and intraday (open→close) legs; overnight-return momentum is a distinct, persistent anomaly ("the tug of war") and Q23 never used the open price for anything | Lou, Polk & Skouras (2019) | New factor `overnight_bias` in the Momentum sleeve — free alpha from a column we already ingest |
| **ML cross-sectional sleeve** | A regularized learner (ridge baseline; gradient boosting optional) trained walk-forward on the factor matrix → cross-sectionally demeaned forward returns. The point is *interaction effects* the linear IC weighting can't see. Refit monthly on a trailing window, purged; predictions enter as a **fifth sleeve** so the sleeve-level IC meta-learner decides how much to trust it — the ML never gets unsupervised control of the book | Gu, Kelly & Xiu (2020), "Empirical Asset Pricing via Machine Learning" | `svyable/ml.py`, optional (`sklearn`); sleeve `ml` |
| **Hierarchical Risk Parity seat weighting** | Alternative to score-proportional weighting inside the selected seats: cluster the seats by return correlation, allocate risk down the dendrogram. No matrix inversion, robust to estimation error — the known failure mode of Markowitz at small N | López de Prado (2016) | `svyable/hrp.py`, optional (`scipy`); config `seat_weighting: "score" \| "hrp" \| "blend"` |
| **Volatility-managed scaling, formalized** | Q23's vol targeting is Moreira-Muir in spirit; formalize with EWMA realized vol and document that vol-managed scaling adds alpha (not just comfort) for momentum-tilted books | Moreira & Muir (2017) | Already in `risk.py`; kept, documented |
| **Purged walk-forward + deflated Sharpe** | Every backtest report: expanding walk-forward with purge+embargo (no train/test overlap through the forward-return window), and Sharpe deflated for the number of configurations tried. Kills the full-sample-tuning sin of the Q23 configs | López de Prado (2018); Bailey & López de Prado (2014) | `svyable/metrics.py` (deflated Sharpe), CLI `backtest` |
| **No-trade band** | Replace the per-day greedy TC gate with an explicit L1 no-trade band: skip rebalancing entirely when the target book is within X% of the current book. Provably near-optimal under proportional costs | Davis & Norman (1990) lineage; standard industry practice | `construct.py`, `no_trade_band` |
| **Dispersion-adaptive seat count** | Concentrate when cross-sectional score dispersion is high (signal discriminates), widen when flat — reuses the dispersion computation as a construction input (§11.2 #8) | Stivers (2010) dispersion-opportunity link | `construct.py`, `seats_adaptive` |
| **Cash as an asset** | Un-deployed budget earns the T-bill rate in backtests and sits in SGOV/BIL live — the contest's implicit 0% cash was a silent tax | — | `risk.py` `cash_yield_annual` |
| *Research (not v1):* lead-lag peer momentum via correlation clusters | Momentum of a stock's statistical peers predicts the stock | Parsons et al. (2020) geography/linkage literature | Needs stability testing at daily frequency first |
| *Research (not v1):* turn-of-month / expiry seasonality overlays | Calendar effects are real but small; only worth it once the book is running | Ariel (1987) onward | Shadow IC tracking first |

**Explicitly rejected for this stack**: intraday/HFT signals (need tick infrastructure), deep nets on daily bars (parameter count ≫ information content at N≈1,000 daily observations; GKX found trees ≈ shallow nets on this data density), and alternative data scraping (compliance surface before there's a company). The §8.10 IC gate remains the immune system for anything new.
