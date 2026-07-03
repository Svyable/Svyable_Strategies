"""Vectorized pairwise-valid factor redundancy penalties."""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.panel import EPS


def pairwise_corr_penalty(
    array: np.ndarray,
    names: list[str],
    index: pd.Index,
    strength: float,
    floor: float,
    *,
    min_obs: int = 10,
) -> pd.DataFrame:
    """Compute per-date average absolute pairwise correlation without imputation.

    ``array`` has shape time x factor x asset. Sufficient statistics are built
    for every factor pair at once, preserving pairwise-valid observations while
    avoiding Python loops over factor pairs.
    """
    time_count, factor_count, _ = array.shape
    result = np.ones((time_count, factor_count), dtype=float)
    for t in range(time_count):
        matrix = array[t].astype(float, copy=False)
        valid = np.isfinite(matrix).astype(float)
        values = np.nan_to_num(matrix, nan=0.0)
        squared = values * values

        count = valid @ valid.T
        sum_x = values @ valid.T
        sum_y = sum_x.T
        sum_x2 = squared @ valid.T
        sum_y2 = sum_x2.T
        sum_xy = values @ values.T

        safe_count = np.maximum(count, 1.0)
        cov = sum_xy - (sum_x * sum_y / safe_count)
        var_x = sum_x2 - (sum_x * sum_x / safe_count)
        var_y = sum_y2 - (sum_y * sum_y / safe_count)
        denominator = np.sqrt(np.maximum(var_x * var_y, 0.0))
        corr = np.divide(
            cov,
            denominator,
            out=np.full_like(cov, np.nan),
            where=denominator > EPS,
        )
        corr[count < max(3, min_obs)] = np.nan
        np.fill_diagonal(corr, np.nan)

        available = np.isfinite(corr)
        totals = np.nansum(np.abs(corr), axis=1)
        observations = available.sum(axis=1)
        mean_abs = np.divide(
            totals,
            observations,
            out=np.zeros_like(totals),
            where=observations > 0,
        )
        result[t] = 1.0 - mean_abs

    result = np.clip(result, floor, 1.0)
    blended = 1.0 - strength * (1.0 - result)
    return pd.DataFrame(blended, index=index, columns=names)
