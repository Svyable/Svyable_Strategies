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


def _atr(panel: Panel, window: int = 14) -> pd.DataFrame:
    """Wilder true range averaged over ``window`` bars.

    True range is the largest of the current high-low span and the gap-adjusted
    moves against the prior close, so it captures overnight jumps the intraday
    range misses. Used to normalize price-distance technical factors by each
    name's own volatility, making them cross-sectionally comparable.
    """
    prev_close = panel.close.shift(1)
    true_range = np.maximum(
        panel.high - panel.low,
        np.maximum((panel.high - prev_close).abs(), (panel.low - prev_close).abs()),
    )
    return true_range.rolling(window, min_periods=max(5, window // 2)).mean()


def _ma_cloud(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Position relative to the 50- and 200-day moving-average 'cloud'.

    ATR-normalized distance above both key moving averages; a standard trend
    location signal. Higher means the price sits well above its own long-run
    averages relative to its volatility (trend continuation tilt).
    """
    atr = _atr(panel, 14) + EPS
    ma_fast = panel.close.rolling(50, min_periods=25).mean()
    ma_slow = panel.close.rolling(200, min_periods=100).mean()
    return (panel.close - ma_fast) / atr + (panel.close - ma_slow) / atr


def _vol_breakout(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Volatility expansion confirmed by trend direction.

    ATR relative to its own 20-day average times the sign of trailing momentum:
    positive when range is expanding while price trends up (a directional
    breakout), negative when expansion accompanies a decline.
    """
    atr = _atr(panel, 14)
    expansion = atr / (atr.rolling(20, min_periods=10).mean() + EPS) - 1.0
    momentum = panel.close / (panel.close.shift(21) + EPS) - 1.0
    return expansion * np.sign(momentum)


def _calm_flow(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Declining volume trend (short vs long average).

    Negative of the short-over-long volume ratio, so higher means volume is
    fading — a calm-tape defensive signal that often precedes reversals.
    """
    v_short = panel.volume.rolling(5, min_periods=3).mean()
    v_long = panel.volume.rolling(63, min_periods=32).mean()
    return -(v_short / (v_long + EPS) - 1.0)


def _vol_surprise(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Volume relative to its trailing 21-day average.

    Raw volume-surprise signal; its cross-sectional direction is left to IC
    weighting (elevated volume can precede either continuation or reversal), so
    it is carried as shadow research with no guaranteed weight floor.
    """
    avg = panel.volume.rolling(21, min_periods=10).mean()
    return panel.volume / (avg + EPS) - 1.0


def _idio_tail_risk(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Left-tail idiosyncratic risk: the 5th-percentile residual return.

    The 5% quantile of lagged-beta residual returns is a (negative) worst-case
    move; a higher (shallower) quantile means a thinner left tail, so higher is
    safer. A defensive complement to inverse-volatility that targets crash
    asymmetry rather than dispersion.
    """
    residual = residual_returns(panel.ret, panel.market_ret, cfg.beta_win)
    window = max(63, cfg.idio_win)
    return residual.rolling(window, min_periods=max(21, window // 2)).quantile(0.05)


def _ou_zscore_short(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Short-window Ornstein-Uhlenbeck reversion z-score.

    The same rolling AR(1)/OU state estimator as ``ou_zscore`` but fit on the
    short window (``ou_short_win``), so it reacts to faster range-bound
    reversion. Negated so a rich name (price above its OU mean) scores low.
    """
    return -legacy._ou_params(panel, cfg.ou_short_win, cfg)["zscore"]


def _ou_halflife_signal(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Inverse OU half-life: faster mean reversion is the stronger opportunity.

    Half-life comes from the same rolling OU fit (bounded by ou_halflife_min and
    ou_halflife_max); its inverse ranks names whose deviations decay quickly, so
    a reversion trade is expected to realize sooner.
    """
    half_life = legacy._ou_params(panel, cfg.ou_med_win, cfg)["half_life"]
    return 1.0 / (half_life + EPS)


def _lrev(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Intermediate-horizon (one-month) price reversal.

    Negative trailing return over ``mom_short`` days — the complement to the
    5-day ``srev``; captures mean reversion after sustained one-month moves
    rather than very short-term noise.
    """
    return -(panel.close / (panel.close.shift(cfg.mom_short) + EPS) - 1.0)


def _hloc_close_position(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Close position within the trailing monthly high-low range.

    ``(close - min_low) / (max_high - min_low)`` over ~21 bars, in [0, 1]. High
    values mean the name is closing near the top of its recent range (strength
    within consolidation); distinct from ``breakout``, which measures the
    volatility-scaled distance beyond the prior high.
    """
    window = 21
    hi = panel.high.rolling(window, min_periods=window // 2).max()
    lo = panel.low.rolling(window, min_periods=window // 2).min()
    return (panel.close - lo) / (hi - lo + EPS)


def _momentum_divergence(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Beta-driven share of trailing 12-1 momentum (raw minus residual).

    Both legs are cumulative daily returns over the same skipped 12-1 window;
    since residual = raw - beta*market, their difference is the cumulative
    market/beta component of the trend. High values mean a name's momentum is
    carried mostly by market beta rather than idiosyncratic strength — a
    quality signal whose sign is left to IC, so it is carried as shadow.
    """
    skip, formation = 21, 252
    span = formation - skip
    min_periods = max(63, span // 2)
    raw_mom = panel.ret.shift(skip).rolling(span, min_periods=min_periods).sum()
    residual = residual_returns(panel.ret, panel.market_ret, cfg.beta_win)
    resid_mom = residual.shift(skip).rolling(span, min_periods=min_periods).sum()
    return raw_mom - resid_mom


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
    _register(
        "ma_cloud",
        "momentum",
        _ma_cloud,
        proven=False,
        lineage="technical moving-average cloud location",
        description="ATR-normalized distance above the 50- and 200-day moving averages.",
    )
    _register(
        "vol_breakout",
        "momentum",
        _vol_breakout,
        proven=False,
        lineage="volatility-expansion breakout with trend confirmation",
        description="ATR vs its 20-day average, signed by trailing momentum.",
    )
    _register(
        "calm_flow",
        "defensive",
        _calm_flow,
        proven=False,
        lineage="declining-volume calm-tape proxy",
        description="Negative short-over-long volume ratio; higher means fading volume.",
    )
    _register(
        "vol_surprise",
        "defensive",
        _vol_surprise,
        proven=False,
        lineage="volume surprise vs trailing average",
        description="Volume relative to its 21-day average; direction set by IC.",
    )
    _register(
        "idio_tail_risk",
        "defensive",
        _idio_tail_risk,
        proven=False,
        lineage="idiosyncratic left-tail (crash asymmetry)",
        description="5th-percentile residual return; higher means a thinner left tail.",
    )
    _register(
        "ou_zscore_short",
        "meanrev",
        _ou_zscore_short,
        proven=False,
        lineage="short-window Ornstein-Uhlenbeck reversion",
        description="Negated short-window OU z-score for fast range reversion.",
    )
    _register(
        "ou_halflife_signal",
        "meanrev",
        _ou_halflife_signal,
        proven=False,
        lineage="Ornstein-Uhlenbeck reversion speed",
        description="Inverse OU half-life; higher means faster mean reversion.",
    )
    _register(
        "lrev",
        "meanrev",
        _lrev,
        proven=False,
        lineage="intermediate-horizon reversal",
        description="Negative trailing one-month return (mom_short horizon).",
    )
    _register(
        "hloc_close_position",
        "momentum",
        _hloc_close_position,
        proven=False,
        lineage="monthly high-low range position",
        description="Close position within the trailing 21-bar high-low range, in [0,1].",
    )
    _register(
        "momentum_divergence",
        "momentum",
        _momentum_divergence,
        proven=False,
        lineage="raw-vs-residual momentum divergence (trend quality)",
        description="Cumulative beta-driven share of trailing 12-1 momentum.",
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
