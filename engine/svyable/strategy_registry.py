"""First-class Q23 strategy registry.

A strategy is a complete executable recipe: factors, construction parameters,
risk budget, expected holding period, rebalance cadence, and maturity. The daily
PM selector compares whole candidate portfolios; it never mixes arbitrary factor
profiles or lets an agent manufacture weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from svyable.config import SvyableConfig, nasdaq_lo_config
from svyable import factor_library as flib


DEFENSIVE = (
    "inv_vol", "inv_downside", "low_beta", "beta_stability",
    "amihud_inv", "vol_of_vol_inv", "skew_pref", "kurtosis_inv",
    "cross_sectional_dispersion", "max_lottery", "turnover_vol_inv",
)
MOMENTUM = (
    "mom_12_1", "resid_mom", "resid_mom_short", "trend_consistency",
    "prox_52w_high", "slope_ema", "breakout", "mom_accel",
    "momentum_quality", "momentum_persistence", "overnight_bias",
    "attention_momentum", "anchoring_bias", "efficiency_ratio", "capm_alpha",
)
MEAN_REVERSION = (
    "srev", "resid_srev", "ou_zscore", "ou_predicted_return",
    "ou_mom_blend", "mean_reversion_speed", "disposition_alpha",
)
DAILY_FLOW = (
    "ofi_med", "mtf_ofi_alignment", "vpin_inv", "kyle_lambda_inv",
    "bvc_imbalance", "exec_quality", "flow_persistence", "obv_trend",
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
        "ML sleeve. This is the closest Svyable port of the contest-era flagship."
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
))

register(StrategySpec(
    strategy_id="q23_hybrid_alpha",
    display_name="Q23 Hybrid Alpha",
    family="multi-sleeve ensemble",
    description=(
        "Balanced defensive, momentum, OU/reversal, and daily-flow ensemble. "
        "No nonlinear ML dependency; designed as the robust default candidate."
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
))

register(StrategySpec(
    strategy_id="q23_concentrated",
    display_name="Q23 Concentrated Flagship",
    family="concentrated conviction book",
    description=(
        "The contest-identity book: 7-10 NASDAQ names at roughly 10% apiece, "
        "selected by the full Q23 behavioral/price-action ensemble. Concentration "
        "comes from construction (seats + position ceiling), not from a different "
        "factor set — the alpha engine is identical to the hybrid ensemble."
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
        # a 3-name cluster is a third of the book; cap correlated clusters tighter
        "cluster_weight_cap": 0.30,
    },
    minimum_hold_days=5,
))

register(StrategySpec(
    strategy_id="q23_momentum_quality",
    display_name="Q23 Momentum Quality",
    family="trend / continuation",
    description=(
        "Residual and classic momentum, trend consistency, breakout, attention, "
        "and quality-of-trend factors with defensive risk controls."
    ),
    factor_names=DEFENSIVE[:6] + MOMENTUM,
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
))

register(StrategySpec(
    strategy_id="q23_ou_mean_reversion",
    display_name="Q23 OU Mean Reversion",
    family="short-horizon reversal",
    description=(
        "Residual reversal and Ornstein-Uhlenbeck signals with low-risk and "
        "liquidity controls. Faster, more cost-sensitive rebalance behavior."
    ),
    factor_names=DEFENSIVE[:6] + MEAN_REVERSION,
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
))

register(StrategySpec(
    strategy_id="q23_defensive_alpha",
    display_name="Q23 Defensive Alpha",
    family="low risk / capital preservation",
    description=(
        "Low volatility, downside risk, beta stability, liquidity, and selected "
        "slow momentum factors for stressed or low-conviction regimes."
    ),
    factor_names=DEFENSIVE + (
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
    },
    rebalance_interval_days=2,
    minimum_hold_days=5,
))

register(StrategySpec(
    strategy_id="q23_low_turnover",
    display_name="Q23 Low Turnover",
    family="slow ensemble",
    description=(
        "Slow residual momentum, 12-1 momentum, low risk, and stable OU state "
        "with wide no-trade bands. Intended to be difficult to dislodge."
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
))

register(StrategySpec(
    strategy_id="q23_flow_alpha",
    display_name="Q23 Daily Flow Alpha",
    family="daily-bar flow proxy",
    description=(
        "Q23 OFI, VPIN, Kyle, BVC, execution-quality, and flow-persistence "
        "proxies. Kept experimental until true intraday trade/quote data exists."
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
    return [spec.strategy_id for spec in _REGISTRY.values() if spec.enabled_by_default]


def registry_frame():
    import pandas as pd

    return pd.DataFrame([
        {
            "strategy_id": spec.strategy_id,
            "name": spec.display_name,
            "family": spec.family,
            "maturity": spec.maturity,
            "factors": len(spec.factor_names),
            "rebalance_days": spec.rebalance_interval_days,
            "minimum_hold_days": spec.minimum_hold_days,
            "ml_enabled": bool(spec.config_overrides.get("ml_enabled", False)),
            "enabled_by_default": spec.enabled_by_default,
            "description": spec.description,
        }
        for spec in _REGISTRY.values()
    ]).set_index("strategy_id")
