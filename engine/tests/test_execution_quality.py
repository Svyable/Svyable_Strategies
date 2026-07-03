"""Deterministic tests for fill slippage and ledger persistence."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.execution_quality import execution_summary, score_fills
from svyable.ledger import Ledger


def test_signed_slippage_is_positive_when_execution_is_worse():
    planned = [
        {"symbol": "BUY", "side": "buy", "est_price": 100.0},
        {"symbol": "SELL", "side": "sell", "est_price": 100.0},
    ]
    fills = [
        {"symbol": "BUY", "side": "buy", "quantity": 2, "fill_price": 101.0, "fees": 0.1},
        {"symbol": "SELL", "side": "sell", "quantity": 3, "fill_price": 99.0, "fees": 0.2},
    ]
    scored = score_fills(fills, planned)
    assert scored[0]["slippage_bps"] == 100.0
    assert scored[1]["slippage_bps"] == 100.0
    summary = execution_summary(scored)
    assert summary["fills"] == 2
    assert summary["mean_abs_slippage_bps"] == 100.0
    assert summary["fees"] == 0.3


def test_ledger_records_fill_quality():
    with TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "ledger.db")
        run_id = ledger.record_run(kind="rebalance", strategy="test", status="ok")
        ledger.record_fills(run_id, "sandbox", [{
            "executed_at": "2026-07-02T10:00:00",
            "order_id": 1,
            "transaction_id": 2,
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "fill_price": 101.0,
            "reference_price": 100.0,
            "slippage_bps": 100.0,
            "fees": 0.05,
            "venue": "TEST",
            "exec_id": "abc",
        }])
        frame = ledger.execution_quality_frame()
        health = ledger.health()
        ledger.close()
        assert len(frame) == 1
        assert health["fills"] == 1
        assert health["slippage_bps_mean_abs"] == 100.0


if __name__ == "__main__":
    test_signed_slippage_is_positive_when_execution_is_worse()
    test_ledger_records_fill_quality()
    print("EXECUTION QUALITY TESTS PASSED")
