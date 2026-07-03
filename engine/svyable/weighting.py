"""Robust, causal rank-IC meta-learning utilities.

The weighting path is deliberately conservative:

- IC is computed only on pairwise-valid, tradable observations.
- Insufficient cross-sectional breadth stays missing rather than becoming zero.
- Every IC observation is purged by ``horizon + 1`` before it can affect weights.
- Expected IC is shrunk by its own uncertainty, hit rate, and signal coverage.
- Floors apply only to active factors and may differ for proven vs shadow signals.
- Correlation penalties use pairwise-valid observations rather than zero imputation.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from svyable.panel import EPS


def rank_ic(
    factor: pd.DataFrame,
    fwd: pd.DataFrame,
    *,
    eligible: pd.DataFrame | None = None,
    min_obs: int = 15,
) -> pd.Series:
    """Cross-sectional Spearman IC per day.

    Rows with fewer than ``min_obs`` pairwise-valid eligible assets remain NaN.
    Treating an unavailable IC as zero biases both the EWMA state and hit rate.
    """
    mask = factor.notna() & fwd.notna()
    if eligible is not None:
        mask &= eligible.reindex_like(factor).fillna(False).astype(bool)
    counts = mask.sum(axis=1)
    f = factor.where(mask).rank(axis=1, method="average")
    r = fwd.where(mask).rank(axis=1, method="average")
    fx = f.sub(f.mean(axis=1), axis=0)
    rx = r.sub(r.mean(axis=1), axis=0)
    num = (fx * rx).sum(axis=1, min_count=1)
    den = np.sqrt((fx ** 2).sum(axis=1) * (rx ** 2).sum(axis=1))
    result = num / den.replace(0.0, np.nan)
    return result.where(counts >= max(3, int(min_obs)))


def ic_matrix(
    factors: dict[str, pd.DataFrame],
    fwd: pd.DataFrame,
    *,
    eligible: pd.DataFrame | None = None,
    min_obs: int = 15,
) -> pd.DataFrame:
    """Return raw daily IC with shape ``time x factor``."""
    return pd.DataFrame(
        {
            name: rank_ic(frame, fwd, eligible=eligible, min_obs=min_obs)
            for name, frame in factors.items()
        }
    )


def ic_coverage(
    factors: dict[str, pd.DataFrame],
    fwd: pd.DataFrame,
    *,
    eligible: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Pairwise-valid fraction of the eligible cross-section for each factor."""
    if eligible is None:
        eligible = pd.DataFrame(True, index=fwd.index, columns=fwd.columns)
    else:
        eligible = eligible.reindex_like(fwd).fillna(False).astype(bool)
    denominator = eligible.sum(axis=1).replace(0, np.nan)
    return pd.DataFrame(
        {
            name: (
                (frame.notna() & fwd.notna() & eligible).sum(axis=1)
                / denominator
            )
            for name, frame in factors.items()
        }
    )


def factor_corr_penalty(
    A: np.ndarray,
    names: list[str],
    index: pd.Index,
    strength: float,
    floor: float,
    *,
    min_obs: int = 10,
) -> pd.DataFrame:
    """Per-day redundancy penalty in ``[floor, 1]``.

    Correlations are estimated pairwise on finite overlapping assets. Missing
    signals are not converted into a common zero exposure, which otherwise
    creates artificial correlation among sparse factors.
    """
    T, F, _ = A.shape
    pen = np.ones((T, F), dtype=float)
    for t in range(T):
        matrix = A[t]
        totals = np.zeros(F, dtype=float)
        counts = np.zeros(F, dtype=float)
        for i in range(F):
            xi = matrix[i]
            for j in range(i + 1, F):
                xj = matrix[j]
                valid = np.isfinite(xi) & np.isfinite(xj)
                if valid.sum() < max(3, min_obs):
                    continue
                xiv, xjv = xi[valid], xj[valid]
                if np.std(xiv) <= EPS or np.std(xjv) <= EPS:
                    continue
                corr = float(np.corrcoef(xiv, xjv)[0, 1])
                if not np.isfinite(corr):
                    continue
                value = abs(corr)
                totals[i] += value
                totals[j] += value
                counts[i] += 1.0
                counts[j] += 1.0
        mean_abs = np.divide(
            totals,
            counts,
            out=np.zeros_like(totals),
            where=counts > 0,
        )
        pen[t] = 1.0 - mean_abs
    pen = np.clip(pen, floor, 1.0)
    blend = 1.0 - strength * (1.0 - pen)
    return pd.DataFrame(blend, index=index, columns=names)


