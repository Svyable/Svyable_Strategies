"""Strategy configuration. One dataclass; strategies are configs, not code forks.

Defaults implement svyable_nasdaq_lo (strategy.md §12) with the §11 unlocks:
risk-based thinking replaces the Quantiacs 10% flat cap, real TC assumptions,
dispersion-adaptive seats, cash yield on undeployed budget.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class SleeveSpec:
    name: str
    horizons: tuple[int, ...]        # forward-return horizons for IC estimation
    stress_mult: float               # weight multiplier slope vs market drawdown stress
    proven: bool = True              # proven sleeves get the anti-collapse min-weight
    #                                  floor; shadow sleeves (proven=False) may bleed to
    #                                  zero so the IC meta-learner can zero out an
    #                                  untrusted sleeve (strategy.md §8.10/§13)


@dataclass(frozen=True)
class SvyableConfig:
    strategy_id: str = "svyable_nasdaq_lo"
    version: str = "0.2.0"

    # ---- universe ----
    min_price: float = 5.0
    min_adv: float = 25e6            # 21d dollar ADV
    adv_win: int = 21

    # ---- factor windows ----
    beta_win: int = 126
    idio_win: int = 52
    down_win: int = 52
    mom_win: int = 84
    mom_short: int = 21
    mom_long: int = 126
    rev_win: int = 5
    ema_fast: int = 16
    ema_slow: int = 42
    ou_short_win: int = 21
    ou_med_win: int = 63
    ou_halflife_min: float = 2.0
    ou_halflife_max: float = 42.0
    ofi_short_win: int = 5
    ofi_med_win: int = 21
    ofi_long_win: int = 63
    vpin_win: int = 42
    impact_win: int = 42
    attention_win: int = 10
    disposition_win: int = 63
    efficiency_win: int = 21
    persistence_win: int = 42
    skew_win: int = 63
    kurt_win: int = 63
    vov_win: int = 21

    # ---- IC meta-learner ----
    ic_lambda: float = 0.95
    sleeve_ic_lambda: float = 0.94
    ic_clip: float = 0.25
    ic_min_cross_section: int = 15   # eligible pairwise assets required for daily IC
    ic_min_history: int = 21         # purged observations before factor trust is active
    ic_vol_floor: float = 0.02       # prevents tiny estimated IC vol from exploding ICIR
    ic_ir_clip: float = 3.0
    ic_hit_rate_win: int = 63
    ic_min_coverage: float = 0.50
    factor_corr_penalty: float = 0.30
    factor_min_diversification: float = 0.25
    factor_min_weight: float = 0.012 # proven factors only; shadow factors have no floor
    sleeve_corr_penalty: float = 0.35
    sleeve_min_weight: float = 0.10
    recency_boost: float = 0.10
    recency_win: int = 21

    # ---- sleeves + stress prior (§5) ----
    sleeves: tuple[SleeveSpec, ...] = (
        SleeveSpec("momentum", (21, 63), -0.60),
        SleeveSpec("defensive", (21,), +0.80),
        SleeveSpec("meanrev", (5, 21), +0.40),
        SleeveSpec("micro", (5, 21), +0.20),
        SleeveSpec("ml", (21,), 0.0, proven=False),
    )
    sleeve_horizon_for_weighting: int = 21
    stress_dd_cap: float = 0.10

    # ---- construction (§12.3) ----
    seats_base: int = 20
    seats_min: int = 15
    seats_max: int = 30
    seats_adaptive: bool = True
    seats_disp_slope: float = 4.0
    max_pos: float = 0.15
    min_pos: float = 0.005
    softmax_tilt_alpha: float = 0.60
    score_smooth_win: int = 4
    weight_smooth_alpha: float = 0.40
    no_trade_band: float = 0.04      # skip rebalance if L1 diff below this
    seat_weighting: str = "score"    # "score" | "hrp" | "blend"
    # statistical cluster caps (no sector data needed): seats whose trailing
    # correlation exceeds the threshold form a cluster; each cluster's total
    # weight is capped and the excess redistributed to the rest of the book
    cluster_corr_thresh: float = 0.70
    cluster_weight_cap: float = 0.40
    cluster_corr_win: int = 126

    # ---- risk budget (§12.4) ----
    target_vol: float = 0.18
    target_vol_stressed: float = 0.12
    lev_cap: float = 1.5
    lev_min: float = 0.40
    ewma_vol_lambda: float = 0.95
    dd_win: int = 126
    risk_off_stretch: float = 0.70
    risk_off_floor: float = 0.45
    overlay_vol_win: int = 63
    overlay_max_vol: float = 0.22
    overlay_clip: tuple[float, float] = (0.5, 1.25)
    cash_yield_annual: float = 0.045
    kill_dd_mult: float = 1.5
    backtest_max_dd: float = 0.10

    # ---- turbulence / regime avoidance (risk.py x turbulence.py) ----
    turbulence_enabled: bool = True
    turb_win: int = 504              # long "normal-times" covariance window
    turb_step: int = 5               # model refresh cadence (days)
    turb_shrink: float = 0.10        # diagonal covariance shrinkage
    turb_keep_frac: float = 0.80     # quiet-majority share kept when re-estimating
    turb_rank_win: int = 252         # percentile normalization window
    turb_on_pct: float = 0.90        # throttle engages above this percentile
    turb_full_pct: float = 0.99      # throttle saturates at this percentile
    turb_floor: float = 0.60         # deepest de-risking multiplier
    absorption_win: int = 126        # absorption tracks *current* coupling
    absorption_top_frac: float = 0.20
    absorption_weight: float = 0.35  # absorption share of the composite

    # ---- costs ----
    tc_bps: float = 3.0
    adv_participation_cap: float = 0.05

    # ---- ML sleeve ----
    ml_enabled: bool = True
    ml_model: str = "hist_gbrt"       # nonlinear interactions; ridge is fallback
    ml_refit_every: int = 21
    ml_train_win: int = 504
    ml_horizon: int = 21
    ml_ridge_alpha: float = 10.0
    ml_max_iter: int = 125
    ml_max_leaf_nodes: int = 15
    ml_learning_rate: float = 0.05
    ml_l2_regularization: float = 10.0
    ml_sample_half_life: int = 126
    ml_max_rows: int = 250000

    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sleeves"] = [asdict(s) for s in self.sleeves]
        return d

    def config_hash(self) -> str:
        """Provenance hash: identical hash => identical resolved config."""
        blob = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def nasdaq_lo_config(**overrides) -> SvyableConfig:
    return SvyableConfig(**overrides) if overrides else SvyableConfig()
