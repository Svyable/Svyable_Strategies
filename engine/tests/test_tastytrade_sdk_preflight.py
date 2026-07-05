"""Offline safety tests for the typed Tastytrade SDK adapter."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.tastytrade_sdk import OrderIntent, TastySdkBroker


class InstrumentType(Enum):
    EQUITY = "Equity"


class Action(Enum):
    BUY_TO_OPEN = "Buy to Open"
    BUY_TO_CLOSE = "Buy to Close"
    SELL_TO_OPEN = "Sell to Open"
    SELL_TO_CLOSE = "Sell to Close"


class Tif(Enum):
    DAY = "Day"
    GTC = "GTC"


class Kind(Enum):
    MARKET = "Market"
    LIMIT = "Limit"


@dataclass
class NewOrder:
    time_in_force: object
    order_type: object
    legs: list
    price: Decimal | None = None


class Equity:
    @classmethod
    async def get(cls, session, symbol):
        item = cls()
        item.symbol = symbol
        return item

    def build_leg(self, quantity, action):
        return {"symbol": self.symbol, "quantity": quantity, "action": action}


@dataclass
class Response:
    warnings: list
    errors: list
    buying_power_effect: object = None
    fee_calculation: object = None
    order: object = None


class Account:
    def __init__(self, warnings=None):
        self.warnings = warnings or []
        self.dry_runs = 0
        self.deleted: list[int] = []

    async def place_order(self, session, order, dry_run=True):
        assert dry_run is True
        self.dry_runs += 1
        return Response(self.warnings, [])

    async def delete_order(self, session, order_id):
        self.deleted.append(int(order_id))


class Session:
    def validate(self):
        return True


async def market_data(session, symbol, instrument_type):
    return SimpleNamespace(
        symbol=symbol,
        bid=Decimal("99"),
        ask=Decimal("101"),
        last=Decimal("100"),
        mark=Decimal("100"),
        close=Decimal("98"),
        prev_close=Decimal("97"),
        volume=Decimal("1000"),
        updated_at="now",
    )


async def market_data_by_type(session, equities):
    return [
        await market_data(session, symbol, InstrumentType.EQUITY) for symbol in equities
    ]


def bindings():
    return SimpleNamespace(
        Account=SimpleNamespace(),
        Session=Session,
        Equity=Equity,
        get_market_data=market_data,
        get_market_data_by_type=market_data_by_type,
        InstrumentType=InstrumentType,
        NewOrder=NewOrder,
        OrderAction=Action,
        OrderStatus=SimpleNamespace(),
        OrderTimeInForce=Tif,
        OrderType=Kind,
    )


def broker(settings: TastySettings, account: Account | None = None) -> TastySdkBroker:
    return TastySdkBroker(
        settings=settings,
        bindings=bindings(),
        session=Session(),
        account=account or Account(),
    )


def test_preflight_is_dry_run_and_audited():
    with TemporaryDirectory() as tmp:
        settings = TastySettings(
            "secret", "refresh", "TEST123", True, False, Path(tmp) / "audit.jsonl"
        )
        account = Account()
        result = broker(settings, account).preflight(OrderIntent("spy", "buy", 1))
        assert result["status"] == "PASS"
        assert account.dry_runs == 1
        assert settings.audit_path.exists()


def test_intent_validation_and_limit_sign():
    with TemporaryDirectory() as tmp:
        settings = TastySettings(
            "secret", "refresh", "TEST123", True, False, Path(tmp) / "audit.jsonl"
        )
        b = broker(settings)
        normalized = OrderIntent(" spy ", "BUY", 2, "limit", "day", 100.25).normalized()
        assert normalized.symbol == "SPY" and normalized.side == "buy"
        order = b.build_equity_order(
            "SPY", 2, "buy", order_type="limit", price=100.25
        )
        assert order.price == Decimal("-100.25")


def test_explicit_buy_to_close_action_is_preserved():
    with TemporaryDirectory() as tmp:
        settings = TastySettings(
            "secret", "refresh", "TEST123", True, False, Path(tmp) / "audit.jsonl"
        )
        order = broker(settings).build_equity_order(
            "SPY", 2, "buy", order_action="buy_to_close"
        )
        assert order.legs[0]["action"] is Action.BUY_TO_CLOSE


def test_production_submit_order_requires_submit_intent_confirmation():
    with TemporaryDirectory() as tmp:
        settings = TastySettings(
            "secret", "refresh", "LIVE123", False, True, Path(tmp) / "audit.jsonl"
        )
        b = broker(settings)
        try:
            b.submit_order("SPY", 1, "buy")
        except RuntimeError as exc:
            assert "submit_intent" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("production submit_order should require submit_intent")


def test_production_cancel_requires_confirmation_and_redacts_audit():
    with TemporaryDirectory() as tmp:
        account = Account()
        settings = TastySettings(
            "secret", "refresh", "LIVE123", False, True, Path(tmp) / "audit.jsonl"
        )
        b = broker(settings, account)
        try:
            b.cancel_order(42)
        except RuntimeError as exc:
            assert "Production cancel requires" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("production cancel should require confirmation")
        text = settings.audit_path.read_text()
        assert "LIVE123" not in text
        assert "***E123" in text
        assert "<redacted>" not in text
        result = b.cancel_order(42, confirmation="LIVE123")
        assert result["status"] == "Cancel Requested"
        assert account.deleted == [42]


def test_audit_redacts_secret_like_payloads():
    with TemporaryDirectory() as tmp:
        settings = TastySettings(
            "secret", "refresh", "TEST123", True, False, Path(tmp) / "audit.jsonl"
        )
        b = broker(settings)
        b._audit(
            "manual_check",
            {
                "refresh_token": "raw-refresh-token",
                "client_secret": "raw-secret",
                "account_number": "TEST123",
                "nested": {"authorization": "Bearer abc"},
            },
        )
        record = json.loads(settings.audit_path.read_text().splitlines()[-1])
        assert record["account"] == "***T123"
        assert record["payload"]["refresh_token"] == "<redacted>"
        assert record["payload"]["client_secret"] == "<redacted>"
        assert record["payload"]["account_number"] == "***T123"
        assert record["payload"]["nested"]["authorization"] == "<redacted>"


if __name__ == "__main__":
    test_preflight_is_dry_run_and_audited()
    test_intent_validation_and_limit_sign()
    test_explicit_buy_to_close_action_is_preserved()
    test_production_submit_order_requires_submit_intent_confirmation()
    test_production_cancel_requires_confirmation_and_redacts_audit()
    test_audit_redacts_secret_like_payloads()
    print("TASTY PREFLIGHT TESTS PASSED")
