"""Strategy configuration. One dataclass; strategies are configs, not code forks.

Defaults implement svyable_nasdaq_lo with explicit price-action factors,
transaction costs, dispersion-aware construction, volatility management, and a
causal turbulence/breadth regime stack.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict


@dataclass(frozen=True)
class SleeveSpec:
    name: str
    horizons: tuple[int, ...]
    stress_mult: float
    proven: bool = True


@dataclass(frozen=True)
class SvyableConfig:
    strategy_id: str = "svyable_nasdaq_lo"
    version: str = "0.3.0"

    # ---- universe ----
    min_price: float = 5.0
    min_adv: float = 25e6
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
    trend_horizons: tuple[int, ...] = (21, 63, 126, 252)
    trend_tstat_win: int = 126
    resilience_win: int = 126
    gap_risk_win: int = 63

    # ---- IC meta-learner ----
    ic_lambda: float = 0.95
    sleeve_ic_lambda: float = 0.94
    ic_clip: float = 0.25
    ic_min_cross_section: int = 15
    ic_min_history: int = 21
    ic_vol_floor: float = 0.02
    ic_ir_clip: float = 3.0
    ic_hit_rate_win: int = 63
    ic_min_coverage: float = 0.50
    factor_corr_penalty: float = 0.30
    factor_min_diversification: float = 0.25
    factor_min_weight: float = 0.012
    sleeve_corr_penalty: float = 0.35
    sleeve_min_weight: float = 0.10
    recency_boost: float = 0.10
    recency_win: int = 21

    # ---- sleeves + stress prior ----
    sleeves: tuple[SleeveSpec, ...] = (
        SleeveSpec("momentum", (21, 63), -0.60),
        SleeveSpec("defensive", (21,), +0.80),
        SleeveSpec("meanrev", (5, 21), +0.40),
        SleeveSpec("micro", (5, 21), +0.20),
        SleeveSpec("ml", (21,), 0.0, proven=False),
    )
    sleeve_horizon_for_weighting: int = 21
    stress_dd_cap: float = 0.10

    # ---- construction ----
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
    no_trade_band: float = 0.04
    seat_weighting: str = "score"
    cluster_corr_thresh: float = 0.70
    cluster_weight_cap: float = 0.40
    cluster_corr_win: int = 126

    # ---- risk budget ----
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
    # circuit breaker: on breach, cut the book to kill_lev (distinct from and
    # below lev_min, so the kill is a real de-risk, not a no-op) and stay
    # latched until own-book drawdown recovers below kill_rearm_mult x max_dd.
    kill_lev: float = 0.0
    kill_rearm_mult: float = 1.0

    # ---- turbulence / breadth / panic regime ----
    turbulence_enabled: bool = True
    turb_win: int = 504
    turb_step: int = 5
    turb_shrink: float = 0.10
    turb_keep_frac: float = 0.80
    turb_rank_win: int = 252
    turb_on_pct: float = 0.90
    turb_full_pct: float = 0.99
    turb_floor: float = 0.60
    absorption_win: int = 126
    absorption_top_frac: float = 0.20
    absorption_weight: float = 0.30
    breadth_win: int = 126
    breadth_smooth: int = 10
    breadth_on: float = 0.45
    breadth_full: float = 0.25
    breadth_weight: float = 0.20
    panic_vol_win: int = 21
    panic_vol_baseline_win: int = 252
    panic_vol_z_on: float = 1.0
    panic_vol_z_full: float = 3.0
    panic_dd_on: float = 0.08
    panic_dd_full: float = 0.20
    panic_weight: float = 0.20
    regime_boost_cap: float = 1.05
    regime_boost_breadth: float = 0.65
    regime_boost_turb_pct: float = 0.50
    # exposure cap applied while the turbulence model is still in burn-in (not
    # yet estimable). 1.0 = fail open (backtest default); set below 1.0 for a
    # live launch on short history so the book runs light until the structural
    # regime signal is warm.
    regime_warmup_floor: float = 1.0

    # ---- costs ----
    tc_bps: float = 3.0
    adv_participation_cap: float = 0.05

    # ---- ML sleeve ----
    ml_enabled: bool = True
    ml_model: str = "hist_gbrt"
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
        payload = asdict(self)
        payload["sleeves"] = [asdict(sleeve) for sleeve in self.sleeves]
        return payload

    def config_hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def nasdaq_lo_config(**overrides) -> SvyableConfig:
    return SvyableConfig(**overrides) if overrides else SvyableConfig()
