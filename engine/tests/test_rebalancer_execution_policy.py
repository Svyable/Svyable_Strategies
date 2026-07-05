"""Regression tests for rebalance execution policy."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.rebalancer import PlannedOrder, execute_plan


class FailingBroker:
    def __init__(self):
        self.calls: list[str] = []

    def submit_order(self, symbol, qty, side, order_type="market", tif="day"):
        self.calls.append(symbol)
        if symbol == "AAA":
            return {"status": "rejected", "symbol": symbol, "reason": "test"}
        return {"status": "filled", "symbol": symbol, "qty": qty, "side": side}


def orders() -> list[PlannedOrder]:
    return [
        PlannedOrder("AAA", "sell", 5, 10.0, 50.0, "rebalance"),
        PlannedOrder("BBB", "buy", 5, 10.0, 50.0, "rebalance"),
    ]


def test_execute_plan_fails_fast_and_marks_remaining_legs_skipped():
    with TemporaryDirectory() as tmp:
        broker = FailingBroker()
        rec = execute_plan(orders(), broker, tmp, dry_run=False)
        assert rec["status"] == "failed"
        assert rec["aborted"] is True
        assert broker.calls == ["AAA"]
        assert rec["results"][0]["status"] == "rejected"
        assert rec["results"][1]["status"] == "skipped_after_failure"


def test_execute_plan_best_effort_is_degraded_after_failure():
    with TemporaryDirectory() as tmp:
        broker = FailingBroker()
        rec = execute_plan(orders(), broker, tmp, dry_run=False, fail_fast=False)
        assert rec["status"] == "degraded"
        assert rec["aborted"] is False
        assert broker.calls == ["AAA", "BBB"]
        assert len(rec["errors"]) == 1


if __name__ == "__main__":
    test_execute_plan_fails_fast_and_marks_remaining_legs_skipped()
    test_execute_plan_best_effort_is_degraded_after_failure()
    print("REBALANCER EXECUTION POLICY TESTS PASSED")
