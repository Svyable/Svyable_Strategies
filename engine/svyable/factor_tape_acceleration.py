"""Svyable-designed daily tape-acceleration factors.

The factors are pure OHLCV transforms, causal at the daily bar, and oriented so
higher values are more attractive to own. They target short-to-medium horizon
alpha that the existing broad trend/reversal books may miss: post-compression
breakouts, pullback reclaims, gap behavior, exhaustion reversals, and persistent
range/volume acceleration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.factor_ohlcv_tools import atr, close_location, register_factor, rel_dollar_volume, true_range
from svyable.panel import EPS, Panel


def liquidity_squeeze_breakout(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Breakout after compressed range/liquidity, confirmed by returning volume."""
    tr = true_range(panel)
    short_range = tr.rolling(10, min_periods=5).mean()
    long_range = tr.rolling(63, min_periods=32).median()
    compression = (long_range / (short_range + EPS)).clip(0.25, 5.0)
    prev_high = panel.high.rolling(42, min_periods=21).max().shift(1)
    atr_pct = atr(panel, 14) / (panel.close.shift(1) + EPS)
    breakout = ((panel.close / (prev_high + EPS) - 1.0) / (atr_pct + EPS)).clip(-5.0, 5.0)
    volume_confirm = np.sqrt(rel_dollar_volume(panel, 5, 63))
    return (compression * breakout * volume_confirm).clip(-6.0, 6.0)


def pullback_reclaim(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Medium-trend pullback that reclaims short moving averages on a strong close."""
    ma10 = panel.close.rolling(10, min_periods=5).mean()
    ma21 = panel.close.rolling(21, min_periods=10).mean()
    ma63 = panel.close.rolling(63, min_periods=32).mean()
    average_range = atr(panel, 14) + EPS
    trend = ((ma21 / (ma63 + EPS) - 1.0) / (average_range / (panel.close + EPS) + EPS)).clip(-4.0, 4.0)
    recent_low = panel.low.rolling(8, min_periods=4).min()
    pullback_depth = ((ma21 - recent_low) / average_range).clip(0.0, 4.0)
    reclaim = ((panel.close - ma10) / average_range).clip(-4.0, 4.0)
    close_loc = close_location(panel).clip(lower=0.0)
    return (trend.clip(lower=0.0) * pullback_depth * reclaim.clip(lower=0.0) * (1.0 + close_loc)).clip(-5.0, 5.0)


def gap_reversal_pressure(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Fade signal when a meaningful overnight gap is rejected intraday."""
    prev_close = panel.close.shift(1)
    overnight = panel.open / (prev_close + EPS) - 1.0
    intraday = panel.close / (panel.open + EPS) - 1.0
    atr_pct = atr(panel, 14) / (prev_close + EPS)
    gap_size = (overnight.abs() / (atr_pct + EPS)).clip(0.0, 5.0)
    reversal = -np.sign(overnight) * intraday / (atr_pct + EPS)
    return (reversal * np.sqrt(1.0 + gap_size)).rolling(5, min_periods=3).mean().clip(-5.0, 5.0)


def opening_drive_continuation(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Continuation when the opening gap and intraday drive point the same way."""
    prev_close = panel.close.shift(1)
    overnight = panel.open / (prev_close + EPS) - 1.0
    intraday = panel.close / (panel.open + EPS) - 1.0
    atr_pct = atr(panel, 14) / (prev_close + EPS)
    same_way = np.sign(overnight) * intraday / (atr_pct + EPS)
    participation = np.sqrt(rel_dollar_volume(panel, 3, 63)) * (1.0 + close_location(panel).abs())
    return (same_way * participation).rolling(3, min_periods=2).mean().clip(-5.0, 5.0)


def exhaustion_reversal(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Reversal pressure after a stretched 5-day move with wick and volume evidence."""
    atr_pct = atr(panel, 14) / (panel.close + EPS)
    move5 = panel.close / (panel.close.shift(5) + EPS) - 1.0
    stretched = (move5 / (np.sqrt(5.0) * (atr_pct + EPS))).clip(-6.0, 6.0)
    loc = close_location(panel)
    volume = np.sqrt(rel_dollar_volume(panel, 5, 63))
    lower_reversal = (-stretched).clip(lower=0.0) * loc.clip(lower=0.0) * volume
    upper_reversal = stretched.clip(lower=0.0) * (-loc).clip(lower=0.0) * volume
    return (lower_reversal - upper_reversal).clip(-5.0, 5.0)


def range_volume_acceleration(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Three-day return acceleration confirmed by expanding range and volume."""
    ret3 = panel.close / (panel.close.shift(3) + EPS) - 1.0
    ret21 = panel.close / (panel.close.shift(21) + EPS) - 1.0
    atr_pct = atr(panel, 14) / (panel.close + EPS)
    acceleration = ((ret3 - ret21 / 7.0) / (np.sqrt(3.0) * (atr_pct + EPS))).clip(-6.0, 6.0)
    tr = true_range(panel)
    range_expansion = (tr.rolling(3, min_periods=2).mean() / (tr.rolling(21, min_periods=10).median() + EPS)).clip(0.25, 4.0)
    volume = np.sqrt(rel_dollar_volume(panel, 3, 63))
    persistence = (np.sign(panel.ret).rolling(8, min_periods=4).mean()).clip(-1.0, 1.0)
    return (acceleration * np.sqrt(range_expansion) * volume + persistence).clip(-6.0, 6.0)


def register_tape_acceleration() -> None:
    register_factor("liquidity_squeeze_breakout", "momentum", liquidity_squeeze_breakout, proven=False, lineage="daily OHLCV squeeze breakout", description="Range compression followed by prior-high breakout on returning dollar volume.")
    register_factor("pullback_reclaim", "momentum", pullback_reclaim, proven=False, lineage="daily OHLCV pullback reclaim", description="Trend-persistent pullback that reclaims short moving averages with strong close location.")
    register_factor("gap_reversal_pressure", "meanrev", gap_reversal_pressure, proven=False, lineage="daily OHLCV gap rejection", description="Intraday rejection of a meaningful overnight gap, oriented toward the reversal.")
    register_factor("opening_drive_continuation", "momentum", opening_drive_continuation, proven=False, lineage="daily OHLCV opening drive", description="Continuation when overnight gap and intraday drive align with participation.")
    register_factor("exhaustion_reversal", "meanrev", exhaustion_reversal, proven=False, lineage="daily OHLCV exhaustion reversal", description="Stretched 5-day move with wick/volume evidence for reversal.")
    register_factor("range_volume_acceleration", "momentum", range_volume_acceleration, proven=False, lineage="daily OHLCV range-volume acceleration", description="Short return acceleration confirmed by expanding range, volume, and directional persistence.")


register_tape_acceleration()
from svyable import strategy_tape_acceleration as _strategy_tape_acceleration  # noqa: F401,E402
