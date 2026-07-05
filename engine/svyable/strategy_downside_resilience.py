"""Svyable Downside Resilience strategy recipe."""

from __future__ import annotations

from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_leadership_quality import LEADERSHIP_QUALITY
from svyable.strategy_registry import DEFENSIVE, INSTITUTIONAL_TREND, RESIDUAL_ALPHA, RESILIENCE, StrategySpec, register


DOWNSIDE_RESILIENCE = (
    "down_market_residual_strength",
    "downside_capture_inverse",
    "panic_reclaim_strength",
    "drawdown_floor_stability",
    "liquidity_safety_momentum",
    "volatility_cooldown_momentum",
)


def register_downside_resilience_strategy() -> None:
    register(StrategySpec(
        strategy_id="svyable_downside_resilience",
        display_name="Svyable Downside Resilience",
        family="defensive residual alpha ensemble",
        description=(
            "Svyable-designed defensive alpha book focused on residual strength during weak markets, "
            "low downside capture, broad-selloff reclaim behavior, drawdown-floor stability, stress liquidity, "
            "and volatility-cooldown momentum. It complements faster alpha books with a lower-volatility, "
            "risk-aware candidate for difficult regimes."
        ),
        factor_names=tuple(dict.fromkeys(
            DOWNSIDE_RESILIENCE + RESILIENCE + DEFENSIVE + RESIDUAL_ALPHA + INSTITUTIONAL_TREND + ALPHA_CATALYST + LEADERSHIP_QUALITY + (
                "liquidity", "liquidity_momentum", "gk_inv_vol", "turnover_vol_inv", "inv_idio", "low_corr",
            )
        )),
        config_overrides={
            "ml_enabled": False,
            "seats_base": 16,
            "seats_min": 12,
            "seats_max": 22,
            "seat_weighting": "blend",
            "max_pos": 0.075,
            "cluster_weight_cap": 0.24,
            "score_smooth_win": 6,
            "weight_smooth_alpha": 0.34,
            "no_trade_band": 0.045,
            "target_vol": 0.120,
            "target_vol_stressed": 0.070,
            "tc_bps": 4.0,
            "regime_boost_cap": 1.02,
            "turb_floor": 0.62,
        },
        minimum_hold_days=5,
        pitch_role="defensive residual alpha",
        regime_profile="downside_resilience",
    ))


register_downside_resilience_strategy()
