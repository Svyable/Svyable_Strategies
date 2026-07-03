"""Chimera blends: convex combinations of registered strategy portfolios.

A blend is a first-class candidate on the daily board, never a side channel.
Deterministic code turns component RunResults into one blended portfolio with
real artifacts, so selection, eligibility gates, two-phase agent approval, and
activation treat a chimera exactly like a single registered strategy. Neither
the GUI nor the agent ever authors weights: component weights are either fixed
in the registered/persisted blend definition or derived by a deterministic
rule (inverse volatility) from the day's candidate results.

Blending happens at the *portfolio* level. The blended book inherits the real
trade netting between components (a buy in one component cancels a sell in
another), which is measured honestly by re-running the cost model on the
blended weights history rather than averaging component diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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

INVERSE_VOL_WIN = 63
INVERSE_VOL_MIN_WEIGHT = 0.10
INVERSE_VOL_MAX_WEIGHT = 0.50


@dataclass(frozen=True)
class BlendSpec:
    """A complete blended recipe, duck-compatible with StrategySpec where the
    candidate board builder needs it (strategy_id, display fields, cadence,
    build_config)."""

    blend_id: str
    display_name: str
    description: str
    components: tuple[tuple[str, float], ...]   # (strategy_id, weight)
    method: str = "fixed"                        # "fixed" | "inverse_vol"
    rebalance_interval_days: int = 1
    minimum_hold_days: int = 3
    maturity: str = "production_candidate"
    enabled_by_default: bool = True

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

    def build_config(self, base: SvyableConfig | None = None) -> SvyableConfig:
        """Representative execution config: exposure-weighted cost and band
        assumptions across components. Used for cost estimation and artifact
        provenance only — components were built with their own configs."""
        from dataclasses import replace

        cfg = base or nasdaq_lo_config()
        weights = self.fixed_weights()
        component_cfgs = {
            strategy_id: get_strategy(strategy_id).build_config()
            for strategy_id, _ in self.components
        }

        def blended(attr: str) -> float:
            return float(sum(
                weights[strategy_id] * getattr(component_cfgs[strategy_id], attr)
                for strategy_id in weights.index
            ))

        return replace(
            cfg,
            strategy_id=f"candidate_{self.blend_id}",
            ml_enabled=False,
            tc_bps=blended("tc_bps"),
            no_trade_band=blended("no_trade_band"),
            target_vol=blended("target_vol"),
        )

    def fixed_weights(self) -> pd.Series:
        """Definition-time component weights (equal split for dynamic methods
        until results exist)."""
        raw = pd.Series(
            {strategy_id: weight for strategy_id, weight in self.components},
            dtype=float,
        )
        return raw / raw.sum()

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
            get_strategy(strategy_id)   # raises for unknown ids
            if weight <= 0:
                raise ValueError(
                    f"Blend {self.blend_id} component {strategy_id} weight must be > 0"
                )
        if self.method not in {"fixed", "inverse_vol"}:
            raise ValueError(f"Unknown blend method {self.method!r}")
        if self.method == "fixed":
            total = sum(weight for _, weight in self.components)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"Blend {self.blend_id} fixed weights sum to {total:.4f}, not 1"
                )
        if self.rebalance_interval_days < 1 or self.minimum_hold_days < 0:
            raise ValueError(f"Invalid cadence for blend {self.blend_id}")


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
        "The concentrated contest-identity book with a defensive ballast: "
        "70% q23_concentrated conviction, 30% q23_defensive_alpha to blunt "
        "drawdowns without abandoning the flagship mandate."
    ),
    components=(("q23_concentrated", 0.70), ("q23_defensive_alpha", 0.30)),
    minimum_hold_days=5,
))

register_blend(BlendSpec(
    blend_id="chimera_trend_reversion",
    display_name="Chimera Trend x Reversion",
    description=(
        "Horizon diversification: half trend continuation, half short-horizon "
        "OU reversal. The sleeves profit from opposite market microstructures, "
        "and portfolio-level netting cancels much of their opposing trading."
    ),
    components=(("q23_momentum_quality", 0.50), ("q23_ou_mean_reversion", 0.50)),
    minimum_hold_days=3,
))

register_blend(BlendSpec(
    blend_id="chimera_all_weather",
    display_name="Chimera All-Weather",
    description=(
        "Slow, robust core for stressed or low-conviction tape: balanced "
        "hybrid ensemble, defensive alpha, and low-turnover holdings."
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
        "Inverse-volatility weights across the flagship, trend, reversal, and "
        "defensive books, recomputed deterministically from each morning's "
        "candidate results (63d realized vol, clamped 10-50% per component)."
    ),
    components=(
        ("q23_concentrated", 0.25),
        ("q23_momentum_quality", 0.25),
        ("q23_ou_mean_reversion", 0.25),
        ("q23_defensive_alpha", 0.25),
    ),
    method="inverse_vol",
    minimum_hold_days=3,
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
    return [spec.blend_id for spec in _REGISTRY.values() if spec.enabled_by_default]


def blend_spec_from_dict(payload: Mapping[str, Any]) -> BlendSpec:
    """Build a custom (policy-persisted) blend definition; validates fully."""
    components = payload.get("components", {})
    if isinstance(components, Mapping):
        component_items = tuple(
            (str(strategy_id), float(weight))
            for strategy_id, weight in sorted(components.items())
        )
    else:
        component_items = tuple(
            (str(strategy_id), float(weight)) for strategy_id, weight in components
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
    )
    spec.validate()
    return spec


def blend_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "blend_id": spec.blend_id,
            "name": spec.display_name,
            "method": spec.method,
            "components": json.dumps(dict(spec.components)),
            "minimum_hold_days": spec.minimum_hold_days,
            "rebalance_interval_days": spec.rebalance_interval_days,
            "enabled_by_default": spec.enabled_by_default,
            "description": spec.description,
        }
        for spec in _REGISTRY.values()
    ]).set_index("blend_id")


def resolve_component_weights(
    spec: BlendSpec,
    results: Mapping[str, RunResult],
) -> pd.Series:
    """Deterministic component weights for today's board."""
    if spec.method == "fixed":
        return spec.fixed_weights()

    vols = {}
    for strategy_id, _ in spec.components:
        net = results[strategy_id].pnl["net_ret"].dropna().tail(INVERSE_VOL_WIN)
        vols[strategy_id] = float(net.std() * np.sqrt(252.0)) if len(net) >= 21 else np.nan
    inverse = pd.Series(
        {
            strategy_id: 1.0 / (vol + EPS) if np.isfinite(vol) else np.nan
            for strategy_id, vol in vols.items()
        },
        dtype=float,
    )
    if inverse.isna().any():
        return spec.fixed_weights()
    weights = inverse / inverse.sum()
    # enforce the clamps exactly: pin violators at their bound and push the
    # remainder proportionally into the free components (plain clip-then-
    # renormalize re-breaks the caps). Feasible for 2-4 components by bounds.
    lo, hi = INVERSE_VOL_MIN_WEIGHT, INVERSE_VOL_MAX_WEIGHT
    for _ in range(2 * len(weights)):
        weights = weights.clip(lo, hi)
        residual = 1.0 - float(weights.sum())
        if abs(residual) < 1e-12:
            break
        free = (weights > lo + 1e-12) & (weights < hi - 1e-12)
        if not free.any():
            free = weights == weights   # all pinned: spread evenly, then re-clip
        weights = weights.where(
            ~free, weights + residual * weights[free] / weights[free].sum()
        )
    return weights / weights.sum()