def ic_state(
    ic_raw: pd.DataFrame,
    *,
    horizon: int,
    lam: float,
    clip: float,
    vol_floor: float = 0.02,
    min_history: int = 21,
    hit_rate_win: int = 63,
    coverage: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Causal IC state used by both allocation and PM diagnostics."""
    alpha = 1.0 - lam
    purged = ic_raw.clip(-clip, clip).shift(horizon + 1)
    mean = purged.ewm(
        alpha=alpha,
        adjust=False,
        min_periods=min_history,
        ignore_na=True,
    ).mean()
    vol = purged.ewm(
        alpha=alpha,
        adjust=False,
        min_periods=min_history,
        ignore_na=True,
    ).std(bias=False)
    ir = mean / vol.clip(lower=vol_floor)
    positive = (purged > 0).where(purged.notna())
    hit_rate = positive.rolling(
        hit_rate_win,
        min_periods=max(5, min_history // 2),
    ).mean()
    observations = purged.notna().rolling(hit_rate_win, min_periods=1).sum()
    if coverage is None:
        known_coverage = pd.DataFrame(1.0, index=ic_raw.index, columns=ic_raw.columns)
    else:
        known_coverage = coverage.reindex_like(ic_raw).shift(horizon + 1).ewm(
            alpha=alpha,
            adjust=False,
            min_periods=min_history,
            ignore_na=True,
        ).mean()
    return {
        "purged": purged,
        "mean": mean,
        "vol": vol,
        "ir": ir,
        "hit_rate": hit_rate,
        "observations": observations,
        "coverage": known_coverage,
    }


def _floor_series(
    min_weight: float | Mapping[str, float] | pd.Series,
    columns: pd.Index,
) -> pd.Series:
    if np.isscalar(min_weight):
        return pd.Series(float(min_weight), index=columns)
    return pd.Series(min_weight, dtype=float).reindex(columns).fillna(0.0)


def ic_weights(
    ic_raw: pd.DataFrame,
    *,
    horizon: int,
    lam: float,
    clip: float,
    min_weight: float | Mapping[str, float] | pd.Series,
    penalty: pd.DataFrame | None = None,
    recency_boost: float = 0.0,
    recency_win: int = 21,
    coverage: pd.DataFrame | None = None,
    min_coverage: float = 0.50,
    vol_floor: float = 0.02,
    ir_clip: float = 3.0,
    min_history: int = 21,
    hit_rate_win: int = 63,
) -> pd.DataFrame:
    """Causal reliability-adjusted factor weights summing to one per day."""
    nf = ic_raw.shape[1]
    if nf == 0:
        return pd.DataFrame(index=ic_raw.index)

    state = ic_state(
        ic_raw,
        horizon=horizon,
        lam=lam,
        clip=clip,
        vol_floor=vol_floor,
        min_history=min_history,
        hit_rate_win=hit_rate_win,
        coverage=coverage,
    )
    mean = state["mean"]
    ir = state["ir"].clip(lower=0.0, upper=ir_clip)
    hit = state["hit_rate"].clip(lower=0.0, upper=1.0)
    known_coverage = state["coverage"].clip(lower=0.0, upper=1.0)

    confidence = ir / (1.0 + ir)
    hit_quality = ((hit - 0.40) / 0.20).clip(lower=0.0, upper=1.0)
    reliability = (0.25 + 0.75 * confidence) * (0.50 + 0.50 * hit_quality)
    w = mean.clip(lower=0.0) * reliability * np.sqrt(known_coverage)

    active = mean.notna() & (known_coverage >= min_coverage)
    w = w.where(active, 0.0)

    if penalty is not None:
        w = w * penalty.reindex(index=w.index, columns=w.columns).fillna(1.0)

    if recency_boost > 0:
        recent = mean.rolling(recency_win, min_periods=max(5, recency_win // 3)).mean()
        lo = recent.min(axis=1)
        spread = recent.max(axis=1) - lo
        boost = recent.sub(lo, axis=0).div(spread + EPS, axis=0).fillna(0.5)
        w = w * (1.0 + recency_boost * boost)

    active_count = active.sum(axis=1)
    total = w.sum(axis=1)
    equal_active = active.div(active_count.replace(0, np.nan), axis=0).fillna(0.0)
    equal_all = pd.DataFrame(1.0 / nf, index=w.index, columns=w.columns)
    fallback = equal_active.where(active_count.gt(0), equal_all)
    w = w.div(total.replace(0.0, np.nan), axis=0).fillna(fallback)

    floors = _floor_series(min_weight, w.columns)
    floor_frame = pd.DataFrame(
        np.broadcast_to(floors.to_numpy(), w.shape),
        index=w.index,
        columns=w.columns,
    ).where(active, 0.0)
    w = w.where(w >= floor_frame, floor_frame)
    total = w.sum(axis=1)
    return w.div(total.replace(0.0, np.nan), axis=0).fillna(equal_all)


def latest_ic_diagnostics(
    ic_raw: pd.DataFrame,
    weights: pd.DataFrame,
    *,
    horizon: int,
    lam: float,
    clip: float,
    coverage: pd.DataFrame | None = None,
    vol_floor: float = 0.02,
    min_history: int = 21,
    hit_rate_win: int = 63,
) -> pd.DataFrame:
    """Latest factor health table for PM review and artifact persistence."""
    state = ic_state(
        ic_raw,
        horizon=horizon,
        lam=lam,
        clip=clip,
        vol_floor=vol_floor,
        min_history=min_history,
        hit_rate_win=hit_rate_win,
        coverage=coverage,
    )

    def latest(frame: pd.DataFrame) -> pd.Series:
        return frame.ffill().iloc[-1] if len(frame) else pd.Series(dtype=float)

    result = pd.DataFrame(
        {
            "mean_ic": latest(state["mean"]),
            "ic_vol": latest(state["vol"]),
            "ic_ir": latest(state["ir"]),
            "hit_rate": latest(state["hit_rate"]),
            "observations": latest(state["observations"]),
            "coverage": latest(state["coverage"]),
            "weight": latest(weights),
        }
    )
    result.index.name = "factor"
    return result.sort_values("weight", ascending=False)


def composite_score(
    factors: dict[str, pd.DataFrame],
    weights: pd.DataFrame,
) -> pd.DataFrame:
    """Compute ``sum_f weight[t,f] * factor_f[t,asset]``."""
    names = list(factors)
    first = factors[names[0]]
    array = np.stack(
        [factors[name].to_numpy(dtype=np.float32) for name in names], axis=1
    )
    weight_array = weights.reindex(columns=names).to_numpy(dtype=np.float32)
    score = np.einsum("tf,tfn->tn", weight_array, np.nan_to_num(array))
    return pd.DataFrame(score, index=first.index, columns=first.columns)


def stack_factors(
    factors: dict[str, pd.DataFrame],
) -> tuple[np.ndarray, list[str]]:
    """Stack factor frames while preserving NaNs for pairwise-valid diagnostics."""
    names = list(factors)
    array = np.stack(
        [factors[name].to_numpy(dtype=np.float32) for name in names], axis=1
    )
    return array, names
