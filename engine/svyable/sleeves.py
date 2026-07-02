"""Sleeve ensemble with stress prior (strategy.md §5).

Each sleeve: correlation-penalized IC weights over its own factors at its own
horizons, averaged. Across sleeves: rank-IC weighting x sleeve correlation
penalty x drawdown stress multiplier, min-weight floored.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from svyable.panel import EPS, Panel, forward_returns
from svyable.config import SvyableConfig
from svyable import factors as flib
from svyable.weighting import (
    composite_score, factor_corr_penalty, ic_matrix, ic_weights, rank_ic, stack_factors,
)


@dataclass
class SleeveResult:
    score: pd.DataFrame                 # composite (time x asset)
    sleeve_scores: dict[str, pd.DataFrame]
    sleeve_weights: pd.DataFrame        # (time x sleeve)
    factor_weights: dict[str, pd.DataFrame]  # sleeve -> (time x factor)
    ic_health: pd.DataFrame             # (time x sleeve) smoothed sleeve IC
    stress: pd.Series


def market_drawdown(mkt_ret: pd.Series, win: int) -> pd.Series:
    growth = (1.0 + mkt_ret.fillna(0.0)).cumprod()
    peak = growth.rolling(win, min_periods=1).max()
    return ((peak - growth) / (peak + EPS)).clip(0.0, 1.0)


def _sleeve_score(F: dict[str, pd.DataFrame], panel: Panel, cfg: SvyableConfig,
                  members: list[str], horizons: tuple[int, ...]
                  ) -> tuple[pd.DataFrame, pd.DataFrame]:
    sub = {n: F[n] for n in members if n in F}
    if not sub:
        idx, cols = panel.close.index, panel.close.columns
        return (pd.DataFrame(0.0, index=idx, columns=cols),
                pd.DataFrame(index=idx))

    A, names = stack_factors(sub)
    pen = factor_corr_penalty(A, names, panel.close.index,
                              cfg.factor_corr_penalty, cfg.factor_min_diversification)

    scores, fws = [], []
    for h in horizons:
        fwd = forward_returns(panel.close, h)
        ic = ic_matrix(sub, fwd)
        w = ic_weights(ic, horizon=h, lam=cfg.ic_lambda, clip=cfg.ic_clip,
                       min_weight=cfg.factor_min_weight, penalty=pen,
                       recency_boost=cfg.recency_boost, recency_win=cfg.recency_win)
        scores.append(composite_score(sub, w))
        fws.append(w)

    score = sum(scores) / len(scores)
    fw = sum(fws) / len(fws)
    return score, fw


def build_ensemble(panel: Panel, cfg: SvyableConfig,
                   extra_sleeve_scores: dict[str, pd.DataFrame] | None = None
                   ) -> SleeveResult:
    """Compute all sleeves and combine. `extra_sleeve_scores` lets the ML sleeve
    (or any future sleeve computed outside the factor registry) plug in."""
    F = flib.compute_all(panel, cfg)
    extra = extra_sleeve_scores or {}

    sleeve_scores: dict[str, pd.DataFrame] = {}
    factor_weights: dict[str, pd.DataFrame] = {}

    for spec in cfg.sleeves:
        if spec.name in extra:
            sleeve_scores[spec.name] = extra[spec.name]
            continue
        members = flib.sleeve_members(spec.name)
        if not members:
            continue
        score, fw = _sleeve_score(F, panel, cfg, members, spec.horizons)
        sleeve_scores[spec.name] = score
        factor_weights[spec.name] = fw

    names = list(sleeve_scores)
    h = cfg.sleeve_horizon_for_weighting
    fwd = forward_returns(panel.close, h)

    # sleeve-level IC, purged + smoothed
    ic = pd.DataFrame({n: rank_ic(sleeve_scores[n], fwd) for n in names})
    ic = ic.shift(h + 1).fillna(0.0)
    ic_smooth = ic.ewm(alpha=1.0 - cfg.sleeve_ic_lambda, adjust=False).mean()

    # sleeve correlation penalty
    A, _ = stack_factors(sleeve_scores)
    pen = factor_corr_penalty(A, names, panel.close.index,
                              cfg.sleeve_corr_penalty, 0.25)

    # stress prior
    dd = market_drawdown(panel.market_ret, cfg.dd_win)
    stress = (dd / (cfg.stress_dd_cap + EPS)).clip(0.0, 1.0)
    mults = {s.name: s.stress_mult for s in cfg.sleeves}
    stress_mult = pd.DataFrame(
        {n: 1.0 + mults.get(n, 0.0) * stress for n in names}, index=panel.close.index
    ).clip(lower=0.0)

    raw = ic_smooth.clip(lower=0.0) * pen * stress_mult
    s = raw.sum(axis=1)
    w = raw.div(s + EPS, axis=0)
    w = w.where(s > EPS, other=1.0 / max(1, len(names)))
    w = w.clip(lower=cfg.sleeve_min_weight)
    w = w.div(w.sum(axis=1) + EPS, axis=0)

    score = composite_score(sleeve_scores, w)

    return SleeveResult(
        score=score,
        sleeve_scores=sleeve_scores,
        sleeve_weights=w,
        factor_weights=factor_weights,
        ic_health=ic_smooth,
        stress=stress,
    )