class BlendRunResult:
    """Duck-typed RunResult for a blended portfolio: enough surface for the
    candidate board (weights, pnl, ensemble.score, risk.kill_switch,
    output_dir) built from real component results."""

    def __init__(
        self,
        *,
        weights: pd.DataFrame,
        pnl: pd.DataFrame,
        score: pd.DataFrame,
        kill_switch: pd.Series,
        component_weights: pd.Series,
        component_dirs: dict[str, str],
        tag: str,
        output_dir: Path | None = None,
    ) -> None:
        self.weights = weights
        self.pnl = pnl
        self.ensemble = SimpleNamespace(score=score)
        self.risk = SimpleNamespace(kill_switch=kill_switch)
        self.component_weights = component_weights
        self.component_dirs = component_dirs
        self.tag = tag
        self.output_dir = output_dir


def _blend_frames(
    frames: Mapping[str, pd.DataFrame],
    component_weights: pd.Series,
) -> pd.DataFrame:
    """NaN-aware weighted average across component frames (aligned on the
    union of columns; all components share the panel's date index)."""
    total: pd.DataFrame | None = None
    denominator: pd.DataFrame | None = None
    for strategy_id, weight in component_weights.items():
        frame = frames[strategy_id]
        present = frame.notna()
        contribution = frame.where(present, 0.0) * float(weight)
        indicator = present.astype(float) * float(weight)
        total = contribution if total is None else total.add(contribution, fill_value=0.0)
        denominator = (
            indicator if denominator is None
            else denominator.add(indicator, fill_value=0.0)
        )
    assert total is not None and denominator is not None
    return total.div(denominator.replace(0.0, np.nan))


