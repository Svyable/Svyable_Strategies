"""Portfolio construction (strategy.md §12.3, §13).

Per day, causally: smooth score -> dispersion-adaptive seat selection ->
softmax conviction tilt (or HRP) -> capped-simplex projection ->
EWMA smoothing vs yesterday -> L1 no-trade band.
Output: unit weights (sum = 1 per day); the risk budget scales them later.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from svyable.panel import EPS
from svyable.config import SvyableConfig


def project_capped_simplex(v: np.ndarray, total: float,
                           lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Euclidean projection of v onto {lo <= x <= hi, sum(x) = total}.

    Bisection on the uniform shift tau: x = clip(v + tau, lo, hi).
    Requires sum(lo) <= total <= sum(hi); degrades to closest bound otherwise.
    """
    if hi.sum() < total:            # infeasible: give everything its cap
        return hi.copy()
    if lo.sum() > total:            # infeasible: floor everything
        return lo.copy()
    t_lo = float((lo - v).min()) - 1.0
    t_hi = float((hi - v).max()) + 1.0
    for _ in range(64):
        tau = 0.5 * (t_lo + t_hi)
        s = np.clip(v + tau, lo, hi).sum()
        if s < total:
            t_lo = tau
        else:
            t_hi = tau
    return np.clip(v + 0.5 * (t_lo + t_hi), lo, hi)


def softmax_tilt(base: np.ndarray, scores: np.ndarray, sel: np.ndarray,
                 alpha: float) -> np.ndarray:
    """Blend base weights toward softmax(conviction) on the selected set."""
    out = base.copy()
    s = scores[sel]
    if s.size < 2 or alpha <= 0:
        return out
    z = (s - s.mean()) / (s.std() + EPS)
    sm = np.exp(z - z.max())
    sm /= sm.sum() + EPS
    mass = base[sel].sum()
    out[sel] = ((1.0 - alpha) * base[sel] + alpha * sm * mass)
    out[sel] *= mass / (out[sel].sum() + EPS)
    return out


def _hrp_weights(ret_win: np.ndarray) -> np.ndarray | None:
    """Hierarchical Risk Parity on the selected seats (López de Prado).

    ret_win: (T, k) recent returns of selected assets. Returns k weights or
    None if scipy unavailable / data insufficient.
    """
    try:
        from scipy.cluster.hierarchy import linkage, leaves_list
        from scipy.spatial.distance import squareform
    except ImportError:
        return None
    if ret_win.shape[0] < 40 or ret_win.shape[1] < 3:
        return None
    R = np.nan_to_num(ret_win)
    C = np.corrcoef(R.T)
    C = np.clip(C, -1, 1)
    D = np.sqrt(0.5 * (1 - C))
    np.fill_diagonal(D, 0.0)
    order = leaves_list(linkage(squareform(D, checks=False), method="single"))
    var = R.var(axis=0) + EPS

    w = np.ones(len(order))
    clusters = [list(order)]
    while clusters:
        nxt = []
        for cl in clusters:
            if len(cl) <= 1:
                continue
            mid = len(cl) // 2
            a, b = cl[:mid], cl[mid:]
            va = 1.0 / np.sum(1.0 / var[a])
            vb = 1.0 / np.sum(1.0 / var[b])
            alloc_a = 1.0 - va / (va + vb)
            w[a] *= alloc_a
            w[b] *= (1.0 - alloc_a)
            nxt += [a, b]
        clusters = nxt
    return w / (w.sum() + EPS)


def apply_cluster_caps(w: np.ndarray, sel_idx: np.ndarray, R: np.ndarray,
                       cap: float, thresh: float) -> np.ndarray:
    """Cap the total weight of any correlation cluster among selected seats.

    Clusters = connected components of the graph where seats i,j are linked if
    corr(returns_i, returns_j) > thresh over the trailing window. The risk
    stack sees vol but not theme concentration (an all-semis book looks fine
    to a vol targeter until the theme breaks); this is the concentration brake.
    Excess weight is redistributed pro-rata to uncapped seats.
    """
    k = len(sel_idx)
    if k < 3 or R.shape[0] < 40:
        return w
    sub = R[:, sel_idx]
    sd = np.nanstd(sub, axis=0)
    ok = sd > 1e-12
    if ok.sum() < 3:
        return w
    C = np.corrcoef(np.nan_to_num(sub[:, ok]).T)

    # connected components via label propagation (tiny k, loop is fine)
    idx_ok = sel_idx[ok]
    labels = np.arange(len(idx_ok))
    for _ in range(len(idx_ok)):
        changed = False
        for i in range(len(idx_ok)):
            for j in range(i + 1, len(idx_ok)):
                if C[i, j] > thresh and labels[j] != labels[i]:
                    m = min(labels[i], labels[j])
                    labels[labels == labels[i]] = m
                    labels[labels == labels[j]] = m
                    changed = True
        if not changed:
            break

    out = w.copy()
    excess_total = 0.0
    capped_assets: set[int] = set()
    for lab in np.unique(labels):
        members = idx_ok[labels == lab]
        cw = out[members].sum()
        if cw > cap and len(members) > 1:
            out[members] *= cap / cw
            excess_total += cw - cap
            capped_assets.update(members.tolist())
    if excess_total > 1e-9:
        rest = np.array([i for i in sel_idx if i not in capped_assets])
        if len(rest) and out[rest].sum() > 1e-9:
            out[rest] *= (out[rest].sum() + excess_total) / out[rest].sum()
    return out


