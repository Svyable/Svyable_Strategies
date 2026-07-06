"""Downside-resilience factors for defensive alpha candidates.

This family fills a different gap than faster catalyst books: it looks for names
that keep residual strength when the market is weak, avoid severe drawdown
capture, recover after broad selloffs, and keep liquidity support during stress.
All transforms are causal daily OHLCV/market-return features and oriented so
higher values are more attractive to own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.factor_ohlcv_tools import atr, close_location, register_factor, rel_dollar_volume, true_range
from svyable.panel import EPS, Panel, residual_returns


def _residual(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    return residual_returns(panel.ret, panel.market_ret, cfg.beta_win)


def _where_dates(frame: pd.DataFrame, mask: pd.Series, other: float = 0.0) -> pd.DataFrame:
    """Apply a date-indexed boolean mask to every asset column.

    Pandas ``DataFrame.where(series)`` can align a Series against columns unless
    the axis is explicit. Downside factors use date masks, so force row-axis
    alignment to avoid silently producing all-NaN frames.
    """
    date_mask = mask.reindex(frame.index).fillna(False).astype(bool)
    return frame.where(date_mask, other=other, axis=0)


def _market_down_mask(panel: Panel, window: int = 63) -> pd.Series:
    """Causal weak-market mask with a sparse-stress fallback.

    The primary definition is a meaningful broad-market down day: market return
    below -0.5 trailing-vol. Calm synthetic/regime fixtures can go long stretches
    without enough such days for rolling conditional factors. In that sparse
    case, fall back to ordinary negative market-return days so the factor remains
    an inspectable downside-conditioning signal rather than degenerating to all
    NaN. Live stressed periods still use the stricter threshold automatically.
    """
    vol = panel.market_ret.rolling(window, min_periods=max(20, window // 2)).std().fillna(0.0)
    stress = panel.market_ret.lt(-0.50 * vol)
    ordinary_down = panel.market_ret.lt(0.0)
    min_stress_events = max(3, window // 10)
    enough_stress = stress.astype(float).rolling(window, min_periods=1).sum().ge(min_stress_events)
    return stress.where(enough_stress, ordinary_down).fillna(False)


def down_market_residual_strength(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Residual strength on weak broad-market days.

    A name scores well when its beta-stripped return remains positive on days
    when the internal market proxy is weak. The statistic is normalized by its
    residual volatility and scaled by the square-root of observed weak-market
    days. If a calm synthetic/live window has no weak-market observations at all,
    it falls back to ordinary rolling residual strength so the factor remains a
    usable resilience proxy instead of degenerating to all-NaN.
    """
    resid = _residual(panel, cfg)
    window = 63
    min_down_days = max(5, window // 8)
    min_resid_days = max(20, window // 2)
    mask = _market_down_mask(panel, window).reindex(resid.index).fillna(False)
    down_resid = _where_dates(resid, mask, other=0.0)
    count = mask.astype(float).rolling(window, min_periods=1).sum()
    conditional_strength = down_resid.rolling(window, min_periods=min_down_days).sum().div(
        count.replace(0.0, np.nan),
        axis=0,
    )
    unconditional_strength = resid.rolling(window, min_periods=min_resid_days).mean()
    enough_weak_samples = count.ge(min_down_days)
    strength = conditional_strength.where(enough_weak_samples, unconditional_strength, axis=0)
    resid_vol = resid.rolling(window, min_periods=min_resid_days).std()
    effective_count = count.where(enough_weak_samples, float(window)).clip(lower=1.0)
    signal = strength.div(resid_vol + EPS, axis=0).mul(np.sqrt(effective_count), axis=0)
    return signal.clip(-6.0, 6.0)


def downside_capture_inverse(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Reward low or positive capture on negative market-return days."""
    mask = _market_down_mask(panel).reindex(panel.ret.index).fillna(False)
    down_mkt = panel.market_ret.where(mask, 0.0)
    denominator = down_mkt.abs().rolling(84, min_periods=30).sum().replace(0.0, np.nan)
    own_down = _where_dates(panel.ret, mask, other=0.0).rolling(84, min_periods=30).sum()
    capture = own_down.div(denominator, axis=0)
    return (-capture).clip(-5.0, 5.0)


def panic_reclaim_strength(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Fast recovery after a broad market selloff with strong close location."""
    mkt_vol = panel.market_ret.rolling(84, min_periods=42).std()
    panic = panel.market_ret.lt(-1.25 * mkt_vol).astype(float)
    recent_panic = panic.rolling(5, min_periods=1).max()
    ret3 = panel.close / (panel.close.shift(3) + EPS) - 1.0
    atr_pct = atr(panel, 21) / (panel.close + EPS)
    reclaim = (ret3 / (np.sqrt(3.0) * (atr_pct + EPS))).clip(-6.0, 6.0)
    loc = 1.0 + close_location(panel).clip(lower=0.0)
    return (reclaim.clip(lower=0.0).mul(recent_panic, axis=0) * loc).clip(-5.0, 5.0)


def drawdown_floor_stability(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Shallow and stable medium-term drawdowns, not just low volatility."""
    rolling_high = panel.close.rolling(126, min_periods=63).max()
    drawdown = (panel.close / (rolling_high + EPS) - 1.0).clip(-1.0, 0.0)
    worst = drawdown.rolling(63, min_periods=32).min().abs()
    variability = drawdown.diff().abs().rolling(42, min_periods=21).mean()
    return (1.0 / (1.0 + 8.0 * worst + 30.0 * variability)).clip(0.0, 1.0)


def liquidity_safety_momentum(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Liquidity support that does not vanish during market weakness."""
    mask = _market_down_mask(panel).reindex(panel.ret.index).fillna(False)
    down_volume = _where_dates(panel.dollar_volume, mask, other=np.nan).rolling(63, min_periods=10).median()
    all_volume = panel.dollar_volume.rolling(63, min_periods=30).median()
    stress_liquidity = (down_volume / (all_volume + EPS)).clip(0.0, 3.0)
    current_participation = np.sqrt(rel_dollar_volume(panel, 10, 84))
    return (stress_liquidity * current_participation).clip(0.0, 5.0)


def volatility_cooldown_momentum(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Positive drift while realized range cools down from a stress spike."""
    tr = true_range(panel)
    short = tr.rolling(10, min_periods=5).mean()
    long = tr.rolling(63, min_periods=32).median()
    prior_spike = (short.shift(5) / (long.shift(5) + EPS)).clip(0.25, 6.0)
    cooldown = (long / (short + EPS)).clip(0.25, 6.0)
    drift = panel.ret.rolling(10, min_periods=5).sum() / (panel.ret.rolling(42, min_periods=21).std() * np.sqrt(10.0) + EPS)
    return (np.sqrt(prior_spike) * np.sqrt(cooldown) * drift.clip(lower=0.0)).clip(-5.0, 5.0)


def register_downside_resilience() -> None:
    register_factor("down_market_residual_strength", "resilience", down_market_residual_strength, proven=False, lineage="down-market residual strength", description="Residual strength measured specifically on weak broad-market days, with rolling residual-strength fallback when weak samples are absent.")
    register_factor("downside_capture_inverse", "resilience", downside_capture_inverse, proven=False, lineage="inverse downside capture", description="Low or positive capture on negative market-return days.")
    register_factor("panic_reclaim_strength", "resilience", panic_reclaim_strength, proven=False, lineage="panic reclaim strength", description="Fast recovery after broad market selloffs with strong close location.")
    register_factor("drawdown_floor_stability", "resilience", drawdown_floor_stability, proven=False, lineage="drawdown floor stability", description="Shallow and stable medium-term drawdowns.")
    register_factor("liquidity_safety_momentum", "liquidity", liquidity_safety_momentum, proven=False, lineage="stress liquidity support", description="Dollar-volume support that remains present during market weakness.")
    register_factor("volatility_cooldown_momentum", "momentum", volatility_cooldown_momentum, proven=False, lineage="volatility cooldown momentum", description="Positive drift as realized range cools down from a stress spike.")


register_downside_resilience()
from svyable import strategy_downside_resilience as _strategy_downside_resilience  # noqa: F401,E402
