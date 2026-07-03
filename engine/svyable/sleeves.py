"""Sleeve ensemble with robust IC state, maturity floors, and stress priors."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from svyable.panel import EPS, Panel, forward_returns
from svyable.config import SvyableConfig
from svyable import factor_library as flib
from svyable.factor_correlation import pairwise_corr_penalty
from svyable.weighting import (
    composite_score,
    ic_coverage,
    ic_matrix,
    ic_state,
    ic_weights,
    latest_ic_diagnostics,
    rank_ic,
    stack_factors,
)


@dataclass
class SleeveResult:
    score: pd.DataFrame
    sleeve_scores: dict[str, pd.DataFrame]
    sleeve_weights: pd.DataFrame
    factor_weights: dict[str, pd.DataFrame]
    factor_health: dict[str, pd.DataFrame]
    sleeve_health: pd.DataFrame
    ic_health: pd.DataFrame
    stress: pd.Series


def market_drawdown(mkt_ret: pd.Series, win: int) -> pd.Series:
    growth = (1.0 + mkt_ret.fillna(0.0)).cumprod()
    peak = growth.rolling(win, min_periods=1).max()
    return ((peak - growth) / (peak + EPS)).clip(0.0, 1.0)


def _sleeve_score(
    factors: dict[str, pd.DataFrame],
    panel: Panel,
    cfg: SvyableConfig,
    members: list[str],
    horizons: tuple[int, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sub = {name: factors[name] for name in members if name in factors}
    if not sub:
        index, columns = panel.close.index, panel.close.columns
        return (
            pd.DataFrame(0.0, index=index, columns=columns),
            pd.DataFrame(index=index),
            pd.DataFrame(),
        )

    eligible = panel.liquidity_mask(
        cfg.min_adv, cfg.min_price, cfg.adv_win
    ).astype(bool)
    array, names = stack_factors(sub)
    penalty = pairwise_corr_penalty(
        array,
        names,
        panel.close.index,
        cfg.factor_corr_penalty,
        cfg.factor_min_diversification,
        min_obs=cfg.ic_min_cross_section,
    )
    floors = flib.factor_floors(names, cfg.factor_min_weight)

    scores: list[pd.DataFrame] = []
    factor_weights: list[pd.DataFrame] = []
    diagnostics: list[pd.DataFrame] = []
    catalog = flib.factor_metadata(names)[["stage", "lineage", "description"]]

    for horizon in horizons:
        fwd = forward_returns(panel.close, horizon)
        raw_ic = ic_matrix(
            sub,
            fwd,
            eligible=eligible,
            min_obs=cfg.ic_min_cross_section,
        )
        coverage = ic_coverage(sub, fwd, eligible=eligible)
        weights = ic_weights(
            raw_ic,
            horizon=horizon,
            lam=cfg.ic_lambda,
            clip=cfg.ic_clip,
            min_weight=floors,
            penalty=penalty,
            recency_boost=cfg.recency_boost,
            recency_win=cfg.recency_win,
            coverage=coverage,
            min_coverage=cfg.ic_min_coverage,
            vol_floor=cfg.ic_vol_floor,
            ir_clip=cfg.ic_ir_clip,
            min_history=cfg.ic_min_history,
            hit_rate_win=cfg.ic_hit_rate_win,
        )
        scores.append(composite_score(sub, weights))
        factor_weights.append(weights)

        health = latest_ic_diagnostics(
            raw_ic,
            weights,
            horizon=horizon,
            lam=cfg.ic_lambda,
            clip=cfg.ic_clip,
            coverage=coverage,
            vol_floor=cfg.ic_vol_floor,
            min_history=cfg.ic_min_history,
            hit_rate_win=cfg.ic_hit_rate_win,
        ).join(catalog, how="left")
        health["horizon"] = horizon
        diagnostics.append(health.reset_index())

    score = sum(scores) / len(scores)
    weights = sum(factor_weights) / len(factor_weights)
    health = pd.concat(diagnostics, ignore_index=True).set_index(["factor", "horizon"])
    return score, weights, health


def _sleeve_coverage(
    scores: dict[str, pd.DataFrame],
    fwd: pd.DataFrame,
    eligible: pd.DataFrame,
) -> pd.DataFrame:
    denominator = eligible.sum(axis=1).replace(0, np.nan)
    return pd.DataFrame(
        {
            name: (frame.notna() & fwd.notna() & eligible).sum(axis=1) / denominator
            for name, frame in scores.items()
        }
    )


def build_ensemble(
    panel: Panel,
    cfg: SvyableConfig,
    extra_sleeve_scores: dict[str, pd.DataFrame] | None = None,
    factors: dict[str, pd.DataFrame] | None = None,
) -> SleeveResult:
    """Compute factor sleeves and combine them through the same robust IC state."""
    library = flib.compute_all(panel, cfg) if factors is None else factors
    extra = extra_sleeve_scores or {}

    sleeve_scores: dict[str, pd.DataFrame] = {}
    factor_weights: dict[str, pd.DataFrame] = {}
    factor_health: dict[str, pd.DataFrame] = {}

    for spec in cfg.sleeves:
        if spec.name in extra:
            sleeve_scores[spec.name] = extra[spec.name]
            continue
        members = flib.sleeve_members(spec.name)
        if not members:
            continue
        score, weights, health = _sleeve_score(
            library, panel, cfg, members, spec.horizons
        )
        sleeve_scores[spec.name] = score
        factor_weights[spec.name] = weights
        factor_health[spec.name] = health

    names = list(sleeve_scores)
    horizon = cfg.sleeve_horizon_for_weighting
    fwd = forward_returns(panel.close, horizon)
    eligible = panel.liquidity_mask(
        cfg.min_adv, cfg.min_price, cfg.adv_win
    ).astype(bool)

    raw_ic = pd.DataFrame(
        {
            name: rank_ic(
                sleeve_scores[name],
                fwd,
                eligible=eligible,
                min_obs=cfg.ic_min_cross_section,
            )
            for name in names
        }
    )
    coverage = _sleeve_coverage(sleeve_scores, fwd, eligible)
    state = ic_state(
        raw_ic,
        horizon=horizon,
        lam=cfg.sleeve_ic_lambda,
        clip=cfg.ic_clip,
        vol_floor=cfg.ic_vol_floor,
        min_history=cfg.ic_min_history,
        hit_rate_win=cfg.ic_hit_rate_win,
        coverage=coverage,
    )
    ic_health = state["mean"]

    array, _ = stack_factors(sleeve_scores)
    penalty = pairwise_corr_penalty(
        array,
        names,
        panel.close.index,
        cfg.sleeve_corr_penalty,
        0.25,
        min_obs=cfg.ic_min_cross_section,
    )
    proven = {spec.name for spec in cfg.sleeves if spec.proven}
    floors = pd.Series(
        {
            name: cfg.sleeve_min_weight if name in proven else 0.0
            for name in names
        }
    )
    weights = ic_weights(
        raw_ic,
        horizon=horizon,
        lam=cfg.sleeve_ic_lambda,
        clip=cfg.ic_clip,
        min_weight=floors,
        penalty=penalty,
        recency_boost=cfg.recency_boost,
        recency_win=cfg.recency_win,
        coverage=coverage,
        min_coverage=cfg.ic_min_coverage,
        vol_floor=cfg.ic_vol_floor,
        ir_clip=cfg.ic_ir_clip,
        min_history=cfg.ic_min_history,
        hit_rate_win=cfg.ic_hit_rate_win,
    )

    drawdown = market_drawdown(panel.market_ret, cfg.dd_win)
    stress = (drawdown / (cfg.stress_dd_cap + EPS)).clip(0.0, 1.0)
    multipliers = {spec.name: spec.stress_mult for spec in cfg.sleeves}
    stress_multiplier = pd.DataFrame(
        {
            name: 1.0 + multipliers.get(name, 0.0) * stress
            for name in names
        },
        index=panel.close.index,
    ).clip(lower=0.0)
    weights = weights * stress_multiplier
    floor_frame = pd.DataFrame(
        np.broadcast_to(floors.reindex(names).fillna(0.0).to_numpy(), weights.shape),
        index=weights.index,
        columns=weights.columns,
    )
    weights = weights.where(weights >= floor_frame, floor_frame)
    weights = weights.div(weights.sum(axis=1) + EPS, axis=0)

    sleeve_health = latest_ic_diagnostics(
        raw_ic,
        weights,
        horizon=horizon,
        lam=cfg.sleeve_ic_lambda,
        clip=cfg.ic_clip,
        coverage=coverage,
        vol_floor=cfg.ic_vol_floor,
        min_history=cfg.ic_min_history,
        hit_rate_win=cfg.ic_hit_rate_win,
    )
    sleeve_health["stress_multiplier"] = stress_multiplier.ffill().iloc[-1]
    sleeve_health.index.name = "sleeve"

    score = composite_score(sleeve_scores, weights)
    return SleeveResult(
        score=score,
        sleeve_scores=sleeve_scores,
        sleeve_weights=weights,
        factor_weights=factor_weights,
        factor_health=factor_health,
        sleeve_health=sleeve_health,
        ic_health=ic_health,
        stress=stress,
    )
