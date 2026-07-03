"""Causal market-structure regime model.

The regime stack combines four complementary price-only diagnostics:

1. robust Mahalanobis turbulence for unusual multivariate return geometry;
2. absorption ratio for systemic coupling;
3. market breadth for participation deterioration; and
4. panic state for the high-volatility drawdown environment associated with
   momentum crashes and unstable beta.

The composite primarily removes exposure. A small, separately bounded risk-on
boost is allowed only when breadth is strong and turbulence is quiet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.panel import EPS

ANN = 252.0


def _model_dates(index: pd.Index, window: int, step: int) -> list[int]:
    return list(range(window, len(index), step))


def _median_abs_deviation(sample: np.ndarray) -> float:
    """Median absolute deviation from the window's own median."""
    finite = sample[np.isfinite(sample)]
    if finite.size == 0:
        return np.nan
    center = np.median(finite)
    return float(np.median(np.abs(finite - center)))


def turbulence_index(
    returns: pd.DataFrame,
    *,
    window: int = 504,
    step: int = 5,
    shrink: float = 0.10,
    min_coverage: float = 0.90,
    keep_frac: float = 0.80,
) -> pd.Series:
    """Robust normalized Mahalanobis distance, fit only on prior observations."""

    def _fit(sample: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        mean = np.nanmean(sample, axis=0)
        centered = np.nan_to_num(sample - mean, nan=0.0)
        covariance = centered.T @ centered / max(1, len(centered) - 1)
        diagonal = np.diag(np.diag(covariance))
        shrunk = (1.0 - shrink) * covariance + shrink * diagonal
        shrunk[np.diag_indices_from(shrunk)] += EPS
        try:
            return mean, np.linalg.cholesky(shrunk), centered
        except np.linalg.LinAlgError:
            return None

    values = returns.to_numpy(dtype=np.float64)
    index = returns.index
    output = np.full(len(index), np.nan)
    cholesky = None
    mean = None
    columns: np.ndarray | None = None
    refreshes = set(_model_dates(index, window, step))

    for t in range(window, len(index)):
        if t in refreshes or cholesky is None:
            sample = values[t - window : t]
            coverage = np.isfinite(sample).mean(axis=0)
            columns = np.where(coverage >= min_coverage)[0]
            if len(columns) < 5:
                cholesky = None
                continue
            first = _fit(sample[:, columns])
            if first is None:
                cholesky = None
                continue
            mean, cholesky, centered = first
            scores = (np.linalg.solve(cholesky, centered.T) ** 2).sum(axis=0)
            keep_count = max(30, int(len(scores) * keep_frac))
            keep = np.sort(np.argsort(scores)[:keep_count])
            refit = _fit(sample[keep][:, columns])
            if refit is not None:
                mean, cholesky, _ = refit
        if cholesky is None or columns is None or mean is None:
            continue
        finite = np.isfinite(values[t, columns])
        if not finite.any():
            continue
        observation = np.where(finite, values[t, columns] - mean, 0.0)
        standardized = np.linalg.solve(cholesky, observation)
        # normalize by the assets actually observed today, not the model width:
        # zero-imputed halted names must not dilute a crisis reading
        output[t] = float(standardized @ standardized) / int(finite.sum())

    return pd.Series(output, index=index, name="turbulence")


def absorption_ratio(
    returns: pd.DataFrame,
    *,
    window: int = 126,
    step: int = 5,
    top_frac: float = 0.20,
    min_coverage: float = 0.90,
) -> pd.Series:
    """Fraction of correlation variance explained by the leading eigenvectors."""
    values = returns.to_numpy(dtype=np.float64)
    index = returns.index
    output = np.full(len(index), np.nan)
    last = np.nan
    refreshes = set(_model_dates(index, window, step))

    for t in range(window, len(index)):
        if t in refreshes:
            sample = values[t - window : t]
            coverage = np.isfinite(sample).mean(axis=0)
            columns = np.where(coverage >= min_coverage)[0]
            if len(columns) >= 5:
                subset = sample[:, columns]
                mean = np.nanmean(subset, axis=0)
                standard_deviation = np.nanstd(subset, axis=0) + EPS
                standardized = np.nan_to_num(
                    (subset - mean) / standard_deviation, nan=0.0
                )
                correlation = standardized.T @ standardized / max(1, len(standardized) - 1)
                eigenvalues = np.linalg.eigvalsh(correlation)
                count = max(1, int(round(top_frac * len(columns))))
                last = float(eigenvalues[-count:].sum() / (eigenvalues.sum() + EPS))
        output[t] = last

    return pd.Series(output, index=index, name="absorption")


def market_breadth(
    returns: pd.DataFrame,
    *,
    window: int = 126,
    smooth: int = 10,
) -> pd.Series:
    """Share of assets with a positive trailing log return."""
    log_return = np.log1p(returns.clip(lower=-0.999))
    trailing = log_return.rolling(window, min_periods=max(42, window // 2)).sum()
    breadth = (trailing > 0.0).where(trailing.notna()).mean(axis=1)
    return breadth.rolling(smooth, min_periods=max(3, smooth // 2)).mean().rename("breadth")


def panic_state(
    returns: pd.DataFrame,
    cfg: SvyableConfig,
) -> pd.DataFrame:
    """High-volatility drawdown state using the panel's equal-weight proxy."""
    market = returns.mean(axis=1, skipna=True).fillna(0.0)
    growth = (1.0 + market).cumprod()
    peak = growth.rolling(cfg.dd_win, min_periods=1).max()
    drawdown = (1.0 - growth / (peak + EPS)).clip(0.0, 1.0)

    realized_vol = market.rolling(
        cfg.panic_vol_win,
        min_periods=max(10, cfg.panic_vol_win // 2),
    ).std() * np.sqrt(ANN)
    # robust (median / MAD) baseline: a mean/std reference lets a months-long
    # crisis inflate its own baseline and quietly decays the signal, exactly
    # when the panic state should stay on. The median is unmoved until the
    # crisis occupies more than half the trailing window.
    baseline_win = cfg.panic_vol_baseline_win
    min_periods = max(63, baseline_win // 2)
    baseline_median = realized_vol.rolling(
        baseline_win, min_periods=min_periods
    ).median()
    baseline_mad = realized_vol.rolling(
        baseline_win, min_periods=min_periods
    ).apply(_median_abs_deviation, raw=True)
    robust_scale = 1.4826 * baseline_mad
    vol_z = (realized_vol - baseline_median) / (robust_scale + EPS)

    dd_span = max(cfg.panic_dd_full - cfg.panic_dd_on, 1e-6)
    vol_span = max(cfg.panic_vol_z_full - cfg.panic_vol_z_on, 1e-6)
    dd_signal = ((drawdown - cfg.panic_dd_on) / dd_span).clip(0.0, 1.0)
    vol_signal = ((vol_z - cfg.panic_vol_z_on) / vol_span).clip(0.0, 1.0)
    panic = np.sqrt(dd_signal * vol_signal).fillna(0.0)

    return pd.DataFrame(
        {
            "market_drawdown": drawdown,
            "market_realized_vol": realized_vol,
            "market_vol_z": vol_z,
            "panic_signal": panic,
        }
    )


def regime_frame(returns: pd.DataFrame, cfg: SvyableConfig) -> pd.DataFrame:
    """Return regime diagnostics, de-risking throttle, and bounded multiplier."""
    turbulence = turbulence_index(
        returns,
        window=cfg.turb_win,
        step=cfg.turb_step,
        shrink=cfg.turb_shrink,
        keep_frac=cfg.turb_keep_frac,
    )
    turbulence_percentile = turbulence.rolling(
        cfg.turb_rank_win, min_periods=63
    ).rank(pct=True)
    turbulence_span = max(cfg.turb_full_pct - cfg.turb_on_pct, 1e-6)
    turbulence_signal = (
        (turbulence_percentile - cfg.turb_on_pct) / turbulence_span
    ).clip(0.0, 1.0)

    absorption = absorption_ratio(
        returns,
        window=cfg.absorption_win,
        step=cfg.turb_step,
        top_frac=cfg.absorption_top_frac,
    )
    absorption_mean = absorption.rolling(252, min_periods=126).mean()
    absorption_std = absorption.rolling(252, min_periods=126).std()
    absorption_delta = (
        absorption.rolling(15, min_periods=10).mean() - absorption_mean
    ) / (absorption_std + EPS)
    absorption_signal = (
        (absorption_delta - cfg.absorption_delta_on)
        / max(cfg.absorption_delta_span, 1e-6)
    ).clip(0.0, 1.0)

    breadth = market_breadth(
        returns,
        window=cfg.breadth_win,
        smooth=cfg.breadth_smooth,
    )
    breadth_span = max(cfg.breadth_on - cfg.breadth_full, 1e-6)
    breadth_signal = ((cfg.breadth_on - breadth) / breadth_span).clip(0.0, 1.0)

    panic = panic_state(returns, cfg)
    panic_signal = panic["panic_signal"]

    absorption_weight = max(0.0, cfg.absorption_weight)
    breadth_weight = max(0.0, cfg.breadth_weight)
    panic_weight = max(0.0, cfg.panic_weight)
    turbulence_weight = max(
        0.0,
        1.0 - absorption_weight - breadth_weight - panic_weight,
    )
    weight_sum = (
        turbulence_weight + absorption_weight + breadth_weight + panic_weight
    ) or 1.0
    composite = (
        turbulence_weight * turbulence_signal.fillna(0.0)
        + absorption_weight * absorption_signal.fillna(0.0)
        + breadth_weight * breadth_signal.fillna(0.0)
        + panic_weight * panic_signal.fillna(0.0)
    ) / weight_sum
    # smooth the composite (not the raw inputs) so the whole-book throttle stops
    # chattering on the stair-stepped turbulence refresh; a crisis is persistent
    # and survives a short EMA, so protection is retained while turnover is not.
    if cfg.regime_smooth_span > 1:
        composite = composite.ewm(
            span=cfg.regime_smooth_span, adjust=False, min_periods=1
        ).mean()
    throttle = (1.0 - (1.0 - cfg.turb_floor) * composite).clip(
        cfg.turb_floor, 1.0
    )

    breadth_risk_on = (
        (breadth - cfg.regime_boost_breadth)
        / max(1.0 - cfg.regime_boost_breadth, 1e-6)
    ).clip(0.0, 1.0)
    turbulence_quiet = (
        (cfg.regime_boost_turb_pct - turbulence_percentile)
        / max(cfg.regime_boost_turb_pct, 1e-6)
    ).clip(0.0, 1.0)
    risk_on_signal = (
        breadth_risk_on
        * turbulence_quiet
        * (1.0 - panic_signal.fillna(0.0))
    ).fillna(0.0)
    boost = 1.0 + max(0.0, cfg.regime_boost_cap - 1.0) * risk_on_signal

    # readiness: the structural turbulence signal is the slowest to warm, so it
    # gates whether the regime stack is trustworthy. Before it is estimable the
    # composite is driven only by the faster breadth/panic components and the
    # book may optionally be held light via regime_warmup_floor.
    regime_ready = turbulence.notna()
    warmup_floor = float(cfg.regime_warmup_floor)
    lower_bound = min(cfg.turb_floor, warmup_floor)
    warmup_cap = np.where(regime_ready.to_numpy(), cfg.regime_boost_cap, warmup_floor)
    multiplier = (throttle * boost).clip(lower_bound, cfg.regime_boost_cap)
    multiplier = pd.Series(
        np.minimum(multiplier.to_numpy(), warmup_cap),
        index=multiplier.index,
    ).clip(lower_bound, cfg.regime_boost_cap)

    return pd.concat(
        [
            turbulence.rename("turbulence"),
            turbulence_percentile.rename("turb_pct"),
            turbulence_signal.rename("turb_signal"),
            absorption.rename("absorption"),
            absorption_delta.rename("absorption_delta"),
            absorption_signal.fillna(0.0).rename("absorption_signal"),
            breadth.rename("breadth"),
            breadth_signal.fillna(0.0).rename("breadth_signal"),
            panic,
            composite.rename("regime_risk"),
            throttle.rename("throttle"),
            risk_on_signal.rename("risk_on_signal"),
            boost.rename("boost"),
            regime_ready.astype(float).rename("regime_ready"),
            multiplier.rename("multiplier"),
        ],
        axis=1,
    )
