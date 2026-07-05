"""Shared OHLCV helper functions for frontier alpha factors.

Tape Acceleration and Alpha Catalyst use the same causal daily-bar primitives:
true range, ATR, close location, relative dollar volume, and registry insertion.
Keeping them here prevents factor-family drift and duplicated helper logic.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from svyable import factors as legacy
from svyable.panel import EPS, Panel


FactorFn = Callable[..., pd.DataFrame]


def register_factor(name: str, sleeve: str, fn: FactorFn, *, proven: bool, lineage: str, description: str) -> None:
    """Register a factor without overwriting an existing registry entry."""
    legacy.REGISTRY.setdefault(name, {"fn": fn, "sleeve": sleeve, "proven": proven, "lineage": lineage, "description": description})


def true_range(panel: Panel) -> pd.DataFrame:
    """Daily true range using high/low and previous close."""
    prev_close = panel.close.shift(1)
    return np.maximum(panel.high - panel.low, np.maximum((panel.high - prev_close).abs(), (panel.low - prev_close).abs()))


def atr(panel: Panel, window: int = 14) -> pd.DataFrame:
    """Average true range with causal rolling windows."""
    return true_range(panel).rolling(window, min_periods=max(5, window // 2)).mean()


def close_location(panel: Panel) -> pd.DataFrame:
    """Close location in the daily range, centered around zero."""
    return ((panel.close - panel.low) / (panel.high - panel.low + EPS) - 0.5).clip(-0.5, 0.5)


def rel_dollar_volume(panel: Panel, short: int = 5, long: int = 63) -> pd.DataFrame:
    """Short-vs-long relative dollar-volume participation."""
    fast = panel.dollar_volume.rolling(short, min_periods=max(2, short // 2)).mean()
    slow = panel.dollar_volume.rolling(long, min_periods=max(10, long // 2)).median()
    return (fast / (slow + EPS)).clip(0.10, 6.0)
