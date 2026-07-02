"""Offline tests for delayed fill recovery and slippage escalation."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.execution_backfill import ExecutionBackfillMixin
from svyable.ledger import Ledger


class FakeTransaction:
    id = 9001
    order_id = 7001
    symbol = "AAPL"
    underlying_symbol = "AAPL"
    action = "Buy to Open"
    quantity = Decimal("5")
    price = Decimal("101")
    commission = Decimal("0")
    regulatory_fees = Decimal("0.01")
    clearing_fees = Decimal("0.01")
    proprietary_index_option_fees = None
    other_charge = None
    executed_at = datetime(2026, 7, 2, 15, 0, tzinfo=timezone.utc)
    destination_venue = "TEST"
    exchange = "TEST"
    exec_id = "exec-9001"


class FakeAccount:
    async def get_history(self, session, **kwargs):
        return [FakeTransaction()]


class FakeBroker:
    session = object()
    sdk = SimpleNamespace(InstrumentType=SimpleNamespace(EQUITY="Equity"))

    async def _get_account_async(self):
        return FakeAccount()


class FakeService(ExecutionBackfillMixin):
    def __init__(self, ledger_path: Path):
        self.ledger_path = ledger_path
        self.broker = FakeBroker()
        self.settings = TastySettings(
            client_secret="x",
            refresh_token="y",
            account_number="TEST123",
            is_test=True,
            audit_path=ledger_path.with_suffix(".jsonl"),
            slippage_warn_bps=10.0,
            slippage_critical_bps=20.0,
        )


def seed_order(path: Path) -> None:
    ledger = Ledger(path)
    run_id = ledger.record_run(kind="rebalance", strategy="test", status="ok")
    ledger.record_orders(
        run_id,
        "tastytrade-sdk",
        False,
        [{
            "symbol": "AAPL",
            "side": "buy",
            "qty": 5,
            "est_price": 100.0,
            "est_notional": 500.0,
            "reason": "rebalance",
        }],
        [{"symbol": "AAPL", "status": "Filled", "id": 7001}],
    )
    ledger.close()


def test_backfill_is_idempotent_and_escalates_slippage():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.db"
        seed_order(path)
        service = FakeService(path)

        first = service.backfill_execution_quality(since_days=5)
        second = service.backfill_execution_quality(since_days=5)

        assert first["fills_found"] == 1
        assert first["execution_quality"]["worst_slippage_bps"] == 100.0
        assert second["fills_found"] == 1

        ledger = Ledger(path)
        fills = ledger.execution_quality_frame()
        escalations = ledger.con.execute(
            "SELECT COUNT(*) FROM events WHERE level='critical' "
            "AND source='execution_quality_backfill'"
        ).fetchone()[0]
        ledger.close()

        assert len(fills) == 1
        assert fills.iloc[0]["broker_order_id"] == 7001
        assert escalations >= 1


if __name__ == "__main__":
    test_backfill_is_idempotent_and_escalates_slippage()
    print("EXECUTION BACKFILL TESTS PASSED")
