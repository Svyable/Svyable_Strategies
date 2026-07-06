"""Svyable Rotation Breadth strategy recipe."""

from __future__ import annotations

from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_leadership_quality import LEADERSHIP_QUALITY
from svyable.strategy_registry import INSTITUTIONAL_TREND, RESIDUAL_ALPHA, RESILIENCE, StrategySpec, register
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


ROTATION_BREADTH = (
    "relative_momentum_spread",
    "rank_improvement_velocity",
    "relative_volume_sponsorship",
    "breadth_thrust_participation",
    "leader_pullback_accumulation",
    "weak_breadth_relative_reclaim",
)


def register_rotation_breadth_strategy() -> None:
    register(StrategySpec(
        strategy_id="svyable_rotation_breadth",
        display_name="Svyable Rotation Breadth",
        family="cross-sectional rotation ensemble",
        description=(
            "Svyable-designed rotation book focused on improving relative momentum rank, volume sponsorship, "
            "breadth-thrust participation, leader pullback accumulation, and single-name reclaim behavior "
            "during weak breadth. It complements absolute tape/catalyst books by catching early leadership rotation."
        ),
        factor_names=tuple(dict.fromkeys(
            ROTATION_BREADTH + TAPE_ACCELERATION + ALPHA_CATALYST + LEADERSHIP_QUALITY + RESIDUAL_ALPHA + INSTITUTIONAL_TREND + RESILIENCE + (
                "prox_52w_high", "intermediate_momentum", "fip_momentum", "momentum_quality",
                "trend_consistency", "efficiency_ratio", "liquidity", "liquidity_momentum",
                "gk_inv_vol", "turnover_vol_inv", "low_corr", "inv_idio",
            )
        )),
        config_overrides={
            "ml_enabled": False,
            "seats_base": 20,
            "seats_min": 16,
            "seats_max": 28,
            "seat_weighting": "blend",
            "max_pos": 0.085,
            "cluster_weight_cap": 0.27,
            "score_smooth_win": 4,
            "weight_smooth_alpha": 0.42,
            "no_trade_band": 0.034,
            "target_vol": 0.155,
            "target_vol_stressed": 0.092,
            "tc_bps": 4.2,
            "regime_boost_cap": 1.05,
            "turb_floor": 0.53,
        },
        minimum_hold_days=3,
        pitch_role="early leadership rotation alpha",
        regime_profile="rotation_breadth",
    ))


register_rotation_breadth_strategy()
