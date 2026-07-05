"""Tests for shared OHLCV factor helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.factor_ohlcv_tools import atr, close_location, rel_dollar_volume, true_range
from svyable.panel import Panel


def _panel() -> Panel:
    idx = pd.bdate_range("2026-01-01", periods=40)
    cols = ["AAA", "BBB", "CCC"]
    t = np.arange(len(idx), dtype=float)
    close = pd.DataFrame({"AAA": 100 + t, "BBB": 80 + np.sin(t), "CCC": 60 + t * 0.2}, index=idx)
    open_ = close.shift(1).fillna(close) * 1.001
    high = pd.concat([open_, close], axis=0).groupby(level=0).max() * 1.01
    low = pd.concat([open_, close], axis=0).groupby(level=0).min() * 0.99
    volume = pd.DataFrame(1_000_000.0 + t[:, None] * 1000.0, index=idx, columns=cols)
    return Panel(open=open_, high=high, low=low, close=close, volume=volume)


def test_true_range_atr_close_location_and_volume_shapes():
    panel = _panel()

    assert true_range(panel).shape == panel.close.shape
    assert atr(panel, 14).shape == panel.close.shape
    assert close_location(panel).shape == panel.close.shape
    assert rel_dollar_volume(panel, 3, 21).shape == panel.close.shape


def test_close_location_and_relative_volume_are_bounded():
    panel = _panel()

    loc = close_location(panel).dropna(how="all")
    rel = rel_dollar_volume(panel, 3, 21).dropna(how="all")
    assert float(loc.max().max()) <= 0.5
    assert float(loc.min().min()) >= -0.5
    assert float(rel.max().max()) <= 6.0
    assert float(rel.min().min()) >= 0.10


if __name__ == "__main__":
    test_true_range_atr_close_location_and_volume_shapes()
    test_close_location_and_relative_volume_are_bounded()
    print("FACTOR OHLCV TOOLS TESTS PASSED")
