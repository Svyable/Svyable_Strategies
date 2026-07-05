"""Regression tests for Svyable Alpha Catalyst factors and strategy."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import SvyableConfig
from svyable.factor_library import compute_all, factor_metadata
from svyable.panel import Panel
from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_registry import default_strategy_ids, get_strategy


def _panel() -> Panel:
    idx = pd.bdate_range("2025-01-01", periods=260)
    cols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    t = np.arange(len(idx), dtype=float)
    market = 100 + t * 0.08 + np.sin(t / 19) * 3.0
    close = pd.DataFrame(
        {
            "AAA": market + t * 0.08 + np.sin(t / 5) * 2.0,
            "BBB": market * 0.85 - t * 0.04 + np.cos(t / 7) * 2.5,
            "CCC": 70 + np.sin(t / 4) * 5.0 + np.maximum(t - 120, 0) * 0.10,
            "DDD": 55 + np.maximum(t - 100, 0) * 0.22 + np.sin(t / 9) * 1.5,
            "EEE": 120 + np.cos(t / 3) * 3.5 - np.maximum(t - 180, 0) * 0.08,
            "FFF": 95 + t * 0.05 + np.sin(t / 13) * 6.0,
        },
        index=idx,
    )
    open_ = close.shift(1).fillna(close) * (1.0 + pd.DataFrame(np.sin(t[:, None] / 11) * 0.003, index=idx, columns=cols))
    high = pd.concat([open_, close], axis=0).groupby(level=0).max() * 1.014
    low = pd.concat([open_, close], axis=0).groupby(level=0).min() * 0.986
    volume = pd.DataFrame(
        np.tile(np.linspace(900_000.0, 1_700_000.0, len(cols)), (len(idx), 1))
        * (1.0 + np.abs(np.sin(t[:, None] / 6))),
        index=idx,
        columns=cols,
    )
    return Panel(open=open_, high=high, low=low, close=close, volume=volume)


def test_alpha_catalyst_factors_and_strategy_are_registered():
    metadata = factor_metadata()
    for name in ALPHA_CATALYST:
        assert name in metadata.index

    assert "svyable_alpha_catalyst" in default_strategy_ids()
    spec = get_strategy("svyable_alpha_catalyst")
    for name in ALPHA_CATALYST:
        assert name in spec.factor_names
    assert spec.regime_profile == "alpha_catalyst"
    assert spec.config_overrides["ml_enabled"] is False
    assert spec.config_overrides["max_pos"] <= 0.09


def test_alpha_catalyst_factors_compute_finite_recent_frames():
    panel = _panel()
    cfg = SvyableConfig()
    values = compute_all(panel, cfg, names=list(ALPHA_CATALYST))

    assert set(values) == set(ALPHA_CATALYST)
    for frame in values.values():
        assert frame.shape == panel.close.shape
        recent = frame.tail(40)
        assert recent.notna().mean().mean() > 0.70
        assert np.isfinite(recent.dropna(how="all").fillna(0.0).to_numpy()).all()


if __name__ == "__main__":
    test_alpha_catalyst_factors_and_strategy_are_registered()
    test_alpha_catalyst_factors_compute_finite_recent_frames()
    print("ALPHA CATALYST TESTS PASSED")
