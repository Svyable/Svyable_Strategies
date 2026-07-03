"""Causal chimera blends of registered strategy portfolios.

A chimera is a first-class candidate. Component allocations are computed through
time using only information available before each allocation date, so historical
blend P&L is not contaminated by today's weights. Portfolio-level netting is
preserved by rebuilding the blended weights and transaction costs directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig, nasdaq_lo_config
from svyable.panel import EPS, Panel
from svyable.pipeline import RunResult
from svyable.risk import backtest_pnl
from svyable.strategy_registry import get_strategy

BLEND_PREFIX = "chimera_"
ANN = 252.0


@dataclass(frozen=True)
class BlendSpec:
    blend_id: str
    display_name: str
    description: str
    components: tuple[tuple[str, float], ...]
    method: str = "fixed"  # fixed | inverse_vol | alpha_risk
    rebalance_interval_days: int = 1
    minimum_hold_days: int = 3
    maturity: str = "production_candidate"
    enabled_by_default: bool = True
    allocation_window: int = 126
    allocation_min_history: int = 42
    allocation_smooth_alpha: float = 0.25
    component_min_weight: float = 0.05
    component_max_weight: float = 0.60
    alpha_tilt: float = 0.35

    @property
    def strategy_id(self) -> str:
        return self.blend_id

    @property
    def family(self) -> str:
        return "chimera blend"

    @property
    def factor_names(self) -> tuple[str, ...]:
        names: set[str] = set()
        for strategy_id, _ in self.components:
            names.update(get_strategy(strategy_id).factor_names)
        return tuple(sorted(names))

    def component_ids(self) -> tuple[str, ...]:
        return tuple(strategy_id for strategy_id, _ in self.components)

    def fixed_weights(self) -> pd.Series:
        raw = pd.Series(
            {strategy_id: weight for strategy_id, weight in self.components},
            dtype=float,
        )
        return raw / raw.sum()

    def build_config(self, base: SvyableConfig | None = None) -> SvyableConfig:
        from dataclasses import replace

        cfg = base or nasdaq_lo_config()
        weights = self.fixed_weights()
        component_cfgs = {
            strategy_id: get_strategy(strategy_id).build_config()
            for strategy_id, _ in self.components
        }

        def blended(attribute: str) -> float:
            return float(
                sum(
                    weights[strategy_id]
                    * getattr(component_cfgs[strategy_id], attribute)
                    for strategy_id in weights.index
                )
            )

        return replace(
            cfg,
            strategy_id=f"candidate_{self.blend_id}",
            ml_enabled=False,
            tc_bps=blended("tc_bps"),
            no_trade_band=blended("no_trade_band"),
            target_vol=blended("target_vol"),
        )

    def validate(self) -> None:
        if not self.blend_id.startswith(BLEND_PREFIX):
            raise ValueError(
                f"Blend id {self.blend_id!r} must start with {BLEND_PREFIX!r}"
            )
        if not 2 <= len(self.components) <= 4:
            raise ValueError(
                f"Blend {self.blend_id} needs 2-4 components, has {len(self.components)}"
            )
        seen: set[str] = set()
        for strategy_id, weight in self.components:
            if strategy_id in seen:
                raise ValueError(
                    f"Blend {self.blend_id} repeats component {strategy_id}"
                )
            seen.add(strategy_id)
            get_strategy(strategy_id)
            if weight <= 0:
                raise ValueError(
                    f"Blend {self.blend_id} component {strategy_id} weight must be > 0"
                )
        if self.method not in {"fixed", "inverse_vol", "alpha_risk"}:
            raise ValueError(f"Unknown blend method {self.method!r}")
        if self.method == "fixed":
            total = sum(weight for _, weight in self.components)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"Blend {self.blend_id} fixed weights sum to {total:.4f}, not 1"
                )
        if self.rebalance_interval_days < 1 or self.minimum_hold_days < 0:
            raise ValueError(f"Invalid cadence for blend {self.blend_id}")
        if self.allocation_window < 21 or self.allocation_min_history < 10:
            raise ValueError(f"Invalid allocation history for blend {self.blend_id}")
        if not 0 < self.allocation_smooth_alpha <= 1:
            raise ValueError("allocation_smooth_alpha must be in (0, 1]")
        count = len(self.components)
        if self.component_min_weight * count > 1.0 + 1e-9:
            raise ValueError("component minimum weights are infeasible")
        if self.component_max_weight * count < 1.0 - 1e-9:
            raise ValueError("component maximum weights are infeasible")
        if not 0 <= self.component_min_weight < self.component_max_weight <= 1:
            raise ValueError("invalid component weight bounds")


_REGISTRY: dict[str, BlendSpec] = {}


def register_blend(spec: BlendSpec) -> BlendSpec:
    if spec.blend_id in _REGISTRY:
        raise ValueError(f"Duplicate blend id: {spec.blend_id}")
    spec.validate()
    _REGISTRY[spec.blend_id] = spec
    return spec


register_blend(BlendSpec(
    blend_id="chimera_flagship_shield",
    display_name="Chimera Flagship + Shield",
    description=(
        "Concentrated flagship conviction with defensive ballast to blunt "
        "drawdowns without abandoning the primary alpha mandate."
    ),
    components=(("q23_concentrated", 0.70), ("q23_defensive_alpha", 0.30)),
    minimum_hold_days=5,
))

register_blend(BlendSpec(
    blend_id="chimera_trend_reversion",
    display_name="Chimera Trend x Reversion",
    description=(
        "Horizon diversification between trend continuation and short-horizon "
        "OU reversal, with portfolio-level trade netting."
    ),
    components=(("q23_momentum_quality", 0.50), ("q23_ou_mean_reversion", 0.50)),
    minimum_hold_days=3,
))

register_blend(BlendSpec(
    blend_id="chimera_all_weather",
    display_name="Chimera All-Weather",
    description=(
        "Slow robust core combining hybrid alpha, defensive alpha, and the "
        "low-turnover implementation book."
    ),
    components=(
        ("q23_hybrid_alpha", 0.40),
        ("q23_defensive_alpha", 0.30),
        ("q23_low_turnover", 0.30),
    ),
    minimum_hold_days=5,
))

register_blend(BlendSpec(
    blend_id="chimera_adaptive",
    display_name="Chimera Adaptive Risk Parity",
    description=(
        "Causal inverse-volatility allocation across flagship, trend, reversal, "
        "and defensive books with bounded and smoothed component weights."
    ),
    components=(
        ("q23_concentrated", 0.25),
        ("q23_momentum_quality", 0.25),
        ("q23_ou_mean_reversion", 0.25),
        ("q23_defensive_alpha", 0.25),
    ),
    method="inverse_vol",
    minimum_hold_days=3,
    component_min_weight=0.10,
    component_max_weight=0.50,
))

register_blend(BlendSpec(
    blend_id="chimera_institutional_alpha",
    display_name="Chimera Institutional Alpha",
    description=(
        "Causal alpha/risk allocation across beta capture, crash-resilient "
        "momentum, residual alpha, and defensive alpha."
    ),
    components=(
        ("q23_alpha_beta", 0.25),
        ("q23_crash_resilient_momentum", 0.25),
        ("q23_residual_alpha", 0.25),
        ("q23_defensive_alpha", 0.25),
    ),
    method="alpha_risk",
    minimum_hold_days=4,
    allocation_window=126,
    component_min_weight=0.08,
    component_max_weight=0.50,
    alpha_tilt=0.40,
))

register_blend(BlendSpec(
    blend_id="chimera_opportunity_stack",
    display_name="Chimera Opportunity Stack",
    description=(
        "Dynamic blend of concentrated conviction, dispersion alpha, OU "
        "reversal, and low-turnover capacity using risk-adjusted recent evidence."
    ),
    components=(
        ("q23_concentrated", 0.25),
        ("q23_dispersion_alpha", 0.25),
        ("q23_ou_mean_reversion", 0.25),
        ("q23_low_turnover", 0.25),
    ),
    method="alpha_risk",
    minimum_hold_days=3,
    component_min_weight=0.08,
    component_max_weight=0.50,
    alpha_tilt=0.30,
))


def get_blend(blend_id: str) -> BlendSpec:
    try:
        return _REGISTRY[blend_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown blend {blend_id!r}; available: {', '.join(_REGISTRY)}"
        ) from exc


def list_blends() -> list[BlendSpec]:
    return list(_REGISTRY.values())


def default_blend_ids() -> list[str]:
    return [
        spec.blend_id
        for spec in _REGISTRY.values()
        if spec.enabled_by_default
    ]


def blend_spec_from_dict(payload: Mapping[str, Any]) -> BlendSpec:
    components = payload.get("components", {})
    if isinstance(components, Mapping):
        component_items = tuple(
            (str(strategy_id), float(weight))
            for strategy_id, weight in sorted(components.items())
        )
    else:
        component_items = tuple(
            (str(strategy_id), float(weight))
            for strategy_id, weight in components
        )
    spec = BlendSpec(
        blend_id=str(payload["blend_id"]),
        display_name=str(payload.get("display_name", payload["blend_id"])),
        description=str(payload.get("description", "User-defined chimera blend.")),
        components=component_items,
        method=str(payload.get("method", "fixed")),
        rebalance_interval_days=int(payload.get("rebalance_interval_days", 1)),
        minimum_hold_days=int(payload.get("minimum_hold_days", 3)),
        maturity="user_defined",
        allocation_window=int(payload.get("allocation_window", 126)),
        allocation_min_history=int(payload.get("allocation_min_history", 42)),
        allocation_smooth_alpha=float(payload.get("allocation_smooth_alpha", 0.25)),
        component_min_weight=float(payload.get("component_min_weight", 0.05)),
        component_max_weight=float(payload.get("component_max_weight", 0.60)),
        alpha_tilt=float(payload.get("alpha_tilt", 0.35)),
    )
    spec.validate()
    return spec


def blend_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "blend_id": spec.blend_id,
                "name": spec.display_name,
                "method": spec.method,
                "components": json.dumps(dict(spec.components)),
                "allocation_window": spec.allocation_window,
                "component_bounds": (
                    f"{spec.component_min_weight:.0%}-{spec.component_max_weight:.0%}"
                ),
                "minimum_hold_days": spec.minimum_hold_days,
                "rebalance_interval_days": spec.rebalance_interval_days,
                "enabled_by_default": spec.enabled_by_default,
                "description": spec.description,
            }
            for spec in _REGISTRY.values()
        ]
    ).set_index("blend_id")


def _project_component_weights(
    raw: pd.Series,
    spec: BlendSpec,
) -> pd.Series:
    """Project positive scores onto a bounded simplex."""
    index = raw.index
    values = raw.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    if values.sum() <= EPS:
        values = spec.fixed_weights().reindex(index).fillna(0.0)
    else:
        values = values / values.sum()

    lower = spec.component_min_weight
    upper = spec.component_max_weight
    weights = values.copy()
    for _ in range(4 * len(weights)):
        weights = weights.clip(lower, upper)
        residual = 1.0 - float(weights.sum())
        if abs(residual) < 1e-12:
            break
        if residual > 0:
            free = weights < upper - 1e-12
            capacity = (upper - weights.where(free, upper)).clip(lower=0.0)
        else:
            free = weights > lower + 1e-12
            capacity = (weights.where(free, lower) - lower).clip(lower=0.0)
        if not free.any() or capacity.sum() <= EPS:
            break
        weights.loc[free] += residual * capacity.loc[free] / capacity.loc[free].sum()
    weights = weights.clip(lower, upper)
    return weights / weights.sum()


def _component_returns(
    spec: BlendSpec,
    results: Mapping[str, RunResult],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            strategy_id: results[strategy_id].pnl["net_ret"]
            for strategy_id, _ in spec.components
        }
    ).sort_index()


def resolve_component_weight_history(
    spec: BlendSpec,
    results: Mapping[str, RunResult],
) -> pd.DataFrame:
    """Causal component allocations for every historical date."""
    returns = _component_returns(spec, results)
    component_ids = list(spec.component_ids())
    fixed = spec.fixed_weights().reindex(component_ids)
    history = pd.DataFrame(index=returns.index, columns=component_ids, dtype=float)
    previous = fixed.copy()

    if spec.method == "fixed":
        history.loc[:, :] = fixed.to_numpy()
        return history

    shifted = returns.shift(1)
    rolling_vol = shifted.rolling(
        spec.allocation_window,
        min_periods=spec.allocation_min_history,
    ).std() * np.sqrt(ANN)
    ewma_mean = shifted.ewm(
        halflife=max(10, spec.allocation_window // 3),
        min_periods=spec.allocation_min_history,
        adjust=False,
    ).mean() * ANN

    for position, timestamp in enumerate(returns.index):
        volatility = rolling_vol.loc[timestamp]
        if volatility.notna().sum() < len(component_ids):
            target = fixed.copy()
        else:
            inverse_vol = 1.0 / (volatility + EPS)
            raw = inverse_vol.copy()
            if spec.method == "alpha_risk":
                annual_alpha = ewma_mean.loc[timestamp]
                sharpe = (annual_alpha / (volatility + EPS)).clip(-2.5, 2.5)
                start = max(0, position - spec.allocation_window)
                sample = shifted.iloc[start:position].dropna(how="all")
                if len(sample) >= spec.allocation_min_history:
                    correlation = sample.corr().abs()
                    average_correlation = (
                        correlation.sum(axis=1) - 1.0
                    ) / max(1, len(component_ids) - 1)
                    diversification = 1.0 / np.sqrt(0.50 + average_correlation.clip(0.0, 1.0))
                else:
                    diversification = pd.Series(1.0, index=component_ids)
                alpha_multiplier = np.exp(spec.alpha_tilt * sharpe)
                raw = inverse_vol * alpha_multiplier * diversification
            target = _project_component_weights(raw, spec)

        smoothed = (
            spec.allocation_smooth_alpha * target
            + (1.0 - spec.allocation_smooth_alpha) * previous
        )
        previous = _project_component_weights(smoothed, spec)
        history.loc[timestamp] = previous

    return history.ffill().fillna(fixed)


def resolve_component_weights(
    spec: BlendSpec,
    results: Mapping[str, RunResult],
) -> pd.Series:
    """Current allocation retained for board/UI compatibility."""
    return resolve_component_weight_history(spec, results).iloc[-1]


class BlendRunResult:
    def __init__(
        self,
        *,
        weights: pd.DataFrame,
        pnl: pd.DataFrame,
        score: pd.DataFrame,
        kill_switch: pd.Series,
        component_weights: pd.Series,
        component_weight_history: pd.DataFrame,
        component_dirs: dict[str, str],
        tag: str,
        output_dir: Path | None = None,
    ) -> None:
        self.weights = weights
        self.pnl = pnl
        self.ensemble = SimpleNamespace(score=score)
        self.risk = SimpleNamespace(kill_switch=kill_switch)
        self.component_weights = component_weights
        self.component_weight_history = component_weight_history
        self.component_dirs = component_dirs
        self.tag = tag
        self.output_dir = output_dir


def _blend_frames_dynamic(
    frames: Mapping[str, pd.DataFrame],
    component_history: pd.DataFrame,
) -> pd.DataFrame:
    total: pd.DataFrame | None = None
    denominator: pd.DataFrame | None = None
    for strategy_id in component_history.columns:
        allocation = component_history[strategy_id]
        frame = frames[strategy_id]
        present = frame.notna()
        contribution = frame.where(present, 0.0).mul(allocation, axis=0)
        indicator = present.astype(float).mul(allocation, axis=0)
        total = contribution if total is None else total.add(contribution, fill_value=0.0)
        denominator = indicator if denominator is None else denominator.add(indicator, fill_value=0.0)
    assert total is not None and denominator is not None
    return total.div(denominator.replace(0.0, np.nan))


def build_blend_result(
    spec: BlendSpec,
    component_weights: pd.Series | pd.DataFrame,
    results: Mapping[str, RunResult],
    panel: Panel,
    *,
    tag: str,
) -> BlendRunResult:
    cfg = spec.build_config()
    if isinstance(component_weights, pd.Series):
        history = pd.DataFrame(
            np.broadcast_to(component_weights.to_numpy(), (len(panel.close.index), len(component_weights))),
            index=panel.close.index,
            columns=component_weights.index,
        )
    else:
        history = component_weights.reindex(panel.close.index).ffill()
    history = history.reindex(columns=list(spec.component_ids()))

    blended_weights: pd.DataFrame | None = None
    for strategy_id in history.columns:
        frame = results[strategy_id].weights.fillna(0.0).mul(
            history[strategy_id], axis=0
        )
        blended_weights = frame if blended_weights is None else blended_weights.add(frame, fill_value=0.0)
    assert blended_weights is not None
    blended_weights = blended_weights.fillna(0.0)

    pnl = backtest_pnl(blended_weights, panel.ret, cfg)
    score = _blend_frames_dynamic(
        {
            strategy_id: results[strategy_id].ensemble.score
            for strategy_id in history.columns
        },
        history,
    )

    kill = pd.Series(0.0, index=blended_weights.index)
    for strategy_id in history.columns:
        component_kill = results[strategy_id].risk.kill_switch.fillna(0.0)
        active = history[strategy_id] > 1e-6
        kill = np.maximum(kill, component_kill.where(active, 0.0))

    return BlendRunResult(
        weights=blended_weights,
        pnl=pnl,
        score=score,
        kill_switch=pd.Series(kill, index=blended_weights.index),
        component_weights=history.iloc[-1],
        component_weight_history=history,
        component_dirs={
            strategy_id: str(results[strategy_id].output_dir or "")
            for strategy_id in history.columns
        },
        tag=tag,
    )


def write_blend_artifacts(
    spec: BlendSpec,
    result: BlendRunResult,
    panel: Panel,
    output_root: str | Path,
    *,
    tag: str,
) -> Path:
    cfg = spec.build_config()
    directory = Path(output_root) / f"candidate_{spec.blend_id}" / tag
    directory.mkdir(parents=True, exist_ok=True)

    last = result.weights.index[-1]
    weights_today = result.weights.loc[last]
    weights_today[weights_today > 1e-12].rename("weight").to_csv(
        directory / "weights_today.csv"
    )
    result.weights.iloc[-63:].to_csv(directory / "weights_history.csv")
    result.pnl.iloc[-252:].to_csv(directory / "pnl_diag.csv")
    result.component_weight_history.iloc[-252:].to_csv(
        directory / "component_weights_history.csv"
    )

    prices = panel.close.loc[last].dropna().rename("price")
    adv = panel.adv(cfg.adv_win).loc[last].dropna().rename("adv_dollars")
    liquid = (
        panel.liquidity_mask(cfg.min_adv, cfg.min_price, cfg.adv_win)
        .loc[last]
        .fillna(False)
        .astype(bool)
        .rename("is_liquid")
    )
    pd.concat([prices, adv, liquid], axis=1).sort_index().to_csv(
        directory / "execution_inputs.csv"
    )

    composition = {
        strategy_id: round(float(weight), 6)
        for strategy_id, weight in result.component_weights.items()
    }
    (directory / "meta.json").write_text(
        json.dumps(
            {
                "strategy_id": f"candidate_{spec.blend_id}",
                "blend_id": spec.blend_id,
                "kind": "chimera_blend",
                "method": spec.method,
                "components": composition,
                "component_output_dirs": result.component_dirs,
                "allocation": {
                    "window": spec.allocation_window,
                    "minimum_history": spec.allocation_min_history,
                    "smooth_alpha": spec.allocation_smooth_alpha,
                    "minimum_weight": spec.component_min_weight,
                    "maximum_weight": spec.component_max_weight,
                    "alpha_tilt": spec.alpha_tilt,
                    "causal_history": True,
                },
                "tag": tag,
                "run_timestamp": datetime.now().isoformat(),
                "config_hash": cfg.config_hash(),
                "config": cfg.to_dict(),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )

    lines = [
        f"# Chimera blend — {spec.display_name}",
        "",
        spec.description,
        "",
        "| Component | Current weight |",
        "|---|---:|",
    ]
    lines += [
        f"| {strategy_id} | {weight:.1%} |"
        for strategy_id, weight in composition.items()
    ]
    lines += [
        "",
        f"- Method: {spec.method}",
        "- Historical allocation: causal and lagged",
        f"- Positions: {int((weights_today > 1e-12).sum())}",
        f"- Gross: {float(weights_today.clip(lower=0).sum()):.1%}",
        f"- As of: {last.date() if hasattr(last, 'date') else last}",
    ]
    (directory / "morning_report.md").write_text("\n".join(lines) + "\n")

    result.output_dir = directory
    return directory
