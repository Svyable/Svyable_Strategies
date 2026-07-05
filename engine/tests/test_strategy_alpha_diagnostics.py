"""Tests for strategy alpha diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import SvyableConfig
from svyable.panel import Panel
from svyable.strategy_alpha_diagnostics import (
    factor_correlation_matrix,
    factor_snapshot,
    redundancy_warnings,
    strategy_alpha_diagnostics,
)
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


def _panel() -> Panel:
    idx = pd.bdate_range("2025-01-01", periods=220)
    cols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    t = np.arange(len(idx), dtype=float)
    close = pd.DataFrame(
        {
            "AAA": 100 + t * 0.18 + np.sin(t / 5) * 1.5,
            "BBB": 85 - t * 0.03 + np.cos(t / 9) * 2.2,
            "CCC": 70 + np.sin(t / 3) * 3.0,
            "DDD": 55 + np.maximum(t - 90, 0) * 0.20 + np.sin(t / 7),
            "EEE": 110 + np.cos(t / 4) * 4.0,
            "FFF": 95 + t * 0.08 + np.sin(t / 11) * 5.0,
        },
        index=idx,
    )
    open_ = close.shift(1).fillna(close) * (1.0 + pd.DataFrame(np.sin(t[:, None] / 17) * 0.003 * np.ones(len(cols)), index=idx, columns=cols))
    high = pd.concat([open_, close], axis=0).groupby(level=0).max() * 1.011
    low = pd.concat([open_, close], axis=0).groupby(level=0).min() * 0.989
    volume = pd.DataFrame(
        np.tile(np.linspace(900_000.0, 1_500_000.0, len(cols)), (len(idx), 1))
        * (1.0 + np.abs(np.sin(t[:, None] / 8))),
        index=idx,
        columns=cols,
    )
    return Panel(open=open_, high=high, low=low, close=close, volume=volume)


def test_factor_snapshot_has_coverage_and_latest_symbols():
    snapshot = factor_snapshot(_panel(), SvyableConfig(), TAPE_ACCELERATION)

    assert set(snapshot.index) == set(TAPE_ACCELERATION)
    assert float(snapshot["coverage_63d"].min()) > 0.0
    assert snapshot["latest_assets"].min() > 0
    assert snapshot["top_symbol"].astype(bool).all()


def test_correlation_and_redundancy_helpers_are_well_formed():
    corr = factor_correlation_matrix(_panel(), SvyableConfig(), TAPE_ACCELERATION, lookback=80)

    assert corr.shape == (len(TAPE_ACCELERATION), len(TAPE_ACCELERATION))
    assert set(corr.index) == set(TAPE_ACCELERATION)
    warnings = redundancy_warnings(corr, threshold=0.10)
    assert isinstance(warnings, list)


def test_strategy_alpha_diagnostics_packet_for_tape_acceleration():
    packet = strategy_alpha_diagnostics("svyable_tape_acceleration", _panel(), SvyableConfig())

    assert packet["strategy_id"] == "svyable_tape_acceleration"
    assert packet["factor_count"] >= len(TAPE_ACCELERATION)
    assert packet["status"] in {"PASS", "WATCH"}
    assert packet["snapshot"]
    assert packet["contract"].startswith("Diagnostics only")


if __name__ == "__main__":
    test_factor_snapshot_has_coverage_and_latest_symbols()
    test_correlation_and_redundancy_helpers_are_well_formed()
    test_strategy_alpha_diagnostics_packet_for_tape_acceleration()
    print("STRATEGY ALPHA DIAGNOSTICS TESTS PASSED")
