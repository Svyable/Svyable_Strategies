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

from svyable import factors as legacy
from svyable.config import SvyableConfig
from svyable.panel import EPS, Panel


def _register(name: str, sleeve: str, fn, *, proven: bool, lineage: str, description: str) -> None:
    legacy.REGISTRY.setdefault(name, {"fn": fn, "sleeve": sleeve, "proven": proven, "lineage": lineage, "description": description})


def _true_range(panel: Panel) -> pd.DataFrame:
    prev_close = panel.close.shift(1)
    return np.maximum(panel.high - panel.low, np.maximum((panel.high - prev_close).abs(), (panel.low - prev_close).abs()))


def _atr(panel: Panel, window: int = 14) -> pd.DataFrame:
    return _true_range(panel).rolling(window, min_periods=max(5, window // 2)).mean()


def _close_location(panel: Panel) -> pd.DataFrame:
    return ((panel.close - panel.low) / (panel.high - panel.low + EPS) - 0.5).clip(-0.5, 0.5)


def _rel_dollar_volume(panel: Panel, short: int = 5, long: int = 63) -> pd.DataFrame:
    fast = panel.dollar_volume.rolling(short, min_periods=max(2, short // 2)).mean()
    slow = panel.dollar_volume.rolling(long, min_periods=max(10, long // 2)).median()
    return (fast / (slow + EPS)).clip(0.10, 6.0)


def liquidity_squeeze_breakout(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Breakout after compressed range/liquidity, confirmed by returning volume."""
    tr = _true_range(panel)
    short_range = tr.rolling(10, min_periods=5).mean()
    long_range = tr.rolling(63, min_periods=32).median()
    compression = (long_range / (short_range + EPS)).clip(0.25, 5.0)
    prev_high = panel.high.rolling(42, min_periods=21).max().shift(1)
    atr_pct = _atr(panel, 14) / (panel.close.shift(1) + EPS)
    breakout = ((panel.close / (prev_high + EPS) - 1.0) / (atr_pct + EPS)).clip(-5.0, 5.0)
    volume_confirm = np.sqrt(_rel_dollar_volume(panel, 5, 63))
    return (compression * breakout * volume_confirm).clip(-6.0, 6.0)


def pullback_reclaim(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Medium-trend pullback that reclaims short moving averages on a strong close."""
    ma10 = panel.close.rolling(10, min_periods=5).mean()
    ma21 = panel.close.rolling(21, min_periods=10).mean()
    ma63 = panel.close.rolling(63, min_periods=32).mean()
    atr = _atr(panel, 14) + EPS
    trend = ((ma21 / (ma63 + EPS) - 1.0) / (atr / (panel.close + EPS) + EPS)).clip(-4.0, 4.0)
    recent_low = panel.low.rolling(8, min_periods=4).min()
    pullback_depth = ((ma21 - recent_low) / atr).clip(0.0, 4.0)
    reclaim = ((panel.close - ma10) / atr).clip(-4.0, 4.0)
    close_loc = _close_location(panel).clip(lower=0.0)
    return (trend.clip(lower=0.0) * pullback_depth * reclaim.clip(lower=0.0) * (1.0 + close_loc)).clip(-5.0, 5.0)


def gap_reversal_pressure(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Fade signal when a meaningful overnight gap is rejected intraday."""
    prev_close = panel.close.shift(1)
    overnight = panel.open / (prev_close + EPS) - 1.0
    intraday = panel.close / (panel.open + EPS) - 1.0
    atr_pct = _atr(panel, 14) / (prev_close + EPS)
    gap_size = (overnight.abs() / (atr_pct + EPS)).clip(0.0, 5.0)
    reversal = -np.sign(overnight) * intraday / (atr_pct + EPS)
    return (reversal * np.sqrt(1.0 + gap_size)).rolling(5, min_periods=3).mean().clip(-5.0, 5.0)


def opening_drive_continuation(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Continuation when the opening gap and intraday drive point the same way."""
    prev_close = panel.close.shift(1)
    overnight = panel.open / (prev_close + EPS) - 1.0
    intraday = panel.close / (panel.open + EPS) - 1.0
    atr_pct = _atr(panel, 14) / (prev_close + EPS)
    same_way = np.sign(overnight) * intraday / (atr_pct + EPS)
    participation = np.sqrt(_rel_dollar_volume(panel, 3, 63)) * (1.0 + _close_location(panel).abs())
    return (same_way * participation).rolling(3, min_periods=2).mean().clip(-5.0, 5.0)


def exhaustion_reversal(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Reversal pressure after a stretched 5-day move with wick and volume evidence."""
    atr_pct = _atr(panel, 14) / (panel.close + EPS)
    move5 = panel.close / (panel.close.shift(5) + EPS) - 1.0
    stretched = (move5 / (np.sqrt(5.0) * (atr_pct + EPS))).clip(-6.0, 6.0)
    loc = _close_location(panel)
    volume = np.sqrt(_rel_dollar_volume(panel, 5, 63))
    lower_reversal = (-stretched).clip(lower=0.0) * loc.clip(lower=0.0) * volume
    upper_reversal = stretched.clip(lower=0.0) * (-loc).clip(lower=0.0) * volume
    return (lower_reversal - upper_reversal).clip(-5.0, 5.0)


def range_volume_acceleration(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Three-day return acceleration confirmed by expanding range and volume."""
    ret3 = panel.close / (panel.close.shift(3) + EPS) - 1.0
    ret21 = panel.close / (panel.close.shift(21) + EPS) - 1.0
    atr_pct = _atr(panel, 14) / (panel.close + EPS)
    acceleration = ((ret3 - ret21 / 7.0) / (np.sqrt(3.0) * (atr_pct + EPS))).clip(-6.0, 6.0)
    tr = _true_range(panel)
    range_expansion = (tr.rolling(3, min_periods=2).mean() / (tr.rolling(21, min_periods=10).median() + EPS)).clip(0.25, 4.0)
    volume = np.sqrt(_rel_dollar_volume(panel, 3, 63))
    persistence = (np.sign(panel.ret).rolling(8, min_periods=4).mean()).clip(-1.0, 1.0)
    return (acceleration * np.sqrt(range_expansion) * volume + persistence).clip(-6.0, 6.0)


def register_tape_acceleration() -> None:
    _register("liquidity_squeeze_breakout", "momentum", liquidity_squeeze_breakout, proven=False, lineage="daily OHLCV squeeze breakout", description="Range compression followed by prior-high breakout on returning dollar volume.")
    _register("pullback_reclaim", "momentum", pullback_reclaim, proven=False, lineage="daily OHLCV pullback reclaim", description="Trend-persistent pullback that reclaims short moving averages with strong close location.")
    _register("gap_reversal_pressure", "meanrev", gap_reversal_pressure, proven=False, lineage="daily OHLCV gap rejection", description="Intraday rejection of a meaningful overnight gap, oriented toward the reversal.")
    _register("opening_drive_continuation", "momentum", opening_drive_continuation, proven=False, lineage="daily OHLCV opening drive", description="Continuation when overnight gap and intraday drive align with participation.")
    _register("exhaustion_reversal", "meanrev", exhaustion_reversal, proven=False, lineage="daily OHLCV exhaustion reversal", description="Stretched 5-day move with wick/volume evidence for reversal.")
    _register("range_volume_acceleration", "momentum", range_volume_acceleration, proven=False, lineage="daily OHLCV range-volume acceleration", description="Short return acceleration confirmed by expanding range, volume, and directional persistence.")


register_tape_acceleration()
from svyable import strategy_tape_acceleration as _strategy_tape_acceleration  # noqa: F401,E402
