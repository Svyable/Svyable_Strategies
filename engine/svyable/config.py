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
    version: str = "0.1.0"

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

    # ---- IC meta-learner (strategy.md §2.2-2.4, §8.1-8.2) ----
    ic_lambda: float = 0.95          # factor-level EWMA
    sleeve_ic_lambda: float = 0.94   # sleeve-level EWMA
    ic_clip: float = 0.25
    factor_corr_penalty: float = 0.30
    factor_min_diversification: float = 0.25
    factor_min_weight: float = 0.012
    sleeve_corr_penalty: float = 0.35
    sleeve_min_weight: float = 0.10
    recency_boost: float = 0.10      # causal rolling boost strength (§8.1 fix)
    recency_win: int = 21

    # ---- sleeves + stress prior (§5) ----
    sleeves: tuple[SleeveSpec, ...] = (
        SleeveSpec("momentum", (21, 63), -0.60),
        SleeveSpec("defensive", (21,), +0.80),
        SleeveSpec("meanrev", (5, 21), +0.40),
        SleeveSpec("micro", (5, 21), +0.20),
        SleeveSpec("ml", (21,), 0.0, proven=False),   # shadow: earns weight only via IC
    )
    sleeve_horizon_for_weighting: int = 21
    stress_dd_cap: float = 0.10      # market dd at which stress saturates to 1

    # ---- construction (§12.3) ----
    seats_base: int = 20
    seats_min: int = 15
    seats_max: int = 30
    seats_adaptive: bool = True
    seats_disp_slope: float = 4.0    # seats shed per +1 z of score dispersion
    max_pos: float = 0.15            # sanity ceiling — risk/ADV caps should bind first
    min_pos: float = 0.005
    softmax_tilt_alpha: float = 0.60 # blend toward conviction softmax
    score_smooth_win: int = 4
    weight_smooth_alpha: float = 0.40
    no_trade_band: float = 0.04      # skip rebalance if L1 diff below this
    seat_weighting: str = "score"    # "score" | "hrp" | "blend"

    # ---- risk budget (§12.4) ----
    target_vol: float = 0.18
    target_vol_stressed: float = 0.12
    lev_cap: float = 1.5             # raise toward 2.0 only per roadmap unlock schedule
    lev_min: float = 0.40
    ewma_vol_lambda: float = 0.95
    dd_win: int = 126
    risk_off_stretch: float = 0.70
    risk_off_floor: float = 0.45
    overlay_vol_win: int = 63
    overlay_max_vol: float = 0.22
    overlay_clip: tuple[float, float] = (0.5, 1.25)
    cash_yield_annual: float = 0.045
    kill_dd_mult: float = 1.5        # live dd > mult x backtest MaxDD -> cut to lev_min
    backtest_max_dd: float = 0.10    # refreshed from walk-forward reports

    # ---- costs ----
    tc_bps: float = 3.0              # measured-cost placeholder; contest model was ~10
    adv_participation_cap: float = 0.05  # execution-layer: max position vs 21d ADV

    # ---- ML sleeve ----
    ml_enabled: bool = True          # degrades gracefully if sklearn missing
    ml_refit_every: int = 21         # trading days
    ml_train_win: int = 504
    ml_horizon: int = 21
    ml_ridge_alpha: float = 10.0

    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sleeves"] = [asdict(s) for s in self.sleeves]
        return d

    def config_hash(self) -> str:
        """Provenance hash (§8.7): identical hash => identical resolved config."""
        blob = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def nasdaq_lo_config(**overrides) -> SvyableConfig:
    return SvyableConfig(**overrides) if overrides else SvyableConfig()