@dataclass
class ConstructResult:
    unit_weights: pd.DataFrame
    seats: pd.Series           # seat count per day
    turnover: pd.Series        # L1 turnover of unit weights
    held_days: pd.Series       # 1.0 when the no-trade band held the book


def build_unit_weights(score: pd.DataFrame, returns: pd.DataFrame,
                       liquidity: pd.DataFrame, cfg: SvyableConfig,
                       max_pos_mult: pd.DataFrame | None = None) -> ConstructResult:
    S = score.rolling(cfg.score_smooth_win, min_periods=1).mean()
    S = S.where(liquidity > 0)

    dates, assets = S.index, S.columns
    n = len(assets)
    Sv = S.to_numpy(dtype=float)
    Rv = returns.to_numpy(dtype=float)
    if max_pos_mult is None:
        cap_mult = pd.DataFrame(1.0, index=dates, columns=assets)
    else:
        cap_mult = max_pos_mult.reindex(index=dates, columns=assets).fillna(0.0).clip(0.0, 1.0)
    Mv = cap_mult.to_numpy(dtype=float)

    # dispersion z for adaptive seats (causal: expanding stats)
    disp = S.std(axis=1)
    dz = ((disp - disp.expanding(min_periods=63).mean())
          / (disp.expanding(min_periods=63).std() + EPS)).fillna(0.0).to_numpy()

    W = np.zeros((len(dates), n))
    seats = np.zeros(len(dates), dtype=int)
    turnover = np.zeros(len(dates))
    held = np.zeros(len(dates))
    prev = np.zeros(n)

    use_hrp = cfg.seat_weighting in ("hrp", "blend")

    for t in range(len(dates)):
        s = Sv[t]
        m = Mv[t]
        valid = np.isfinite(s) & np.isfinite(m) & (m > 0.0)
        if valid.sum() < cfg.seats_min:
            W[t] = prev
            seats[t] = int((prev > 0).sum())
            continue

        k = cfg.seats_base
        if cfg.seats_adaptive:
            k = int(np.clip(round(cfg.seats_base - cfg.seats_disp_slope * dz[t]),
                            cfg.seats_min, cfg.seats_max))
        k = min(k, int(valid.sum()))

        order = np.argsort(np.where(valid, -s, np.inf))
        sel_idx = order[:k]
        sel = np.zeros(n, dtype=bool)
        sel[sel_idx] = True

        # base weights: score-proportional (shifted positive)
        ss = s[sel]
        ss = ss - ss.min() + 1e-6
        base = np.zeros(n)
        base[sel] = ss / (ss.sum() + EPS)

        if use_hrp and t >= 63:
            hw = _hrp_weights(Rv[max(0, t - 126):t, sel_idx])
            if hw is not None:
                hrp_full = np.zeros(n)
                hrp_full[sel_idx] = hw
                base = (0.5 * base + 0.5 * hrp_full) if cfg.seat_weighting == "blend" else hrp_full

        tilted = softmax_tilt(base, s, sel, cfg.softmax_tilt_alpha)

        hi = np.where(sel, cfg.max_pos * m, 0.0)
        lo = np.where(sel, np.minimum(cfg.min_pos, hi), 0.0)
        target = project_capped_simplex(tilted, 1.0, lo, hi)

        if cfg.cluster_weight_cap < 1.0 and t >= cfg.cluster_corr_win:
            target = apply_cluster_caps(
                target, sel_idx, Rv[t - cfg.cluster_corr_win:t],
                cfg.cluster_weight_cap, cfg.cluster_corr_thresh)
            target = project_capped_simplex(target, 1.0, lo, hi)

        if t > 0:
            l1 = np.abs(target - prev).sum()
            if l1 < cfg.no_trade_band:
                # hold, but stay feasible under today's selection/caps
                target = project_capped_simplex(prev, 1.0, lo, hi) if prev.sum() > 0 else target
                held[t] = 1.0
            else:
                sm = cfg.weight_smooth_alpha * target + (1 - cfg.weight_smooth_alpha) * prev
                target = project_capped_simplex(sm, 1.0, lo, hi)

        turnover[t] = np.abs(target - prev).sum()
        W[t] = target
        prev = target
        seats[t] = k

    return ConstructResult(
        unit_weights=pd.DataFrame(W, index=dates, columns=assets),
        seats=pd.Series(seats, index=dates),
        turnover=pd.Series(turnover, index=dates),
        held_days=pd.Series(held, index=dates),
    )
