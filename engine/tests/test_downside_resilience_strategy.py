"""Regression tests for Svyable Downside Resilience factors and strategy."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import SvyableConfig
from svyable.factor_library import compute_all, factor_metadata
from svyable.panel import Panel
from svyable.strategy_downside_resilience import DOWNSIDE_RESILIENCE
from svyable.strategy_registry import default_strategy_ids, get_strategy


def _panel() -> Panel:
    idx = pd.bdate_range("2025-01-01", periods=280)
    cols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    t = np.arange(len(idx), dtype=float)
    market = 100 + t * 0.04 + np.sin(t / 15) * 4.0 - np.maximum(t - 160, 0) * 0.015
    close = pd.DataFrame(
        {
            "AAA": market + t * 0.05 + np.sin(t / 7) * 1.5,
            "BBB": market * 0.80 - t * 0.03 + np.cos(t / 9) * 2.5,
            "CCC": 70 + np.sin(t / 4) * 3.0 + np.maximum(t - 130, 0) * 0.06,
            "DDD": 55 + np.maximum(t - 150, 0) * 0.12 + np.sin(t / 11) * 1.7,
            "EEE": 120 - t * 0.01 + np.cos(t / 5) * 3.0,
            "FFF": 95 + t * 0.03 + np.sin(t / 13) * 5.0,
        },
        index=idx,
    )
    open_noise = pd.DataFrame(
        np.tile((np.sin(t / 17) * 0.0025)[:, None], (1, len(cols))),
        index=idx,
        columns=cols,
    )
    open_ = close.shift(1).fillna(close) * (1.0 + open_noise)
    high = pd.concat([open_, close], axis=0).groupby(level=0).max() * 1.011
    low = pd.concat([open_, close], axis=0).groupby(level=0).min() * 0.989
    volume = pd.DataFrame(
        np.tile(np.linspace(900_000.0, 1_700_000.0, len(cols)), (len(idx), 1))
        * (1.0 + np.abs(np.sin(t[:, None] / 8))),
        index=idx,
        columns=cols,
    )
    return Panel(open=open_, high=high, low=low, close=close, volume=volume)


def test_downside_resilience_factors_and_strategy_are_registered():
    metadata = factor_metadata()
    for name in DOWNSIDE_RESILIENCE:
        assert name in metadata.index

    assert "svyable_downside_resilience" in default_strategy_ids()
    spec = get_strategy("svyable_downside_resilience")
    for name in DOWNSIDE_RESILIENCE:
        assert name in spec.factor_names
    assert spec.regime_profile == "downside_resilience"
    assert spec.config_overrides["ml_enabled"] is False
    assert spec.config_overrides["target_vol"] <= 0.12
    assert spec.minimum_hold_days >= 5


def test_downside_resilience_factors_compute_recent_frames():
    panel = _panel()
    cfg = SvyableConfig()
    values = compute_all(panel, cfg, names=list(DOWNSIDE_RESILIENCE))

    assert set(values) == set(DOWNSIDE_RESILIENCE)
    for frame in values.values():
        assert frame.shape == panel.close.shape
        recent = frame.tail(50)
        assert recent.notna().mean().mean() > 0.55
        assert np.isfinite(recent.dropna(how="all").fillna(0.0).to_numpy()).all()


if __name__ == "__main__":
    test_downside_resilience_factors_and_strategy_are_registered()
    test_downside_resilience_factors_compute_recent_frames()
    print("DOWNSIDE RESILIENCE TESTS PASSED")
