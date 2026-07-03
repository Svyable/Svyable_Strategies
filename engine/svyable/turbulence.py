"""Cross-sectional turbulence and absorption regime model.

Two complementary, fully causal signals computed on the shared daily panel,
combined into a throttle that multiplies the risk budget (strategy.md §12.4
stack). Both react to *structure*, not just magnitude, so they de-risk before
realized portfolio volatility can:

1. Mahalanobis turbulence (Kritzman-Li 2010): the distance of today's
   cross-asset return vector from its recent multivariate distribution. It
   spikes when returns are unusually large OR when assets move "wrong"
   relative to their historical correlation structure.
2. Absorption ratio (Kritzman-Li-Page-Rigobon 2011): the fraction of total
   variance explained by the top principal components. High and rising
   absorption means a tightly coupled, fragile market where shocks propagate.

The throttle only ever removes exposure (multiplier in [turb_floor, 1]); it
never adds leverage, and the kill switch downstream still has the last word.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.panel import EPS


def _model_dates(index: pd.Index, window: int, step: int) -> list[int]:
    """Positions at which the covariance model is refreshed (causal, anchored
    at the series start so truncating the future never shifts past refreshes)."""
    return list(range(window, len(index), step))


def turbulence_index(
    returns: pd.DataFrame,
    *,
    window: int = 504,
    step: int = 5,
    shrink: float = 0.10,
    min_coverage: float = 0.90,
    keep_frac: float = 0.80,
) -> pd.Series:
    """Normalized Mahalanobis distance d²/N of each day's return vector.

    The covariance model (mean, shrunk covariance Cholesky) is refreshed every
    ``step`` days from the trailing ``window`` and applied to subsequent days
    until the next refresh — day t only ever sees data through t-1. Assets
    need ``min_coverage`` non-missing days in the window to participate.

    The model must describe *normal* times: a naive rolling estimate absorbs a
    crisis within days and the index collapses exactly when it should be
    screaming. Crisis days are individually modest but correlated, so
    winsorization cannot remove them; instead an MCD-style robust pass scores
    every window day under an initial model, drops the most turbulent
    ``1 - keep_frac``, and re-estimates from the quiet majority. Distances are
    then computed on raw returns against that normal-times model.
    """

    def _fit(sample: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        mu = np.nanmean(sample, axis=0)
        centered = np.nan_to_num(sample - mu, nan=0.0)
        cov = centered.T @ centered / max(1, len(centered) - 1)
        diag = np.diag(np.diag(cov))
        shrunk = (1.0 - shrink) * cov + shrink * diag
        shrunk[np.diag_indices_from(shrunk)] += EPS
        try:
            return mu, np.linalg.cholesky(shrunk), centered
        except np.linalg.LinAlgError:
            return None

    values = returns.to_numpy(dtype=np.float64)
    index = returns.index
    out = np.full(len(index), np.nan)

    chol = None
    mu = None
    cols: np.ndarray | None = None
    refreshes = set(_model_dates(index, window, step))

    for t in range(window, len(index)):
        if t in refreshes or chol is None:
            sample = values[t - window : t]
            coverage = np.isfinite(sample).mean(axis=0)
            cols = np.where(coverage >= min_coverage)[0]
            if len(cols) < 5:
                chol = None
                continue
            first = _fit(sample[:, cols])
            if first is None:
                chol = None
                continue
            mu, chol, centered = first
            scores = (np.linalg.solve(chol, centered.T) ** 2).sum(axis=0)
            keep = np.sort(
                np.argsort(scores)[: max(30, int(len(scores) * keep_frac))]
            )
            refit = _fit(sample[keep][:, cols])
            if refit is not None:
                mu, chol, _ = refit
        if chol is None or cols is None or mu is None:
            continue
        x = np.nan_to_num(values[t, cols] - mu, nan=0.0)
        z = np.linalg.solve(chol, x)   # chol is lower-triangular; z'z = x' Σ⁻¹ x
        out[t] = float(z @ z) / len(cols)

    return pd.Series(out, index=index, name="turbulence")


def absorption_ratio(
    returns: pd.DataFrame,
    *,
    window: int = 126,
    step: int = 5,
    top_frac: float = 0.20,
    min_coverage: float = 0.90,
) -> pd.Series:
    """Fraction of total variance absorbed by the top ``top_frac`` eigenvectors
    of the trailing correlation matrix. Refreshed every ``step`` days; causal."""
    values = returns.to_numpy(dtype=np.float64)
    index = returns.index
    out = np.full(len(index), np.nan)

    last = np.nan
    refreshes = set(_model_dates(index, window, step))
    for t in range(window, len(index)):
        if t in refreshes:
            sample = values[t - window : t]
            coverage = np.isfinite(sample).mean(axis=0)
            cols = np.where(coverage >= min_coverage)[0]
            if len(cols) >= 5:
                sub = sample[:, cols]
                mu = np.nanmean(sub, axis=0)
                sd = np.nanstd(sub, axis=0) + EPS
                z = np.nan_to_num((sub - mu) / sd, nan=0.0)
                corr = z.T @ z / max(1, len(z) - 1)
                eig = np.linalg.eigvalsh(corr)
                k = max(1, int(round(top_frac * len(cols))))
                last = float(eig[-k:].sum() / (eig.sum() + EPS))
        out[t] = last

    return pd.Series(out, index=index, name="absorption")


def regime_frame(returns: pd.DataFrame, cfg: SvyableConfig) -> pd.DataFrame:
    """Turbulence + absorption diagnostics and the composite budget throttle.

    - ``turb_pct``: rolling percentile of the turbulence index; the throttle
      ramps in above ``turb_on_pct`` and saturates at ``turb_full_pct``.
    - ``absorption_delta``: standardized 15d-vs-1y shift in absorption; a
      rising ratio (0.5-2.0 sigma ramp) marks increasing fragility.
    - ``throttle``: 1 - (1 - turb_floor) * composite, clipped to
      [turb_floor, 1]. Missing early history resolves to 1 (no de-risking).
    """
    turb = turbulence_index(
        returns,
        window=cfg.turb_win,
        step=cfg.turb_step,
        shrink=cfg.turb_shrink,
        keep_frac=cfg.turb_keep_frac,
    )
    turb_pct = turb.rolling(cfg.turb_rank_win, min_periods=63).rank(pct=True)
    span = max(cfg.turb_full_pct - cfg.turb_on_pct, 1e-6)
    turb_signal = ((turb_pct - cfg.turb_on_pct) / span).clip(0.0, 1.0)

    absorb = absorption_ratio(
        returns,
        window=cfg.absorption_win,
        step=cfg.turb_step,
        top_frac=cfg.absorption_top_frac,
    )
    base_mean = absorb.rolling(252, min_periods=126).mean()
    base_std = absorb.rolling(252, min_periods=126).std()
    absorb_delta = (absorb.rolling(15, min_periods=10).mean() - base_mean) / (
        base_std + EPS
    )
    absorb_signal = ((absorb_delta - 0.5) / 1.5).clip(0.0, 1.0)

    aw = cfg.absorption_weight
    composite = ((1.0 - aw) * turb_signal + aw * absorb_signal).fillna(0.0)
    throttle = (1.0 - (1.0 - cfg.turb_floor) * composite).clip(
        cfg.turb_floor, 1.0
    )

    return pd.DataFrame(
        {
            "turbulence": turb,
            "turb_pct": turb_pct,
            "turb_signal": turb_signal,
            "absorption": absorb,
            "absorption_delta": absorb_delta,
            "absorption_signal": absorb_signal.fillna(0.0),
            "throttle": throttle,
        }
    )
