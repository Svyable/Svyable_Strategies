"""Regression tests for Svyable Leadership Quality factors and strategy."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import SvyableConfig
from svyable.factor_library import compute_all, factor_metadata
from svyable.panel import Panel
from svyable.strategy_leadership_quality import LEADERSHIP_QUALITY
from svyable.strategy_registry import default_strategy_ids, get_strategy


def _panel() -> Panel:
    idx = pd.bdate_range("2025-01-01", periods=280)
    cols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    t = np.arange(len(idx), dtype=float)
    close = pd.DataFrame(
        {
            "AAA": 100 + t * 0.18 + np.sin(t / 11) * 2.0,
            "BBB": 90 + t * 0.04 + np.cos(t / 8) * 3.0,
            "CCC": 75 + np.maximum(t - 80, 0) * 0.14 + np.sin(t / 5) * 1.8,
            "DDD": 60 + np.maximum(t - 150, 0) * 0.22 + np.cos(t / 13) * 2.2,
            "EEE": 125 - t * 0.02 + np.sin(t / 7) * 4.0,
            "FFF": 50 + t * 0.08 + np.sin(t / 17) * 5.0,
        },
        index=idx,
    )
    open_noise = pd.DataFrame(
        np.tile((np.sin(t / 13) * 0.0025)[:, None], (1, len(cols))),
        index=idx,
        columns=cols,
    )
    open_ = close.shift(1).fillna(close) * (1.0 + open_noise)
    high = pd.concat([open_, close], axis=0).groupby(level=0).max() * 1.012
    low = pd.concat([open_, close], axis=0).groupby(level=0).min() * 0.988
    volume = pd.DataFrame(
        np.tile(np.linspace(850_000.0, 1_900_000.0, len(cols)), (len(idx), 1))
        * (1.0 + np.abs(np.sin(t[:, None] / 9))),
        index=idx,
        columns=cols,
    )
    return Panel(open=open_, high=high, low=low, close=close, volume=volume)


def test_leadership_quality_factors_and_strategy_are_registered():
    metadata = factor_metadata()
    for name in LEADERSHIP_QUALITY:
        assert name in metadata.index

    assert "svyable_leadership_quality" in default_strategy_ids()
    spec = get_strategy("svyable_leadership_quality")
    for name in LEADERSHIP_QUALITY:
        assert name in spec.factor_names
    assert spec.regime_profile == "leadership_quality"
    assert spec.config_overrides["ml_enabled"] is False
    assert spec.minimum_hold_days >= 4


def test_leadership_quality_factors_compute_recent_frames():
    panel = _panel()
    cfg = SvyableConfig()
    values = compute_all(panel, cfg, names=list(LEADERSHIP_QUALITY))

    assert set(values) == set(LEADERSHIP_QUALITY)
    for frame in values.values():
        assert frame.shape == panel.close.shape
        recent = frame.tail(50)
        assert recent.notna().mean().mean() > 0.70
        assert np.isfinite(recent.dropna(how="all").fillna(0.0).to_numpy()).all()


if __name__ == "__main__":
    test_leadership_quality_factors_and_strategy_are_registered()
    test_leadership_quality_factors_compute_recent_frames()
    print("LEADERSHIP QUALITY TESTS PASSED")
