"""Ledger regression tests for rebalance execution outcomes."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.ledger import Ledger


PLANNED = [
    {
        "symbol": "AAA",
        "side": "sell",
        "qty": 5,
        "est_price": 10.0,
        "est_notional": 50.0,
        "reason": "rebalance",
    },
    {
        "symbol": "BBB",
        "side": "buy",
        "qty": 5,
        "est_price": 10.0,
        "est_notional": 50.0,
        "reason": "rebalance",
    },
]


def _run_status(db_path: Path, run_id: int) -> str:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        con.close()


def test_record_orders_downgrades_fail_fast_rebalance_to_failed():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.db"
        ledger = Ledger(path)
        run_id = ledger.record_run(kind="rebalance", strategy="test", status="ok")
        ledger.record_orders(
            run_id,
            "paper",
            False,
            PLANNED,
            [
                {"symbol": "AAA", "status": "rejected", "error": "test"},
                {"symbol": "BBB", "status": "skipped_after_failure"},
            ],
        )
        ledger.close()
        assert _run_status(path, run_id) == "failed"


def test_record_orders_downgrades_best_effort_rebalance_to_degraded():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.db"
        ledger = Ledger(path)
        run_id = ledger.record_run(kind="rebalance", strategy="test", status="ok")
        ledger.record_orders(
            run_id,
            "paper",
            False,
            PLANNED,
            [
                {"symbol": "AAA", "status": "rejected", "error": "test"},
                {"symbol": "BBB", "status": "filled"},
            ],
        )
        ledger.close()
        assert _run_status(path, run_id) == "degraded"


def test_record_orders_keeps_dry_runs_ok():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.db"
        ledger = Ledger(path)
        run_id = ledger.record_run(kind="rebalance", strategy="test", status="ok")
        ledger.record_orders(
            run_id,
            "paper",
            True,
            PLANNED,
            [{"symbol": "AAA", "status": "planned"}],
        )
        ledger.close()
        assert _run_status(path, run_id) == "ok"


if __name__ == "__main__":
    test_record_orders_downgrades_fail_fast_rebalance_to_failed()
    test_record_orders_downgrades_best_effort_rebalance_to_degraded()
    test_record_orders_keeps_dry_runs_ok()
    print(json.dumps({"status": "LEDGER EXECUTION STATUS TESTS PASSED"}))
