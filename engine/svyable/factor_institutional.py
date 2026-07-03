"""Institutional price-action factor extensions.

These signals stay inside the existing daily OHLCV contract. They target three
separate jobs: trend quality, asymmetric beta capture, and crash resilience.
Every function is causal and returns a raw cross-sectional characteristic;
``factor_library.compute_all`` performs the common robust z-score afterwards.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable import factors as legacy
from svyable.config import SvyableConfig
from svyable.panel import EPS, Panel, residual_returns


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


def _conditional_beta(
    returns: pd.DataFrame,
    market: pd.Series,
    window: int,
    *,
    positive_market: bool,
) -> pd.DataFrame:
    condition = market > 0 if positive_market else market < 0
    market_masked = market.where(condition)
    returns_masked = returns.where(condition, axis=0)
    minimum = max(20, window // 3)
    covariance = returns_masked.rolling(window, min_periods=minimum).cov(market_masked)
    variance = market_masked.rolling(window, min_periods=minimum).var()
    return covariance.div(variance + EPS, axis=0)


def downside_beta_resilience(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Prefer stocks with lower sensitivity specifically on market-down days."""
    downside = _conditional_beta(
        panel.ret, panel.market_ret, cfg.beta_win, positive_market=False
    )
    return -downside


def beta_asymmetry(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Upside capture minus downside capture using conditional rolling betas."""
    upside = _conditional_beta(
        panel.ret, panel.market_ret, cfg.beta_win, positive_market=True
    )
    downside = _conditional_beta(
        panel.ret, panel.market_ret, cfg.beta_win, positive_market=False
    )
    return (upside - downside).clip(-3.0, 3.0)


def drawdown_resilience(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Shallow historical drawdowns plus current recovery state."""
    window = max(63, cfg.resilience_win)
    rolling_peak = panel.close.rolling(window, min_periods=window // 2).max()
    drawdown = panel.close / (rolling_peak + EPS) - 1.0
    worst = drawdown.rolling(window, min_periods=window // 2).min()
    return worst + 0.25 * drawdown


def gap_resilience(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Low downside overnight-gap semivolatility."""
    overnight = panel.open / (panel.close.shift(1) + EPS) - 1.0
    downside = overnight.clip(upper=0.0)
    semivol = np.sqrt(
        downside.pow(2).rolling(
            cfg.gap_risk_win,
            min_periods=max(20, cfg.gap_risk_win // 2),
        ).mean()
    )
    return -semivol


def multi_horizon_trend(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Risk-adjusted trend strength rewarded when horizons agree in sign."""
    daily_vol = panel.ret.rolling(63, min_periods=32).std()
    signals: list[pd.DataFrame] = []
    signs: list[pd.DataFrame] = []
    for horizon in cfg.trend_horizons:
        trailing = panel.close / (panel.close.shift(horizon) + EPS) - 1.0
        scaled = trailing / (daily_vol * np.sqrt(float(horizon)) + EPS)
        signals.append(scaled.clip(-5.0, 5.0))
        signs.append(np.sign(trailing))
    strength = sum(signals) / len(signals)
    agreement = (sum(signs) / len(signs)).abs()
    return strength * (0.5 + 0.5 * agreement)


def residual_trend_tstat(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """T-statistic of beta-stripped daily returns over the trend window."""
    residual = residual_returns(panel.ret, panel.market_ret, cfg.beta_win)
    window = max(63, cfg.trend_tstat_win)
    mean = residual.rolling(window, min_periods=window // 2).mean()
    volatility = residual.rolling(window, min_periods=window // 2).std()
    return (mean / (volatility + EPS) * np.sqrt(window)).clip(-6.0, 6.0)


def volume_confirmed_breakout(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Range-normalized breakout confirmed by dollar-volume participation."""
    window = 63
    prior_high = panel.high.rolling(window, min_periods=42).max().shift(1)
    average_range = (panel.high - panel.low).rolling(21, min_periods=10).mean()
    breakout = ((panel.close - prior_high) / (average_range + EPS)).clip(-4.0, 4.0)
    relative_volume = (
        panel.dollar_volume
        / (panel.dollar_volume.rolling(window, min_periods=32).median() + EPS)
    ).clip(0.25, 4.0)
    close_location = (
        (panel.close - panel.low) / (panel.high - panel.low + EPS) - 0.5
    ).clip(-0.5, 0.5)
    return breakout * np.sqrt(relative_volume) + 0.25 * close_location


def correlation_shock_resilience(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Prefer assets whose market correlation rises less in selloffs."""
    window = max(63, cfg.resilience_win)
    unconditional = panel.ret.rolling(
        window, min_periods=window // 2
    ).corr(panel.market_ret)
    downside_returns = panel.ret.where(panel.market_ret < 0, axis=0)
    downside_market = panel.market_ret.where(panel.market_ret < 0)
    downside = downside_returns.rolling(
        window, min_periods=max(20, window // 3)
    ).corr(downside_market)
    return -(downside - unconditional).clip(-2.0, 2.0)


def register_institutional_extensions() -> None:
    _register(
        "downside_beta_resilience",
        "defensive",
        downside_beta_resilience,
        proven=True,
        lineage="conditional downside beta / low-risk literature",
        description="Negative rolling beta estimated only on market-down days.",
    )
    _register(
        "beta_asymmetry",
        "defensive",
        beta_asymmetry,
        proven=False,
        lineage="upside/downside capture asymmetry",
        description="Conditional upside beta minus conditional downside beta.",
    )
    _register(
        "drawdown_resilience",
        "defensive",
        drawdown_resilience,
        proven=True,
        lineage="low-risk and drawdown-resilience characteristic",
        description="Shallow rolling drawdowns with a current-recovery adjustment.",
    )
    _register(
        "gap_resilience",
        "defensive",
        gap_resilience,
        proven=False,
        lineage="overnight downside-gap risk",
        description="Negative trailing overnight downside semivolatility.",
    )
    _register(
        "multi_horizon_trend",
        "momentum",
        multi_horizon_trend,
        proven=True,
        lineage="multi-horizon time-series and cross-sectional trend",
        description="Risk-adjusted 1/3/6/12-month trend rewarded for sign agreement.",
    )
    _register(
        "residual_trend_tstat",
        "momentum",
        residual_trend_tstat,
        proven=True,
        lineage="residual momentum / trend significance",
        description="Rolling t-statistic of beta-stripped daily returns.",
    )
    _register(
        "volume_confirmed_breakout",
        "momentum",
        volume_confirmed_breakout,
        proven=False,
        lineage="breakout with price-volume confirmation",
        description="Range-normalized breakout scaled by relative dollar volume.",
    )
    _register(
        "correlation_shock_resilience",
        "defensive",
        correlation_shock_resilience,
        proven=False,
        lineage="conditional correlation and contagion resilience",
        description="Low increase in market correlation during down-market sessions.",
    )


register_institutional_extensions()
