"""Additional Svyable-designed price-action strategy recipe."""

from __future__ import annotations

from svyable.strategy_registry import INSTITUTIONAL_TREND, RESILIENCE, StrategySpec, register


PRICE_ACTION_FRONTIER = (
    "channel_pressure",
    "compression_thrust",
    "gap_continuation",
    "range_participation",
    "range_rejection",
)


def register_price_action_frontier_strategy() -> None:
    register(StrategySpec(
        strategy_id="svyable_frontier_price_action",
        display_name="Svyable Frontier Price Action",
        family="frontier price-action ensemble",
        description=(
            "Svyable-designed OHLCV tape-reading book: channel pressure, volatility "
            "compression thrust, gap continuation, range participation, and failed "
            "range-extension reversal, blended with institutional trend and resilience controls."
        ),
        factor_names=tuple(dict.fromkeys(
            PRICE_ACTION_FRONTIER + INSTITUTIONAL_TREND + RESILIENCE + (
                "ma_cloud", "vol_breakout", "volume_confirmed_breakout",
                "multi_horizon_trend", "residual_trend_tstat", "hloc_close_position",
                "efficiency_ratio", "gk_inv_vol", "inv_idio", "low_corr", "liquidity",
            )
        )),
        config_overrides={
            "ml_enabled": False,
            "seats_base": 18,
            "seats_min": 14,
            "seats_max": 24,
            "seat_weighting": "blend",
            "max_pos": 0.10,
            "cluster_weight_cap": 0.30,
            "score_smooth_win": 3,
            "weight_smooth_alpha": 0.42,
            "no_trade_band": 0.035,
            "target_vol": 0.16,
            "target_vol_stressed": 0.10,
            "regime_boost_cap": 1.07,
            "turb_floor": 0.50,
        },
        minimum_hold_days=2,
        pitch_role="frontier price-action alpha",
        regime_profile="price_action",
    ))


register_price_action_frontier_strategy()
