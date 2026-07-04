"""Tests for the live market quote-board transformations.

These are intentionally broker-free. They prove that the GUI's live-market layer
can merge target weights, broker positions, live quotes, spread math, stale quote
fallbacks, and agent-facing tradeability annotations before the real Tastytrade
adapter is involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.dashboard_live_market import _market_table


class _FakeBroker:
    def get_market_snapshot(self, symbols: list[str]):
        return {
            "AAPL": {
                "symbol": "AAPL",
                "bid": 199.90,
                "ask": 200.10,
                "last": 200.00,
                "mark": 200.00,
                "close": 198.00,
                "prev_close": 198.00,
                "volume": 1_000_000,
                "updated_at": "2026-07-04T15:59:00Z",
                "mid": 200.00,
            },
            "MSFT": {
                "symbol": "MSFT",
                "bid": 300.00,
                "ask": 300.60,
                "last": 300.30,
                "mark": 300.30,
                "close": 301.00,
                "prev_close": 301.00,
                "volume": 900_000,
                "updated_at": "2026-07-04T15:59:00Z",
                "mid": 300.30,
            },
        }


class _FakeService:
    broker = _FakeBroker()

    def target_series(self):
        return pd.Series({"AAPL": 0.20, "MSFT": -0.10})


def test_market_table_combines_targets_positions_and_quotes():
    snapshot = {
        "account": {"equity": 100_000.0},
        "positions": pd.DataFrame(
            [
                {"symbol": "AAPL", "quantity": 50, "mark": 199.0},
                {"symbol": "TSLA", "quantity": -3, "mark": 240.0},
            ]
        ),
    }

    table = _market_table(_FakeService(), snapshot, max_symbols=10)

    assert set(table["symbol"]) == {"AAPL", "MSFT", "TSLA"}
    assert {
        "target_w",
        "broker_qty",
        "spread_bps",
        "delta_notional",
        "trade_side_hint",
        "quote_flag",
        "spread_flag",
        "agent_note",
        "quote_ok",
    } <= set(table.columns)
    indexed = table.set_index("symbol")
    aapl = indexed.loc["AAPL"]
    assert bool(aapl["quote_ok"]) is True
    assert aapl["target_notional"] == 20_000.0
    assert aapl["current_notional"] == 10_000.0
    assert aapl["delta_notional"] == 10_000.0
    assert abs(float(aapl["spread_bps"]) - 10.0) < 1e-9
    assert aapl["trade_side_hint"] == "BUY"
    assert aapl["quote_flag"] == "OK"
    assert aapl["spread_flag"] == "OK"
    assert aapl["agent_note"] == "OK: BUY candidate"

    tsla = indexed.loc["TSLA"]
    assert bool(tsla["quote_ok"]) is False
    assert tsla["broker_qty"] == -3.0
    assert tsla["current_notional"] == -720.0
    assert tsla["trade_side_hint"] == "BUY"
    assert tsla["quote_flag"] == "MISSING"
    assert tsla["agent_note"] == "BLOCK: missing live quote"


if __name__ == "__main__":
    test_market_table_combines_targets_positions_and_quotes()
    print("DASHBOARD LIVE MARKET TESTS PASSED")
