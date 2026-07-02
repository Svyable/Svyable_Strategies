"""Rank-IC meta-learner (strategy.md §2.2-2.4) with the §8 fixes:

- purged IC: shift by (horizon + 1), not 1, before smoothing (§8.2)
- causal recency boost: rolling window, no full-sample statistics (§8.1)
- correlation-aware diversification penalty with floor (§2.3)
- positive-only weights, min-weight floor, normalized per day
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.panel import EPS


def rank_ic(factor: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    """Cross-sectional Spearman IC per day (rank-corr across assets)."""
    mask = factor.notna() & fwd.notna()
    f = factor.where(mask).rank(axis=1)
    r = fwd.where(mask).rank(axis=1)
    fx = f.sub(f.mean(axis=1), axis=0)
    rx = r.sub(r.mean(axis=1), axis=0)
    num = (fx * rx).sum(axis=1)
    den = np.sqrt((fx ** 2).sum(axis=1) * (rx ** 2).sum(axis=1))
    return (num / den.replace(0.0, np.nan)).fillna(0.0)


def ic_matrix(factors: dict[str, pd.DataFrame], fwd: pd.DataFrame) -> pd.DataFrame:
    """(time x factor) raw IC."""
    return pd.DataFrame({n: rank_ic(F, fwd) for n, F in factors.items()})


def factor_corr_penalty(A: np.ndarray, names: list[str], index: pd.Index,
                        strength: float, floor: float) -> pd.DataFrame:
    """Per-day penalty in [floor, 1]: down-weight factors correlated with the rest.

    A: (T, F, N) stacked factor z-scores (NaN already -> 0).
    """
    T, F, _ = A.shape
    pen = np.ones((T, F))
    for t in range(T):
        M = A[t]
        if not np.isfinite(M).all() or M.std() < EPS:
            continue
        sd = M.std(axis=1)
        live = sd > EPS
        if live.sum() < 2:
            continue
        C = np.corrcoef(M[live])
        np.fill_diagonal(C, 0.0)
        p = 1.0 - np.nanmean(np.abs(C), axis=1)
        pen[t, live] = np.nan_to_num(p, nan=1.0)
    pen = np.clip(pen, floor, 1.0)
    blend = 1.0 - strength * (1.0 - pen)
    return pd.DataFrame(blend, index=index, columns=names)


def ic_weights(ic_raw: pd.DataFrame, *, horizon: int, lam: float, clip: float,
               min_weight: float, penalty: pd.DataFrame | None = None,
               recency_boost: float = 0.0, recency_win: int = 21) -> pd.DataFrame:
    """(time x factor) non-negative weights summing to 1 per day. Fully causal."""
    nf = ic_raw.shape[1]

    # purge: today's weights use IC known strictly before the fwd window could leak
    ic = ic_raw.clip(-clip, clip).shift(horizon + 1).fillna(0.0)
    ic_smooth = ic.ewm(alpha=1.0 - lam, adjust=False).mean()

    w = ic_smooth.clip(lower=0.0)

    if penalty is not None:
        w = w * penalty.reindex(index=w.index, columns=w.columns).fillna(1.0)

    if recency_boost > 0:
        # CAUSAL replacement for composer_v2's look-ahead boost (§8.1):
        # trailing-window mean of smoothed IC, min-max scaled per day.
        rec = ic_smooth.rolling(recency_win, min_periods=5).mean()
        lo = rec.min(axis=1)
        rng = rec.max(axis=1) - lo
        boost = rec.sub(lo, axis=0).div(rng + EPS, axis=0).fillna(0.5)
        w = w * (1.0 + recency_boost * boost)

    s = w.sum(axis=1)
    w = w.div(s + EPS, axis=0)
    w = w.where(s > EPS, other=1.0 / nf)          # fall back to equal weight

    # min-weight floor, renormalized (composer_v1 lesson)
    w = w.clip(lower=min_weight)
    return w.div(w.sum(axis=1) + EPS, axis=0)


def composite_score(factors: dict[str, pd.DataFrame], weights: pd.DataFrame) -> pd.DataFrame:
    """score(time, asset) = sum_f w[t, f] * F_f[t, :]."""
    names = list(factors)
    first = factors[names[0]]
    A = np.stack([factors[n].to_numpy(dtype=np.float32) for n in names], axis=1)  # (T,F,N)
    W = weights.reindex(columns=names).to_numpy(dtype=np.float32)                  # (T,F)
    S = np.einsum("tf,tfn->tn", W, np.nan_to_num(A))
    return pd.DataFrame(S, index=first.index, columns=first.columns)


def stack_factors(factors: dict[str, pd.DataFrame]) -> tuple[np.ndarray, list[str]]:
    names = list(factors)
    A = np.stack([factors[n].to_numpy(dtype=np.float32) for n in names], axis=1)
    return np.nan_to_num(A), names
