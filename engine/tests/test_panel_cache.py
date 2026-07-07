"""Regression tests for Panel-derived cache behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.panel import Panel


def _panel() -> Panel:
    index = pd.bdate_range("2026-01-05", periods=5)
    columns = ["AAA", "BBB"]
    close = pd.DataFrame(
        {
            "AAA": [10.0, 10.0, 10.0, 10.0, 10.0],
            "BBB": [100.0, 100.0, 100.0, 100.0, 100.0],
        },
        index=index,
        columns=columns,
    )
    volume = pd.DataFrame(
        {
            "AAA": [1000, 1000, 1000, 1000, 1000],
            "BBB": [1000, 1000, 1000, 1000, 1000],
        },
        index=index,
        columns=columns,
    )
    return Panel(
        open=close.copy(),
        high=close.copy(),
        low=close.copy(),
        close=close,
        volume=volume,
    )


def test_liquidity_mask_cache_is_keyed_by_policy():
    panel = _panel()

    loose = panel.liquidity_mask(min_adv=0.0, min_price=0.0, adv_win=3)
    strict = panel.liquidity_mask(min_adv=50_000.0, min_price=50.0, adv_win=3)

    assert bool(loose.iloc[-1]["AAA"])
    assert bool(loose.iloc[-1]["BBB"])
    assert not bool(strict.iloc[-1]["AAA"])
    assert bool(strict.iloc[-1]["BBB"])

    panel_reversed = _panel()
    strict_first = panel_reversed.liquidity_mask(min_adv=50_000.0, min_price=50.0, adv_win=3)
    loose_second = panel_reversed.liquidity_mask(min_adv=0.0, min_price=0.0, adv_win=3)

    assert not bool(strict_first.iloc[-1]["AAA"])
    assert bool(loose_second.iloc[-1]["AAA"])


if __name__ == "__main__":
    test_liquidity_mask_cache_is_keyed_by_policy()
    print("PANEL CACHE TESTS PASSED")
