"""First-class Q23 strategy registry.

A strategy is a complete executable recipe: factor set, construction, risk
budget, cadence, maturity, and institutional mandate. The daily PM selector
compares whole candidate portfolios; agents never manufacture raw weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from svyable import factor_library as flib
from svyable.config import SvyableConfig, nasdaq_lo_config


DEFENSIVE = (
    "inv_vol", "inv_downside", "low_beta", "beta_stability",
    "amihud_inv", "vol_of_vol_inv", "skew_pref", "kurtosis_inv",
    "cross_sectional_dispersion", "max_lottery", "turnover_vol_inv",
    "inv_idio", "low_corr", "liquidity", "gk_inv_vol",
)
MOMENTUM = (
    "mom_12_1", "resid_mom", "resid_mom_short", "trend_consistency",
    "prox_52w_high", "slope_ema", "breakout", "mom_accel",
    "momentum_quality", "momentum_persistence", "overnight_bias",
    "attention_momentum", "anchoring_bias", "efficiency_ratio", "capm_alpha",
    "fip_momentum", "intermediate_momentum",
)
MEAN_REVERSION = (
    "srev", "resid_srev", "ou_zscore", "ou_predicted_return",
    "ou_mom_blend", "mean_reversion_speed", "disposition_alpha",
)
DAILY_FLOW = (
    "ofi_med", "mtf_ofi_alignment", "vpin_inv", "kyle_lambda_inv",
    "bvc_imbalance", "exec_quality", "flow_persistence", "obv_trend",
)
RESILIENCE = (
    "downside_beta_resilience", "drawdown_resilience", "gap_resilience",
    "correlation_shock_resilience", "beta_asymmetry",
)
INSTITUTIONAL_TREND = (
    "multi_horizon_trend", "residual_trend_tstat",
    "volume_confirmed_breakout", "vol_scaled_momentum", "liquidity_momentum",
)
RESIDUAL_ALPHA = (
    "residual_trend_tstat", "resid_mom", "resid_mom_short", "capm_alpha",
    "resid_srev", "ou_predicted_return", "low_corr", "inv_idio",
)


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    display_name: str
    family: str
    description: str
    factor_names: tuple[str, ...]
    config_overrides: dict[str, Any] = field(default_factory=dict)
    rebalance_interval_days: int = 1
    minimum_hold_days: int = 2
    forecast_horizon_days: int = 1
    maturity: str = "production_candidate"
    enabled_by_default: bool = True
    pitch_role: str = "alpha and beta"
    regime_profile: str = "balanced"

    def build_config(self, base: SvyableConfig | None = None) -> SvyableConfig:
        cfg = base or nasdaq_lo_config()
        return replace(
            cfg,
            strategy_id=f"candidate_{self.strategy_id}",
            **self.config_overrides,
        )

    def validate(self) -> None:
        available = set(flib.factor_metadata().index)
        missing = sorted(set(self.factor_names) - available)
        if missing:
            raise ValueError(
                f"Strategy {self.strategy_id} references missing factors: "
                + ", ".join(missing)
            )
        if self.rebalance_interval_days < 1 or self.minimum_hold_days < 0:
            raise ValueError(f"Invalid cadence for strategy {self.strategy_id}")
        if not self.factor_names:
            raise ValueError(f"Strategy {self.strategy_id} has no factors")


_REGISTRY: dict[str, StrategySpec] = {}


def register(spec: StrategySpec) -> StrategySpec:
    if spec.strategy_id in _REGISTRY:
        raise ValueError(f"Duplicate strategy id: {spec.strategy_id}")
    spec.validate()
    _REGISTRY[spec.strategy_id] = spec
    return spec


register(StrategySpec(
    strategy_id="q23_neural_alpha",
    display_name="Q23 Neural Alpha",
    family="broad behavioral ensemble",
    description=(
        "Broad Q23 price-action and behavioral ensemble with a purged nonlinear "
        "ML sleeve; closest Svyable port of the contest-era flagship."
    ),
    factor_names=DEFENSIVE + MOMENTUM + MEAN_REVERSION + DAILY_FLOW,
    config_overrides={
        "ml_enabled": True,
        "seats_base": 20,
        "seats_min": 15,
        "seats_max": 25,
        "score_smooth_win": 4,
        "weight_smooth_alpha": 0.35,
        "no_trade_band": 0.04,
        "target_vol": 0.17,
    },
    minimum_hold_days=3,
    pitch_role="nonlinear alpha ensemble",
))

register(StrategySpec(
    strategy_id="q23_hybrid_alpha",
    display_name="Q23 Hybrid Alpha",
    family="multi-sleeve ensemble",
    description=(
        "Balanced defensive, momentum, OU/reversal, and daily-flow ensemble; "
        "the robust default candidate without nonlinear model dependency."
    ),
    factor_names=DEFENSIVE + MOMENTUM + MEAN_REVERSION + DAILY_FLOW,
    config_overrides={
        "ml_enabled": False,
        "seats_base": 20,
        "score_smooth_win": 4,
        "weight_smooth_alpha": 0.40,
        "no_trade_band": 0.045,
        "target_vol": 0.16,
    },
    minimum_hold_days=3,
    pitch_role="diversified core alpha",
))

register(StrategySpec(
    strategy_id="q23_concentrated",
    display_name="Q23 Concentrated Flagship",
    family="concentrated conviction book",
    description=(
        "Contest-identity book: 7-10 names selected by the full Q23 ensemble. "
        "Concentration comes from construction, not a bespoke signal engine."
    ),
    factor_names=DEFENSIVE + MOMENTUM + MEAN_REVERSION + DAILY_FLOW,
    config_overrides={
        "ml_enabled": False,
        "seats_base": 9,
        "seats_min": 7,
        "seats_max": 10,
        "max_pos": 0.12,
        "min_pos": 0.02,
        "score_smooth_win": 5,
        "weight_smooth_alpha": 0.30,
        "no_trade_band": 0.06,
        "target_vol": 0.17,
        "cluster_weight_cap": 0.30,
    },
    minimum_hold_days=5,
    pitch_role="high-conviction flagship",
))

register(StrategySpec(
    strategy_id="q23_momentum_quality",
    display_name="Q23 Momentum Quality",
    family="trend / continuation",
    description=(
        "Residual and classic momentum, trend consistency, breakout, attention, "
        "and quality-of-trend factors with defensive risk controls."
    ),
    factor_names=DEFENSIVE[:8] + MOMENTUM,
    config_overrides={
        "ml_enabled": False,
        "seats_base": 18,
        "seats_min": 15,
        "seats_max": 24,
        "score_smooth_win": 5,
        "weight_smooth_alpha": 0.32,
        "no_trade_band": 0.05,
        "target_vol": 0.17,
    },
    minimum_hold_days=4,
    pitch_role="medium-horizon trend alpha",
))

register(StrategySpec(
    strategy_id="q23_ou_mean_reversion",
    display_name="Q23 OU Mean Reversion",
    family="short-horizon reversal",
    description=(
        "Residual reversal and Ornstein-Uhlenbeck signals with low-risk and "
        "liquidity controls; faster and more cost-sensitive."
    ),
    factor_names=DEFENSIVE[:8] + MEAN_REVERSION,
    config_overrides={
        "ml_enabled": False,
        "seats_base": 22,
        "seats_min": 18,
        "seats_max": 28,
        "score_smooth_win": 2,
        "weight_smooth_alpha": 0.55,
        "no_trade_band": 0.025,
        "target_vol": 0.12,
        "tc_bps": 4.0,
    },
    minimum_hold_days=1,
    pitch_role="short-horizon statistical alpha",
    regime_profile="fast",
))

register(StrategySpec(
    strategy_id="q23_defensive_alpha",
    display_name="Q23 Defensive Alpha",
    family="low risk / capital preservation",
    description=(
        "Low volatility, downside risk, beta stability, liquidity, and selected "
        "slow momentum factors for stressed or low-conviction regimes."
    ),
    factor_names=DEFENSIVE + RESILIENCE + (
        "mom_12_1", "resid_mom", "trend_consistency", "momentum_quality",
        "prox_52w_high", "capm_alpha",
    ),
    config_overrides={
        "ml_enabled": False,
        "seats_base": 25,
        "seats_min": 20,
        "seats_max": 30,
        "max_pos": 0.10,
        "score_smooth_win": 6,
        "weight_smooth_alpha": 0.28,
        "no_trade_band": 0.06,
        "target_vol": 0.13,
        "target_vol_stressed": 0.09,
        "regime_boost_cap": 1.0,
        "turb_floor": 0.50,
    },
    rebalance_interval_days=2,
    minimum_hold_days=5,
    pitch_role="drawdown and beta defense",
    regime_profile="defensive",
))

register(StrategySpec(
    strategy_id="q23_low_turnover",
    display_name="Q23 Low Turnover",
    family="slow ensemble",
    description=(
        "Slow residual momentum, 12-1 momentum, low risk, and stable OU state "
        "with wide no-trade bands; deliberately difficult to dislodge."
    ),
    factor_names=DEFENSIVE + (
        "mom_12_1", "resid_mom", "trend_consistency", "prox_52w_high",
        "momentum_quality", "capm_alpha", "ou_mom_blend",
    ),
    config_overrides={
        "ml_enabled": False,
        "seats_base": 25,
        "seats_min": 20,
        "seats_max": 30,
        "score_smooth_win": 8,
        "weight_smooth_alpha": 0.20,
        "no_trade_band": 0.08,
        "target_vol": 0.15,
    },
    rebalance_interval_days=3,
    minimum_hold_days=7,
    pitch_role="capacity and implementation core",
    regime_profile="slow",
))

register(StrategySpec(
    strategy_id="q23_alpha_beta",
    display_name="Q23 Alpha + Beta Capture",
    family="calm-regime participation",
    description=(
        "Captures broad upside participation through multi-horizon trend and "
        "beta asymmetry while preserving low-risk and cluster controls."
    ),
    factor_names=DEFENSIVE + RESILIENCE + INSTITUTIONAL_TREND + (
        "mom_12_1", "fip_momentum", "intermediate_momentum", "capm_alpha",
    ),
    config_overrides={
        "ml_enabled": False,
        "seats_base": 18,
        "seats_min": 14,
        "seats_max": 24,
        "seat_weighting": "blend",
        "max_pos": 0.12,
        "cluster_weight_cap": 0.32,
        "score_smooth_win": 4,
        "weight_smooth_alpha": 0.35,
        "no_trade_band": 0.04,
        "target_vol": 0.18,
        "regime_boost_cap": 1.12,
        "turb_floor": 0.55,
    },
    minimum_hold_days=3,
    pitch_role="beta participation with asymmetric defense",
    regime_profile="risk_on",
))

register(StrategySpec(
    strategy_id="q23_crash_resilient_momentum",
    display_name="Q23 Crash-Resilient Momentum",
    family="managed momentum",
    description=(
        "Multi-horizon and residual trend selected jointly with downside beta, "
        "drawdown, gap, and correlation-shock resilience."
    ),
    factor_names=INSTITUTIONAL_TREND + RESILIENCE + (
        "mom_12_1", "fip_momentum", "intermediate_momentum",
        "momentum_quality", "trend_consistency", "prox_52w_high",
        "gk_inv_vol", "inv_idio", "low_corr", "liquidity",
    ),
    config_overrides={
        "ml_enabled": False,
        "seats_base": 20,
        "seats_min": 16,
        "seats_max": 26,
        "seat_weighting": "blend",
        "max_pos": 0.10,
        "cluster_weight_cap": 0.30,
        "score_smooth_win": 5,
        "weight_smooth_alpha": 0.30,
        "no_trade_band": 0.05,
        "target_vol": 0.15,
        "target_vol_stressed": 0.09,
        "turb_on_pct": 0.85,
        "panic_weight": 0.30,
        "regime_boost_cap": 1.04,
        "turb_floor": 0.45,
    },
    minimum_hold_days=4,
    pitch_role="momentum alpha with crash control",
    regime_profile="defensive_trend",
))

register(StrategySpec(
    strategy_id="q23_residual_alpha",
    display_name="Q23 Residual Alpha",
    family="beta-stripped statistical alpha",
    description=(
        "Residual trend, residual reversal, OU, Jensen alpha, low correlation, "
        "and idiosyncratic-risk control for a cleaner stock-selection book."
    ),
    factor_names=RESIDUAL_ALPHA + RESILIENCE + (
        "liquidity", "gk_inv_vol", "turnover_vol_inv", "efficiency_ratio",
    ),
    config_overrides={
        "ml_enabled": False,
        "seats_base": 22,
        "seats_min": 16,
        "seats_max": 28,
        "seat_weighting": "hrp",
        "max_pos": 0.09,
        "cluster_weight_cap": 0.28,
        "score_smooth_win": 4,
        "weight_smooth_alpha": 0.35,
        "no_trade_band": 0.04,
        "target_vol": 0.14,
        "regime_boost_cap": 1.02,
    },
    minimum_hold_days=3,
    pitch_role="idiosyncratic stock-selection alpha",
    regime_profile="market_aware",
))

register(StrategySpec(
    strategy_id="q23_dispersion_alpha",
    display_name="Q23 Dispersion Alpha",
    family="cross-sectional opportunity",
    description=(
        "Targets periods with wide cross-sectional opportunity using residual "
        "trend, low correlation, reversal, liquidity, and adaptive seat breadth."
    ),
    factor_names=(
        "cross_sectional_dispersion", "residual_trend_tstat", "resid_mom",
        "resid_srev", "ou_predicted_return", "low_corr", "inv_idio",
        "liquidity", "drawdown_resilience", "beta_asymmetry",
    ),
    config_overrides={
        "ml_enabled": False,
        "seats_base": 24,
        "seats_min": 14,
        "seats_max": 30,
        "seats_disp_slope": 6.0,
        "seat_weighting": "blend",
        "max_pos": 0.09,
        "cluster_weight_cap": 0.28,
        "score_smooth_win": 3,
        "weight_smooth_alpha": 0.40,
        "no_trade_band": 0.035,
        "target_vol": 0.13,
        "regime_boost_cap": 1.03,
    },
    minimum_hold_days=2,
    pitch_role="dispersion and relative-value alpha",
    regime_profile="dispersion",
))

register(StrategySpec(
    strategy_id="q23_flow_alpha",
    display_name="Q23 Daily Flow Alpha",
    family="daily-bar flow proxy",
    description=(
        "Q23 OFI, VPIN, Kyle, BVC, execution-quality, and flow-persistence "
        "proxies; experimental until true intraday trade/quote data exists."
    ),
    factor_names=DEFENSIVE[:5] + DAILY_FLOW + (
        "resid_mom_short", "efficiency_ratio", "attention_momentum",
    ),
    config_overrides={
        "ml_enabled": False,
        "seats_base": 20,
        "score_smooth_win": 2,
        "weight_smooth_alpha": 0.50,
        "no_trade_band": 0.03,
        "target_vol": 0.12,
        "tc_bps": 5.0,
    },
    minimum_hold_days=1,
    maturity="experimental",
    enabled_by_default=False,
    pitch_role="microstructure research proxy",
    regime_profile="experimental",
))


def get_strategy(strategy_id: str) -> StrategySpec:
    try:
        return _REGISTRY[strategy_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown strategy {strategy_id!r}; available: {', '.join(_REGISTRY)}"
        ) from exc


def list_strategies(*, include_experimental: bool = True) -> list[StrategySpec]:
    values = list(_REGISTRY.values())
    if not include_experimental:
        values = [spec for spec in values if spec.maturity != "experimental"]
    return values


def default_strategy_ids() -> list[str]:
    return [
        spec.strategy_id
        for spec in _REGISTRY.values()
        if spec.enabled_by_default
    ]


def registry_frame():
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "strategy_id": spec.strategy_id,
                "name": spec.display_name,
                "family": spec.family,
                "pitch_role": spec.pitch_role,
                "regime_profile": spec.regime_profile,
                "maturity": spec.maturity,
                "factors": len(spec.factor_names),
                "rebalance_days": spec.rebalance_interval_days,
                "minimum_hold_days": spec.minimum_hold_days,
                "ml_enabled": bool(spec.config_overrides.get("ml_enabled", False)),
                "target_vol": spec.build_config().target_vol,
                "enabled_by_default": spec.enabled_by_default,
                "description": spec.description,
            }
            for spec in _REGISTRY.values()
        ]
    ).set_index("strategy_id")
