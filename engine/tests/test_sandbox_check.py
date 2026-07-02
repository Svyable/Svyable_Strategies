"""Offline tests for the non-submitting sandbox integration check."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.sandbox_check import run_sandbox_check
from svyable.tastytrade_sdk import QuoteSnapshot


class FakeBroker:
    environment = "sandbox"
    account_number = "TEST1234"

    def __init__(self, *, is_test: bool = True):
        self.settings = TastySettings(
            client_secret="x",
            refresh_token="y",
            account_number=self.account_number,
            is_test=is_test,
        )

    def validate_session(self):
        return True

    def get_account(self):
        return {"equity": 100000.0, "buying_power": 50000.0}

    def get_positions_frame(self):
        return [{"symbol": "AAPL", "quantity": 1}]

    def get_quote(self, symbol):
        return QuoteSnapshot(
            symbol=symbol,
            bid=499.0,
            ask=501.0,
            last=500.0,
            mark=500.0,
            close=498.0,
            prev_close=497.0,
            volume=1000.0,
            updated_at="now",
        )

    def preflight(self, intent):
        assert intent.dry_run is True
        return {"status": "PASS", "warnings": [], "errors": []}


def test_sandbox_check_never_submits():
    result = run_sandbox_check(FakeBroker())
    assert result["status"] == "PASS"
    assert result["account"] == "...1234"
    assert result["preflight"]["status"] == "PASS"
    assert result["submitted"] is False


def test_sandbox_check_rejects_production_settings():
    try:
        run_sandbox_check(FakeBroker(is_test=False))
        raise AssertionError("production settings were accepted")
    except RuntimeError as exc:
        assert "refuses production" in str(exc)


if __name__ == "__main__":
    test_sandbox_check_never_submits()
    test_sandbox_check_rejects_production_settings()
    print("SANDBOX CHECK TESTS PASSED")
