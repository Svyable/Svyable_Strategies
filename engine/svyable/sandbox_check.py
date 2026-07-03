"""Read-only and dry-run verification for a real Tastytrade sandbox account.

This module is safe for a manually triggered CI environment: it validates the
OAuth session, loads the configured sandbox account, reads positions and a quote,
and asks the broker to dry-run a one-share equity order. It never submits.
"""

from __future__ import annotations

import json
from typing import Any

from svyable.broker_settings import TastySettings
from svyable.tastytrade_sdk import OrderIntent, TastySdkBroker


def _masked_account(account_number: str) -> str:
    return f"...{account_number[-4:]}" if account_number else "not-configured"


def run_sandbox_check(
    broker: TastySdkBroker | None = None,
    *,
    symbol: str = "SPY",
) -> dict[str, Any]:
    settings = broker.settings if broker is not None else TastySettings.from_env()
    if not settings.is_test:
        raise RuntimeError(
            "Sandbox check refuses production credentials. Set TASTY_IS_TEST=true."
        )
    broker = broker or TastySdkBroker(settings=settings)

    session_valid = broker.validate_session()
    account = broker.get_account()
    positions = broker.get_positions_frame()
    quote = broker.get_quote(symbol)
    preflight = broker.preflight(
        OrderIntent(
            symbol=symbol,
            side="buy",
            quantity=1,
            order_type="market",
            tif="day",
            dry_run=True,
        )
    )

    result = {
        "status": "PASS"
        if session_valid and preflight.get("status") == "PASS"
        else "BLOCKED",
        "environment": broker.environment,
        "account": _masked_account(broker.account_number),
        "session_valid": bool(session_valid),
        "account_checks": {
            "equity_positive": float(account.get("equity", 0.0)) > 0,
            "buying_power_nonnegative": float(account.get("buying_power", 0.0)) >= 0,
            "positions_count": len(positions),
        },
        "quote": {
            "symbol": quote.symbol,
            "bid": quote.bid,
            "ask": quote.ask,
            "mark": quote.mark,
            "updated_at": quote.updated_at,
        },
        "preflight": {
            "status": preflight.get("status"),
            "warnings": preflight.get("warnings", []),
            "errors": preflight.get("errors", []),
        },
        "submitted": False,
    }
    return result


def main() -> int:
    result = run_sandbox_check()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
