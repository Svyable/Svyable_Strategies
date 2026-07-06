"""Cold-start controls for new listings and fast index inclusions.

The objective is not to pretend a 10-day history is as reliable as a 252-day
history. It is to let new, liquid names enter the model when short-horizon
evidence is strong, while scaling confidence and position caps by observable
history, signal coverage, and early risk.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.panel import EPS, Panel

ANN = 252.0
_GK_CO_COEF = 2.0 * float(np.log(2.0)) - 1.0


@dataclass(frozen=True)
class ColdStartResult:
    trading_age: pd.DataFrame
    factor_coverage: pd.DataFrame
    score_multiplier: pd.DataFrame
    max_pos_multiplier: pd.DataFrame
    range_vol: pd.DataFrame
    risk_cap_multiplier: pd.DataFrame


def trading_age(panel: Panel) -> pd.DataFrame:
    """Count available close bars per asset, preserving the panel shape."""

    return panel.close.notna().cumsum().astype(float)


def factor_coverage(
    factors: dict[str, pd.DataFrame],
    index: pd.Index,
    columns: pd.Index,
) -> pd.DataFrame:
    """Fraction of selected factor signals available for each asset/date."""

    if not factors:
        return pd.DataFrame(1.0, index=index, columns=columns)
    aligned = [
        frame.reindex(index=index, columns=columns).notna().astype(float)
        for frame in factors.values()
    ]
    return sum(aligned).div(float(len(aligned))).clip(0.0, 1.0)


def garman_klass_vol(panel: Panel, window: int, min_periods: int) -> pd.DataFrame:
    """Annualized OHLC range-volatility proxy.

    Range estimators extract more information from short histories than pure
    close-to-close variance. Negative per-bar estimates can occur on noisy bars,
    so they are floored before averaging.
    """

    log_hl = np.log((panel.high / (panel.low + EPS)).clip(lower=EPS))
    log_co = np.log((panel.close / (panel.open + EPS)).clip(lower=EPS))
    daily_var = 0.5 * log_hl**2 - _GK_CO_COEF * log_co**2
    avg_var = daily_var.clip(lower=EPS).rolling(
        window,
        min_periods=max(2, min_periods),
    ).mean()
    return np.sqrt(avg_var * ANN)


def _risk_cap_multiplier(range_vol: pd.DataFrame, floor: float) -> pd.DataFrame:
    median_vol = range_vol.median(axis=1).replace(0.0, np.nan)
    multiplier = range_vol.rdiv(median_vol, axis=0)
    return multiplier.clip(lower=float(floor), upper=1.0).fillna(float(floor))


def cold_start_adjustment(
    panel: Panel,
    factors: dict[str, pd.DataFrame],
    cfg: SvyableConfig,
) -> ColdStartResult:
    """Build score and cap multipliers for sparse-history assets."""

    age = trading_age(panel)
    coverage = factor_coverage(factors, panel.close.index, panel.close.columns)

    min_days = max(1, int(cfg.cold_start_min_trading_days))
    full_days = max(min_days + 1, int(cfg.cold_start_full_trading_days))
    min_cap = float(cfg.cold_start_min_cap_mult)

    age_confidence = (age / float(full_days)).clip(0.0, 1.0)
    coverage_confidence = coverage.clip(0.0, 1.0)
    score_multiplier = np.sqrt(age_confidence * coverage_confidence)
    score_multiplier = score_multiplier.where(
        (age >= min_days) & (coverage >= float(cfg.cold_start_min_factor_coverage)),
        0.0,
    )

    progress = ((age - min_days) / float(full_days - min_days)).clip(0.0, 1.0)
    age_cap = min_cap + (1.0 - min_cap) * progress
    age_cap = age_cap.where(age >= min_days, 0.0).clip(0.0, 1.0)

    rv = garman_klass_vol(
        panel,
        window=max(2, int(cfg.cold_start_vol_win)),
        min_periods=max(2, int(cfg.cold_start_vol_min_periods)),
    )
    risk_cap = _risk_cap_multiplier(rv, floor=float(cfg.cold_start_vol_cap_floor))

    # Mature names keep the normal construction cap; sparse-history names get an
    # extra risk brake if their early range vol is high versus the cross-section.
    max_pos_multiplier = age_cap.where(age < full_days, 1.0)
    max_pos_multiplier = max_pos_multiplier.where(
        age >= full_days,
        max_pos_multiplier * risk_cap,
    ).clip(0.0, 1.0)

    return ColdStartResult(
        trading_age=age,
        factor_coverage=coverage,
        score_multiplier=score_multiplier,
        max_pos_multiplier=max_pos_multiplier,
        range_vol=rv,
        risk_cap_multiplier=risk_cap,
    )


def latest_diagnostics(result: ColdStartResult, as_of=None) -> pd.DataFrame:
    """One-row-per-asset diagnostics for artifacts and PM review."""

    idx = result.trading_age.index
    if not len(idx):
        return pd.DataFrame()
    date = pd.Timestamp(as_of) if as_of is not None else idx[-1]
    if date not in idx:
        date = idx[idx.searchsorted(date) - 1] if idx.searchsorted(date) else idx[0]

    out = pd.DataFrame({
        "trading_age": result.trading_age.loc[date],
        "factor_coverage": result.factor_coverage.loc[date],
        "score_multiplier": result.score_multiplier.loc[date],
        "max_pos_multiplier": result.max_pos_multiplier.loc[date],
        "range_vol": result.range_vol.loc[date],
        "risk_cap_multiplier": result.risk_cap_multiplier.loc[date],
    })
    out.index.name = "symbol"
    out["is_cold_start"] = out["max_pos_multiplier"] < 1.0
    out["eligible_by_cold_start"] = out["max_pos_multiplier"] > 0.0
    return out.sort_values(["is_cold_start", "trading_age"], ascending=[False, True])
