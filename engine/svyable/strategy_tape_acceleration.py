"""Svyable Tape Acceleration strategy recipe."""

from __future__ import annotations

from svyable.strategy_registry import INSTITUTIONAL_TREND, RESILIENCE, StrategySpec, register


TAPE_ACCELERATION = (
    "liquidity_squeeze_breakout",
    "pullback_reclaim",
    "gap_reversal_pressure",
    "opening_drive_continuation",
    "exhaustion_reversal",
    "range_volume_acceleration",
)


def register_tape_acceleration_strategy() -> None:
    register(StrategySpec(
        strategy_id="svyable_tape_acceleration",
        display_name="Svyable Tape Acceleration",
        family="frontier tape-acceleration ensemble",
        description=(
            "Svyable-designed daily OHLCV alpha book focused on post-compression "
            "breakouts, trend pullback reclaims, gap rejection/continuation, exhaustion "
            "reversals, and range-volume acceleration, blended with institutional trend "
            "and resilience controls."
        ),
        factor_names=tuple(dict.fromkeys(
            TAPE_ACCELERATION + INSTITUTIONAL_TREND + RESILIENCE + (
                "channel_pressure", "compression_thrust", "range_participation",
                "range_rejection", "residual_trend_tstat", "multi_horizon_trend",
                "volume_confirmed_breakout", "efficiency_ratio", "gk_inv_vol",
                "inv_idio", "low_corr", "liquidity", "turnover_vol_inv",
            )
        )),
        config_overrides={
            "ml_enabled": False,
            "seats_base": 20,
            "seats_min": 16,
            "seats_max": 28,
            "seat_weighting": "blend",
            "max_pos": 0.095,
            "cluster_weight_cap": 0.30,
            "score_smooth_win": 3,
            "weight_smooth_alpha": 0.44,
            "no_trade_band": 0.032,
            "target_vol": 0.155,
            "target_vol_stressed": 0.095,
            "tc_bps": 4.0,
            "regime_boost_cap": 1.06,
            "turb_floor": 0.52,
        },
        minimum_hold_days=2,
        pitch_role="tape-acceleration alpha",
        regime_profile="tape_acceleration",
    ))


register_tape_acceleration_strategy()
