"""Svyable Alpha Catalyst strategy recipe."""

from __future__ import annotations

from svyable.strategy_registry import INSTITUTIONAL_TREND, RESIDUAL_ALPHA, RESILIENCE, StrategySpec, register
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


ALPHA_CATALYST = (
    "residual_momentum_acceleration",
    "residual_breakout_confirmation",
    "downside_absorption_reversal",
    "failed_breakdown_reclaim",
    "idiosyncratic_trend_quality",
    "volatility_transition_alpha",
)


def register_alpha_catalyst_strategy() -> None:
    register(StrategySpec(
        strategy_id="svyable_alpha_catalyst",
        display_name="Svyable Alpha Catalyst",
        family="residual catalyst ensemble",
        description=(
            "Svyable-designed residual alpha book focused on beta-stripped acceleration, "
            "residual breakouts, downside absorption, failed breakdown reclaims, idiosyncratic "
            "trend quality, and volatility-transition thrust. It blends those catalysts with "
            "Tape Acceleration, residual-alpha, institutional trend, resilience, liquidity, and "
            "idiosyncratic-risk controls."
        ),
        factor_names=tuple(dict.fromkeys(
            ALPHA_CATALYST + TAPE_ACCELERATION + RESIDUAL_ALPHA + INSTITUTIONAL_TREND + RESILIENCE + (
                "channel_pressure", "compression_thrust", "range_participation",
                "range_rejection", "efficiency_ratio", "gk_inv_vol", "turnover_vol_inv",
                "liquidity", "liquidity_momentum", "momentum_quality", "trend_consistency",
            )
        )),
        config_overrides={
            "ml_enabled": False,
            "seats_base": 18,
            "seats_min": 14,
            "seats_max": 26,
            "seat_weighting": "blend",
            "max_pos": 0.09,
            "cluster_weight_cap": 0.28,
            "score_smooth_win": 3,
            "weight_smooth_alpha": 0.46,
            "no_trade_band": 0.030,
            "target_vol": 0.15,
            "target_vol_stressed": 0.09,
            "tc_bps": 4.5,
            "regime_boost_cap": 1.05,
            "turb_floor": 0.50,
        },
        minimum_hold_days=2,
        pitch_role="residual catalyst alpha",
        regime_profile="alpha_catalyst",
    ))


register_alpha_catalyst_strategy()
