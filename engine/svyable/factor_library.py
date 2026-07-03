"""Production factor catalog layered on the legacy flat registry.

The original Q23 registry remains the formula source for established signals.
This module adds three production controls:

1. factor maturity metadata (proven vs shadow),
2. missing-value preservation through IC estimation, and
3. a small set of high-evidence OHLCV factors absent from the port.

Daily-bar approximations of true order-book quantities remain available as
shadow research, but they receive no guaranteed minimum weight.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from svyable import factors as legacy
from svyable.config import SvyableConfig
from svyable.panel import EPS, Panel, cs_zscore, residual_returns


SHADOW_DAILY_MICRO = {
    "ofi_med",
    "mtf_ofi_alignment",
    "vpin_inv",
    "kyle_lambda_inv",
    "bvc_imbalance",
    "exec_quality",
    "flow_persistence",
    "obv_trend",
}


def _rolling_corr(frame: pd.DataFrame, series: pd.Series, window: int) -> pd.DataFrame:
    return frame.rolling(window, min_periods=max(10, window // 2)).corr(series)


def _register(
    name: str,
    sleeve: str,
    fn,
    *,
    proven: bool,
    lineage: str,
    description: str,
) -> None:
    legacy.REGISTRY.setdefault(
        name,
        {
            "fn": fn,
            "sleeve": sleeve,
            "proven": proven,
            "lineage": lineage,
            "description": description,
        },
    )


def _inv_idio(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    residual = residual_returns(panel.ret, panel.market_ret, cfg.beta_win)
    vol = residual.rolling(
        cfg.idio_win, min_periods=max(10, cfg.idio_win // 2)
    ).std()
    return 1.0 / (vol + EPS)


def _low_corr(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    return -_rolling_corr(panel.ret, panel.market_ret, cfg.idio_win)


def _liquidity(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    return np.log1p(panel.adv(max(63, cfg.adv_win)))


def _micro_noise(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Variance-ratio distance from a random walk; a shadow price-noise proxy."""
    window = max(21, cfg.impact_win)
    one_day = panel.ret.rolling(window, min_periods=window // 2).var()
    five_day = panel.ret.rolling(5).sum().rolling(
        window, min_periods=window // 2
    ).var()
    variance_ratio = five_day / (5.0 * one_day + EPS)
    return -np.log(variance_ratio.clip(lower=EPS)).abs()


def _fip_momentum(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Frog-in-the-pan momentum on a canonical 12-month, one-month-skip window."""
    formation = 252
    skip = 21
    effective = formation - skip
    past_return = panel.close.shift(skip) / (panel.close.shift(formation) + EPS) - 1.0
    lagged_daily = panel.ret.shift(skip)
    positive_share = (lagged_daily > 0).rolling(
        effective, min_periods=max(126, effective // 2)
    ).mean()
    negative_share = (lagged_daily < 0).rolling(
        effective, min_periods=max(126, effective // 2)
    ).mean()
    information_discreteness = np.sign(past_return) * (
        negative_share - positive_share
    )
    continuity = ((1.0 - information_discreteness) / 2.0).clip(0.0, 1.0)
    return past_return * continuity


def _overnight_intraday_tug(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Shadow implementation of persistent overnight vs intraday clientele flow."""
    overnight = panel.open / (panel.close.shift(1) + EPS) - 1.0
    intraday = panel.close / (panel.open + EPS) - 1.0
    window = max(10, cfg.mom_short)
    return overnight.rolling(window, min_periods=window // 2).sum() - intraday.rolling(
        window, min_periods=window // 2
    ).sum()


def _liquidity_momentum(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    residual = residual_returns(panel.ret, panel.market_ret, cfg.beta_win)
    momentum = residual.rolling(
        cfg.mom_win, min_periods=max(21, cfg.mom_win // 2)
    ).sum()
    adv = panel.adv(cfg.adv_win)
    relative_adv = adv.div(adv.median(axis=1) + EPS, axis=0).clip(0.25, 4.0)
    return momentum * np.sqrt(relative_adv)


def _vol_scaled_momentum(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    formation = panel.close.shift(21) / (panel.close.shift(252) + EPS) - 1.0
    vol = panel.ret.rolling(63, min_periods=32).std() * np.sqrt(252.0)
    return formation / (vol + EPS)


# constant from the Garman-Klass estimator: (2 ln 2 - 1)
_GK_CO_COEF = 2.0 * float(np.log(2.0)) - 1.0


def _gk_inv_vol(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Inverse Garman-Klass range volatility.

    Close-to-close vol (the ``inv_vol`` factor) throws away the intraday path.
    The Garman-Klass estimator uses the full OHLC bar and is ~7x more efficient
    per observation, so the defensive tilt reacts faster with less estimation
    noise. Per-bar variance = 0.5*ln(H/L)^2 - (2ln2-1)*ln(C/O)^2, averaged over
    the idio window and annualized before inversion.
    """
    window = max(21, cfg.idio_win)
    log_hl = np.log((panel.high / (panel.low + EPS)).clip(lower=EPS))
    log_co = np.log((panel.close / (panel.open + EPS)).clip(lower=EPS))
    gk_daily = 0.5 * log_hl**2 - _GK_CO_COEF * log_co**2
    gk_var = gk_daily.rolling(window, min_periods=max(10, window // 2)).mean()
    gk_vol = np.sqrt(gk_var.clip(lower=EPS) * 252.0)
    return 1.0 / (gk_vol + EPS)


def _intermediate_momentum(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Novy-Marx intermediate-horizon momentum (the 'echo').

    Distinct from the canonical 12-1 signal: the return earned from t-12m to
    t-7m predicts the cross-section better than the more recent leg, which is
    contaminated by short-term reversal. Formation is close[t-126]/close[t-252].
    """
    return panel.close.shift(126) / (panel.close.shift(252) + EPS) - 1.0


def _return_seasonality(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Heston-Sadka same-calendar-month return seasonality (shadow research).

    Average of each asset's trailing-month return sampled at annual lags 1..5.
    Genuinely orthogonal to price-trend momentum, but higher-variance on daily
    bars — carried as shadow, no guaranteed floor, until IC evidence accrues.
    Missing years are dropped per name rather than imputed to zero.
    """
    horizon = 21
    total: pd.DataFrame | None = None
    count: pd.DataFrame | None = None
    for year in range(1, 6):
        lag = 252 * year
        seasonal = panel.close.shift(lag) / (panel.close.shift(lag + horizon) + EPS) - 1.0
        present = seasonal.notna()
        contribution = seasonal.where(present, 0.0)
        total = contribution if total is None else total.add(contribution)
        indicator = present.astype(float)
        count = indicator if count is None else count.add(indicator)
    return total.div(count.replace(0.0, np.nan))


def register_extensions() -> None:
    _register(
        "inv_idio",
        "defensive",
        _inv_idio,
        proven=True,
        lineage="Ang-Hodrick-Xing-Zhang idiosyncratic volatility",
        description="Inverse volatility of lagged-beta residual returns.",
    )
    _register(
        "low_corr",
        "defensive",
        _low_corr,
        proven=True,
        lineage="low-risk / diversification",
        description="Negative rolling correlation to the internal market proxy.",
    )
    _register(
        "liquidity",
        "defensive",
        _liquidity,
        proven=True,
        lineage="liquidity and implementation capacity",
        description="Log trailing dollar ADV.",
    )
    _register(
        "micro_noise",
        "defensive",
        _micro_noise,
        proven=False,
        lineage="variance-ratio price-noise proxy",
        description="Negative absolute log variance-ratio distance from a random walk.",
    )
    _register(
        "fip_momentum",
        "momentum",
        _fip_momentum,
        proven=True,
        lineage="Da-Gurun-Warachka frog-in-the-pan momentum",
        description="12-1 momentum weighted by information continuity.",
    )
    _register(
        "overnight_intraday_tug",
        "momentum",
        _overnight_intraday_tug,
        proven=False,
        lineage="Lou-Polk-Skouras overnight/intraday decomposition",
        description="Trailing overnight continuation minus intraday continuation.",
    )
    _register(
        "liquidity_momentum",
        "momentum",
        _liquidity_momentum,
        proven=False,
        lineage="residual momentum with capacity confidence",
        description="Residual momentum scaled by cross-sectional relative ADV.",
    )
    _register(
        "vol_scaled_momentum",
        "momentum",
        _vol_scaled_momentum,
        proven=False,
        lineage="risk-managed momentum adaptation",
        description="Classic skipped momentum divided by trailing realized volatility.",
    )
    _register(
        "gk_inv_vol",
        "defensive",
        _gk_inv_vol,
        proven=True,
        lineage="Garman-Klass OHLC range volatility estimator",
        description="Inverse annualized Garman-Klass range volatility.",
    )
    _register(
        "intermediate_momentum",
        "momentum",
        _intermediate_momentum,
        proven=True,
        lineage="Novy-Marx intermediate-horizon momentum ('echo')",
        description="Return from t-12m to t-7m, skipping the recent leg.",
    )
    _register(
        "return_seasonality",
        "momentum",
        _return_seasonality,
        proven=False,
        lineage="Heston-Sadka return seasonality",
        description="Same-calendar-month trailing return averaged over annual lags 1-5.",
    )


register_extensions()


def compute_all(
    panel: Panel,
    cfg: SvyableConfig,
    names: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Compute robust cross-sectional scores while preserving missing values."""
    selected = names or sorted(legacy.REGISTRY)
    result: dict[str, pd.DataFrame] = {}
    for name in selected:
        raw = legacy.REGISTRY[name]["fn"](panel, cfg)
        result[name] = cs_zscore(raw)
    return result


def sleeve_members(sleeve: str) -> list[str]:
    return sorted(
        name
        for name, metadata in legacy.REGISTRY.items()
        if metadata["sleeve"] == sleeve
    )


def is_proven(name: str) -> bool:
    metadata = legacy.REGISTRY[name]
    if name in SHADOW_DAILY_MICRO:
        return False
    return bool(metadata.get("proven", True))


def factor_floors(
    names: Iterable[str],
    proven_floor: float,
) -> pd.Series:
    return pd.Series(
        {
            name: float(proven_floor) if is_proven(name) else 0.0
            for name in names
        },
        dtype=float,
    )


def factor_metadata(names: Iterable[str] | None = None) -> pd.DataFrame:
    selected = list(names) if names is not None else sorted(legacy.REGISTRY)
    rows = []
    for name in selected:
        metadata = legacy.REGISTRY[name]
        shadow_proxy = name in SHADOW_DAILY_MICRO
        rows.append(
            {
                "factor": name,
                "sleeve": metadata["sleeve"],
                "stage": "proven" if is_proven(name) else "shadow",
                "lineage": metadata.get(
                    "lineage",
                    "Q23 legacy implementation" if not shadow_proxy else "daily-bar proxy",
                ),
                "description": metadata.get("description", ""),
                "guaranteed_floor": is_proven(name),
            }
        )
    return pd.DataFrame(rows).set_index("factor").sort_values(["sleeve", "stage"])
