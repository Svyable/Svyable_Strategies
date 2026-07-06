"""Regression tests for Svyable Rotation Breadth factors and strategy."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import SvyableConfig
from svyable.factor_library import compute_all, factor_metadata
from svyable.panel import Panel
from svyable.strategy_registry import default_strategy_ids, get_strategy
from svyable.strategy_rotation_breadth import ROTATION_BREADTH


def _panel() -> Panel:
    idx = pd.bdate_range("2025-01-01", periods=260)
    cols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]
    t = np.arange(len(idx), dtype=float)
    close = pd.DataFrame(
        {
            "AAA": 100 + t * 0.16 + np.sin(t / 8) * 1.5,
            "BBB": 95 + np.maximum(t - 80, 0) * 0.18 + np.cos(t / 9) * 2.0,
            "CCC": 80 + np.sin(t / 5) * 4.0 + np.maximum(t - 140, 0) * 0.11,
            "DDD": 65 - t * 0.02 + np.sin(t / 7) * 2.5,
            "EEE": 120 + np.where((t % 50) < 25, t * 0.04, t * 0.10) + np.cos(t / 11),
            "FFF": 55 + np.maximum(t - 120, 0) * 0.22 + np.sin(t / 13) * 1.8,
            "GGG": 75 + t * 0.03 + np.cos(t / 6) * 3.5,
        },
        index=idx,
    )
    open_noise = pd.DataFrame(
        np.tile((np.sin(t / 15) * 0.002)[:, None], (1, len(cols))),
        index=idx,
        columns=cols,
    )
    open_ = close.shift(1).fillna(close) * (1.0 + open_noise)
    high = pd.concat([open_, close], axis=0).groupby(level=0).max() * 1.012
    low = pd.concat([open_, close], axis=0).groupby(level=0).min() * 0.988
    volume = pd.DataFrame(
        np.tile(np.linspace(850_000.0, 1_900_000.0, len(cols)), (len(idx), 1))
        * (1.0 + np.abs(np.sin(t[:, None] / 10))),
        index=idx,
        columns=cols,
    )
    return Panel(open=open_, high=high, low=low, close=close, volume=volume)


def test_rotation_breadth_factors_and_strategy_are_registered():
    metadata = factor_metadata()
    for name in ROTATION_BREADTH:
        assert name in metadata.index

    assert "svyable_rotation_breadth" in default_strategy_ids()
    spec = get_strategy("svyable_rotation_breadth")
    for name in ROTATION_BREADTH:
        assert name in spec.factor_names
    assert spec.regime_profile == "rotation_breadth"
    assert spec.config_overrides["ml_enabled"] is False
    assert spec.minimum_hold_days >= 3


def test_rotation_breadth_factors_compute_recent_frames():
    panel = _panel()
    cfg = SvyableConfig()
    values = compute_all(panel, cfg, names=list(ROTATION_BREADTH))

    assert set(values) == set(ROTATION_BREADTH)
    for frame in values.values():
        assert frame.shape == panel.close.shape
        recent = frame.tail(50)
        assert recent.notna().mean().mean() > 0.55
        assert np.isfinite(recent.dropna(how="all").fillna(0.0).to_numpy()).all()


if __name__ == "__main__":
    test_rotation_breadth_factors_and_strategy_are_registered()
    test_rotation_breadth_factors_compute_recent_frames()
    print("ROTATION BREADTH TESTS PASSED")
