"""Regression tests for rebalance execution policy."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.config import nasdaq_lo_config
from svyable.rebalancer import PlannedOrder, execute_plan, plan_orders


class FailingBroker:
    def __init__(self):
        self.calls: list[str] = []

    def submit_order(self, symbol, qty, side, order_type="market", tif="day"):
        self.calls.append(symbol)
        if symbol == "AAA":
            return {"status": "rejected", "symbol": symbol, "reason": "test"}
        return {"status": "filled", "symbol": symbol, "qty": qty, "side": side}


class IntentBroker:
    def __init__(self):
        self.actions: list[str | None] = []

    def submit_intent(self, intent, *, confirmation=""):
        self.actions.append(intent.order_action)
        return {"status": "DRY_RUN", "symbol": intent.symbol, "qty": intent.quantity}


class CapturingPaperBroker:
    def __init__(self):
        self.calls: list[tuple[str, float, str]] = []

    def submit_order(self, symbol, qty, side, order_type="market", tif="day"):
        self.calls.append((symbol, qty, side))
        return {"status": "filled", "symbol": symbol, "qty": qty, "side": side}


def orders() -> list[PlannedOrder]:
    return [
        PlannedOrder("AAA", "sell", 5, 10.0, 50.0, "rebalance", current_qty=5),
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


def test_sdk_path_receives_buy_to_close_for_short_cover():
    targets = pd.Series({"AAA": 0.0})
    prices = {"AAA": 10.0}
    positions = {"AAA": -12.0}
    planned = plan_orders(targets, 100_000.0, prices, positions, nasdaq_lo_config())
    assert planned[0].side == "buy"
    assert planned[0].order_action == "buy_to_close"
    with TemporaryDirectory() as tmp:
        broker = IntentBroker()
        rec = execute_plan(planned, broker, tmp, dry_run=True)
        assert rec["status"] == "dry_run"
        assert broker.actions == ["buy_to_close"]


def test_generic_paper_path_still_uses_protocol_submit_order():
    with TemporaryDirectory() as tmp:
        broker = CapturingPaperBroker()
        rec = execute_plan([PlannedOrder("AAA", "sell", 3, 10.0, 30.0, "exit", 3)], broker, tmp, dry_run=False)
        assert rec["status"] == "ok"
        assert broker.calls == [("AAA", 3, "sell")]


if __name__ == "__main__":
    test_execute_plan_fails_fast_and_marks_remaining_legs_skipped()
    test_execute_plan_best_effort_is_degraded_after_failure()
    test_sdk_path_receives_buy_to_close_for_short_cover()
    test_generic_paper_path_still_uses_protocol_submit_order()
    print("REBALANCER EXECUTION POLICY TESTS PASSED")
