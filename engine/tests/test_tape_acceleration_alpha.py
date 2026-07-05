"""Regression tests for Svyable tape-acceleration factors and strategy."""

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


TAPE_FACTORS = [
    "liquidity_squeeze_breakout",
    "pullback_reclaim",
    "gap_reversal_pressure",
    "opening_drive_continuation",
    "exhaustion_reversal",
    "range_volume_acceleration",
]


def _panel() -> Panel:
    idx = pd.bdate_range("2025-01-01", periods=180)
    cols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    t = np.arange(len(idx), dtype=float)
    close = pd.DataFrame({
        "AAA": 100 + t * 0.20 + np.sin(t / 5) * 2.0,
        "BBB": 90 - t * 0.05 + np.cos(t / 7) * 1.5,
        "CCC": 60 + np.sin(t / 4) * 4.0,
        "DDD": 45 + np.maximum(t - 80, 0) * 0.25 + np.sin(t / 6),
        "EEE": 120 + np.where((t % 20) < 10, t * 0.05, -t * 0.02) + np.cos(t / 3),
    }, index=idx)
    open_ = close.shift(1).fillna(close) * (1.0 + pd.DataFrame(np.sin(t[:, None] / 13) * 0.002 * np.ones(len(cols)), index=idx, columns=cols))
    high = pd.concat([open_, close], axis=0).groupby(level=0).max() * 1.012
    low = pd.concat([open_, close], axis=0).groupby(level=0).min() * 0.988
    volume = pd.DataFrame(
        1_000_000.0 * (1.0 + np.abs(np.sin(t[:, None] / 9))) * np.linspace(0.9, 1.3, len(cols)),
        index=idx,
        columns=cols,
    )
    return Panel(open=open_, high=high, low=low, close=close, volume=volume)


def test_tape_acceleration_factors_and_strategy_are_registered():
    metadata = factor_metadata()
    for name in TAPE_FACTORS:
        assert name in metadata.index

    assert "svyable_tape_acceleration" in default_strategy_ids()
    spec = get_strategy("svyable_tape_acceleration")
    for name in TAPE_FACTORS:
        assert name in spec.factor_names
    assert spec.regime_profile == "tape_acceleration"
    assert spec.config_overrides["ml_enabled"] is False


def test_tape_acceleration_factors_compute_finite_frames():
    panel = _panel()
    cfg = SvyableConfig()
    values = compute_all(panel, cfg, names=TAPE_FACTORS)

    assert set(values) == set(TAPE_FACTORS)
    for frame in values.values():
        assert frame.shape == panel.close.shape
        assert np.isfinite(frame.tail(20).to_numpy()).all()


if __name__ == "__main__":
    test_tape_acceleration_factors_and_strategy_are_registered()
    test_tape_acceleration_factors_compute_finite_frames()
    print("TAPE ACCELERATION ALPHA TESTS PASSED")
