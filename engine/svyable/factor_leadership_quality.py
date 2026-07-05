"""Leadership-quality factors for durable alpha candidates.

The existing alpha books are strong at tape acceleration and residual catalysts.
This family adds a slower, higher-quality leadership lens: persistent residual
leadership, tight-base breakouts, drawdown repair, trend efficiency, upside-volume
asymmetry, and quiet accumulation. All factors are causal daily OHLCV transforms
and oriented so higher values are more attractive to own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.factor_ohlcv_tools import atr, close_location, register_factor, rel_dollar_volume, true_range
from svyable.panel import EPS, Panel, residual_returns


def _residual(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    return residual_returns(panel.ret, panel.market_ret, cfg.beta_win)


def residual_leadership_persistence(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Residual leadership that persists across 21-day and 63-day horizons."""
    resid = _residual(panel, cfg)
    fast = resid.rolling(21, min_periods=10).sum()
    slow = resid.rolling(63, min_periods=32).sum() / np.sqrt(63.0 / 21.0)
    vol = resid.rolling(63, min_periods=32).std() * np.sqrt(21.0)
    hit_rate = (resid > 0).rolling(21, min_periods=10).mean().sub(0.5).mul(2.0)
    return ((0.65 * fast + 0.35 * slow) / (vol + EPS) * (1.0 + hit_rate.clip(-0.5, 0.75))).clip(-6.0, 6.0)


def tight_base_breakout_quality(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Breakout from a low-range base with improving volume and strong close location."""
    tr = true_range(panel)
    short_range = tr.rolling(10, min_periods=5).mean()
    base_range = tr.rolling(42, min_periods=21).median()
    long_range = tr.rolling(126, min_periods=63).median()
    compression = (long_range / (base_range + EPS)).clip(0.25, 5.0)
    quiet_base = (base_range / (short_range + EPS)).clip(0.25, 5.0)
    prior_high = panel.close.rolling(84, min_periods=42).max().shift(1)
    breakout = ((panel.close / (prior_high + EPS) - 1.0) / (atr(panel, 21) / (panel.close + EPS) + EPS)).clip(-6.0, 6.0)
    participation = np.sqrt(rel_dollar_volume(panel, 8, 84))
    loc = 1.0 + close_location(panel).clip(lower=0.0)
    return (compression * np.sqrt(quiet_base) * breakout * participation * loc).clip(-6.0, 6.0)


def drawdown_repair_velocity(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Fast recovery from drawdown without requiring a full 52-week high breakout."""
    rolling_high = panel.close.rolling(126, min_periods=63).max()
    drawdown = (panel.close / (rolling_high + EPS) - 1.0).clip(-1.0, 0.0)
    repair = panel.close / (panel.close.shift(15) + EPS) - 1.0
    atr_pct = atr(panel, 21) / (panel.close + EPS)
    recovery = (repair / (np.sqrt(15.0) * (atr_pct + EPS))).clip(-6.0, 6.0)
    remaining_damage = (1.0 + drawdown.abs()).clip(1.0, 2.0)
    close_strength = 1.0 + close_location(panel).clip(lower=0.0)
    return (recovery.clip(lower=0.0) * remaining_damage * close_strength).clip(-5.0, 5.0)


def trend_efficiency_stability(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Medium-term trend that moves efficiently rather than through noisy churn."""
    ret63 = panel.close / (panel.close.shift(63) + EPS) - 1.0
    abs_path = panel.ret.abs().rolling(63, min_periods=32).sum()
    efficiency = (ret63 / (abs_path + EPS)).clip(-2.0, 2.0)
    vol_short = panel.ret.rolling(21, min_periods=10).std()
    vol_long = panel.ret.rolling(84, min_periods=42).std()
    vol_stability = (vol_long / (vol_short + EPS)).clip(0.25, 4.0)
    return (efficiency * np.sqrt(vol_stability)).clip(-5.0, 5.0)


def upside_volume_asymmetry(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """More dollar-volume participation on up days than down days."""
    dollar_volume = panel.dollar_volume
    up_volume = dollar_volume.where(panel.ret > 0, 0.0).rolling(21, min_periods=10).sum()
    down_volume = dollar_volume.where(panel.ret < 0, 0.0).rolling(21, min_periods=10).sum()
    asymmetry = (up_volume - down_volume) / (up_volume + down_volume + EPS)
    participation = np.sqrt(rel_dollar_volume(panel, 5, 63))
    return (asymmetry * participation).clip(-4.0, 4.0)


def quiet_accumulation_pressure(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Positive drift during low-range sessions with steady dollar-volume support."""
    tr = true_range(panel)
    range_ratio = (tr.rolling(5, min_periods=3).mean() / (tr.rolling(63, min_periods=32).median() + EPS)).clip(0.25, 4.0)
    quiet = (1.0 / range_ratio).clip(0.25, 4.0)
    drift = panel.ret.rolling(10, min_periods=5).sum() / (panel.ret.rolling(42, min_periods=21).std() * np.sqrt(10.0) + EPS)
    loc = 1.0 + close_location(panel).clip(lower=0.0)
    volume = np.sqrt(rel_dollar_volume(panel, 10, 84))
    return (drift.clip(lower=0.0) * quiet * loc * volume).clip(-5.0, 5.0)


def register_leadership_quality() -> None:
    register_factor("residual_leadership_persistence", "momentum", residual_leadership_persistence, proven=False, lineage="residual leadership persistence", description="Residual leadership that persists across 21-day and 63-day horizons with positive hit-rate support.")
    register_factor("tight_base_breakout_quality", "momentum", tight_base_breakout_quality, proven=False, lineage="tight-base breakout quality", description="Breakout from a lower-range base confirmed by volume and strong close location.")
    register_factor("drawdown_repair_velocity", "momentum", drawdown_repair_velocity, proven=False, lineage="drawdown repair velocity", description="Fast recovery from a medium-term drawdown with strong close location.")
    register_factor("trend_efficiency_stability", "momentum", trend_efficiency_stability, proven=False, lineage="trend efficiency stability", description="Medium-term trend that advances efficiently rather than through noisy churn.")
    register_factor("upside_volume_asymmetry", "momentum", upside_volume_asymmetry, proven=False, lineage="upside dollar-volume asymmetry", description="Dollar-volume participation is stronger on up days than down days.")
    register_factor("quiet_accumulation_pressure", "momentum", quiet_accumulation_pressure, proven=False, lineage="quiet accumulation pressure", description="Positive drift during lower-range sessions with steady dollar-volume support.")


register_leadership_quality()
from svyable import strategy_leadership_quality as _strategy_leadership_quality  # noqa: F401,E402
