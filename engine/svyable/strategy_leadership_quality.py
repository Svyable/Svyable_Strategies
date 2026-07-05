"""Svyable Leadership Quality strategy recipe."""

from __future__ import annotations

from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_registry import INSTITUTIONAL_TREND, RESIDUAL_ALPHA, RESILIENCE, StrategySpec, register
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


LEADERSHIP_QUALITY = (
    "residual_leadership_persistence",
    "tight_base_breakout_quality",
    "drawdown_repair_velocity",
    "trend_efficiency_stability",
    "upside_volume_asymmetry",
    "quiet_accumulation_pressure",
)


def register_leadership_quality_strategy() -> None:
    register(StrategySpec(
        strategy_id="svyable_leadership_quality",
        display_name="Svyable Leadership Quality",
        family="durable leadership ensemble",
        description=(
            "Svyable-designed medium-horizon alpha book focused on persistent residual leadership, "
            "tight-base breakouts, drawdown repair, efficient trends, upside dollar-volume asymmetry, "
            "and quiet accumulation. It complements faster Tape Acceleration and residual Alpha Catalyst "
            "books with a slower, more stable leadership lens."
        ),
        factor_names=tuple(dict.fromkeys(
            LEADERSHIP_QUALITY + ALPHA_CATALYST + TAPE_ACCELERATION + RESIDUAL_ALPHA + INSTITUTIONAL_TREND + RESILIENCE + (
                "prox_52w_high", "intermediate_momentum", "fip_momentum", "momentum_quality",
                "trend_consistency", "efficiency_ratio", "liquidity", "liquidity_momentum",
                "gk_inv_vol", "turnover_vol_inv", "low_corr", "inv_idio",
            )
        )),
        config_overrides={
            "ml_enabled": False,
            "seats_base": 18,
            "seats_min": 14,
            "seats_max": 24,
            "seat_weighting": "blend",
            "max_pos": 0.085,
            "cluster_weight_cap": 0.26,
            "score_smooth_win": 5,
            "weight_smooth_alpha": 0.38,
            "no_trade_band": 0.040,
            "target_vol": 0.145,
            "target_vol_stressed": 0.085,
            "tc_bps": 4.0,
            "regime_boost_cap": 1.04,
            "turb_floor": 0.54,
        },
        minimum_hold_days=4,
        pitch_role="durable leadership alpha",
        regime_profile="leadership_quality",
    ))


register_leadership_quality_strategy()