def build_blend_result(
    spec: BlendSpec,
    component_weights: pd.Series,
    results: Mapping[str, RunResult],
    panel: Panel,
    *,
    tag: str,
) -> BlendRunResult:
    cfg = spec.build_config()

    blended_weights: pd.DataFrame | None = None
    for strategy_id, weight in component_weights.items():
        frame = results[strategy_id].weights.fillna(0.0) * float(weight)
        blended_weights = (
            frame if blended_weights is None
            else blended_weights.add(frame, fill_value=0.0)
        )
    assert blended_weights is not None
    blended_weights = blended_weights.fillna(0.0)

    # honest costs: re-run the cost model on the blended history so component
    # trade netting is captured instead of averaging component diagnostics
    pnl = backtest_pnl(blended_weights, panel.ret, cfg)

    score = _blend_frames(
        {
            strategy_id: results[strategy_id].ensemble.score
            for strategy_id in component_weights.index
        },
        component_weights,
    )

    kill = None
    for strategy_id in component_weights.index:
        component_kill = results[strategy_id].risk.kill_switch.fillna(0.0)
        kill = component_kill if kill is None else np.maximum(kill, component_kill)
    assert kill is not None

    return BlendRunResult(
        weights=blended_weights,
        pnl=pnl,
        score=score,
        kill_switch=pd.Series(kill, index=blended_weights.index),
        component_weights=component_weights,
        component_dirs={
            strategy_id: str(results[strategy_id].output_dir or "")
            for strategy_id in component_weights.index
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
    """Write the same artifact contract candidates produce, so activation and
    the execution stack treat a chimera identically to a single strategy."""
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
    (directory / "meta.json").write_text(json.dumps(
        {
            "strategy_id": f"candidate_{spec.blend_id}",
            "blend_id": spec.blend_id,
            "kind": "chimera_blend",
            "method": spec.method,
            "components": composition,
            "component_output_dirs": result.component_dirs,
            "tag": tag,
            "run_timestamp": datetime.now().isoformat(),
            "config_hash": cfg.config_hash(),
            "config": cfg.to_dict(),
        },
        indent=2,
        sort_keys=True,
        default=str,
    ))

    lines = [
        f"# Chimera blend — {spec.display_name}",
        "",
        spec.description,
        "",
        "| Component | Weight |",
        "|---|---:|",
    ]
    lines += [
        f"| {strategy_id} | {weight:.1%} |"
        for strategy_id, weight in composition.items()
    ]
    lines += [
        "",
        f"- Method: {spec.method}",
        f"- Positions: {int((weights_today > 1e-12).sum())}",
        f"- Gross: {float(weights_today.clip(lower=0).sum()):.1%}",
        f"- As of: {last.date() if hasattr(last, 'date') else last}",
    ]
    (directory / "morning_report.md").write_text("\n".join(lines) + "\n")

    result.output_dir = directory
    return directory
