"""Regression tests for Portfolio Arcana and price-action frontier registration."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import SvyableConfig
from svyable.factor_library import factor_metadata
from svyable.panel import Panel
from svyable.portfolio_arcana import arcana_from_panel, market_model
from svyable.strategy_registry import default_strategy_ids, get_strategy


def _panel() -> Panel:
    idx = pd.bdate_range("2025-01-01", periods=320)
    cols = ["AAA", "BBB", "CCC", "DDD"]
    base = pd.DataFrame(
        {
            "AAA": np.linspace(100, 140, len(idx)),
            "BBB": np.linspace(50, 45, len(idx)),
            "CCC": 80 + np.sin(np.linspace(0, 18, len(idx))) * 4,
            "DDD": np.linspace(30, 42, len(idx)) + np.sin(np.linspace(0, 12, len(idx))) * 2,
        },
        index=idx,
    )
    open_ = base.shift(1).fillna(base) * 1.001
    high = pd.concat([open_, base], axis=0).groupby(level=0).max() * 1.01
    low = pd.concat([open_, base], axis=0).groupby(level=0).min() * 0.99
    volume = pd.DataFrame(1_000_000.0, index=idx, columns=cols)
    return Panel(open=open_, high=high, low=low, close=base, volume=volume)


def test_price_action_factors_and_strategy_are_registered():
    metadata = factor_metadata()
    for name in [
        "channel_pressure",
        "compression_thrust",
        "gap_continuation",
        "range_participation",
        "range_rejection",
    ]:
        assert name in metadata.index

    assert "svyable_frontier_price_action" in default_strategy_ids()
    spec = get_strategy("svyable_frontier_price_action")
    assert "channel_pressure" in spec.factor_names
    assert spec.regime_profile == "price_action"


def test_market_model_and_arcana_snapshot_are_well_formed():
    panel = _panel()
    cfg = SvyableConfig()
    weights = pd.Series({"AAA": 0.45, "BBB": -0.20, "CCC": 0.15, "DDD": 0.20})
    portfolio = panel.ret.mul(weights / weights.abs().sum(), axis=1).sum(axis=1)

    summary, residual = market_model(portfolio, panel.market_ret)
    assert summary["status"] == "ok"
    assert len(residual) >= 20
    assert "ann_residual_alpha" in summary

    snapshot = arcana_from_panel(
        weights,
        panel,
        cfg,
        factor_names=["channel_pressure", "range_participation", "range_rejection"],
    )
    assert snapshot.summary["status"] == "ok"
    assert snapshot.summary["factor_count"] == 3
    assert set(snapshot.factor_exposures["factor"]) == {
        "channel_pressure",
        "range_participation",
        "range_rejection",
    }
    assert not snapshot.idio_contributors.empty


if __name__ == "__main__":
    test_price_action_factors_and_strategy_are_registered()
    test_market_model_and_arcana_snapshot_are_well_formed()
    print("PORTFOLIO ARCANA TESTS PASSED")
