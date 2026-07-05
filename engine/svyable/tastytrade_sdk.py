"""Typed Tastytrade SDK adapter used by the operations dashboard.

This module intentionally keeps the UI away from order construction.  Every
order is validated, written to an append-only audit log, preflighted with the
broker, and only then submitted.  Production submission requires both
``SVYABLE_ENABLE_LIVE=true`` and an account-number confirmation.

The adapter is synchronous at its public boundary so it can satisfy
``BrokerConnector`` and work naturally from Streamlit.  The community
``tastytrade`` package is async, so a small event-loop bridge is kept here.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, TypeVar

from svyable.broker_settings import TastySettings

T = TypeVar("T")

TERMINAL_ORDER_STATUSES = frozenset(
    {"Filled", "Cancelled", "Expired", "Rejected", "Removed", "Partially Removed"}
)

ORDER_ACTIONS = frozenset(
    {"buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"}
)

_SECRET_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "session",
    "credential",
    "api_key",
    "apikey",
)
_ACCOUNT_KEY_FRAGMENTS = ("account", "account_number", "account-number")


def _mask(value: Any, *, keep: int = 4) -> str:
    text = str(value or "")
    if not text:
        return "<empty>"
    if len(text) <= keep:
        return "*" * len(text)
    return f"***{text[-keep:]}"


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            if any(fragment in lower for fragment in _SECRET_KEY_FRAGMENTS):
                out[str(key)] = "<redacted>"
            elif any(fragment in lower for fragment in _ACCOUNT_KEY_FRAGMENTS):
                out[str(key)] = _mask(item)
            else:
                out[str(key)] = _redact_payload(item)
        return out
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item) for item in value)
    return value


@dataclass(frozen=True)
class QuoteSnapshot:
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    mark: float | None
    close: float | None
    prev_close: float | None
    volume: float | None
    updated_at: str | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return None

    @property
    def execution_price(self) -> float | None:
        return self.mark or self.mid or self.last or self.close or self.prev_close


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    quantity: int
    order_type: str = "market"
    tif: str = "day"
    limit_price: float | None = None
    dry_run: bool = True
    order_action: str | None = None

    def normalized(self) -> "OrderIntent":
        symbol = self.symbol.upper().strip()
        side = self.side.lower().strip()
        order_type = self.order_type.lower().strip()
        tif = self.tif.lower().strip()
        order_action = self.order_action.lower().strip() if self.order_action else None
        if not symbol:
            raise ValueError("symbol is required")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if int(self.quantity) <= 0:
            raise ValueError("quantity must be greater than zero")
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        if tif not in {"day", "gtc"}:
            raise ValueError("tif must be day or gtc")
        if order_type == "limit" and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError("a positive limit_price is required for limit orders")
        if order_action and order_action not in ORDER_ACTIONS:
            raise ValueError("order_action must be one of: " + ", ".join(sorted(ORDER_ACTIONS)))
        if order_action and not order_action.startswith(side):
            raise ValueError("order_action must agree with side")
        return OrderIntent(
            symbol=symbol,
            side=side,
            quantity=int(self.quantity),
            order_type=order_type,
            tif=tif,
            limit_price=float(self.limit_price) if self.limit_price is not None else None,
            dry_run=bool(self.dry_run),
            order_action=order_action,
        )


class _PersistentLoop:
    """One background event loop shared by every SDK call in this process.

    The ``tastytrade>=13`` ``Session`` holds a long-lived ``httpx.AsyncClient``
    that binds to the event loop of its first request. A naive bridge that spins
    a fresh ``asyncio.run`` loop per call closes that loop and strands the client,
    so the *next* call dies with ``RuntimeError: Event loop is closed``. Keeping a
    single daemon loop alive for the process lifetime keeps the client valid
    across every balances / positions / order call.
    """

    _lock = threading.Lock()
    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get(cls) -> asyncio.AbstractEventLoop:
        with cls._lock:
            loop = cls._loop
            if loop is None or loop.is_closed():
                loop = asyncio.new_event_loop()
                threading.Thread(
                    target=loop.run_forever,
                    name="svyable-tasty-loop",
                    daemon=True,
                ).start()
                cls._loop = loop
            return loop


def _run(awaitable: Awaitable[T]) -> T:
    """Run one SDK coroutine on the shared persistent event loop.

    Works whether or not the caller is itself inside an event loop (Streamlit,
    Jupyter): the coroutine always executes on the dedicated background loop and
    the calling thread simply blocks on the result.
    """
    loop = _PersistentLoop.get()
    return asyncio.run_coroutine_threadsafe(awaitable, loop).result()


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _model_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return {
            key: _enum_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return {"value": str(value)}


def _load_bindings() -> SimpleNamespace:
    try:
        from tastytrade import Account, Session
        from tastytrade.instruments import Equity
        from tastytrade.market_data import get_market_data, get_market_data_by_type
        from tastytrade.order import (
            InstrumentType,
            LimitOrder,
            MarketOrder,
            OrderAction,
            OrderStatus,
            OrderTimeInForce,
        )
    except ImportError as exc:  # pragma: no cover - installation error
        raise RuntimeError(
            "Install the dashboard dependencies with `pip install -r requirements.txt`"
        ) from exc

    return SimpleNamespace(
        Account=Account,
        Session=Session,
        Equity=Equity,
        get_market_data=get_market_data,
        get_market_data_by_type=get_market_data_by_type,
        InstrumentType=InstrumentType,
        LimitOrder=LimitOrder,
        MarketOrder=MarketOrder,
        OrderAction=OrderAction,
        OrderStatus=OrderStatus,
        OrderTimeInForce=OrderTimeInForce,
    )


class TastySdkBroker:
    """BrokerConnector-compatible adapter around ``tastytrade>=13``."""

    def __init__(
        self,
        settings: TastySettings | None = None,
        *,
        bindings: Any | None = None,
        session: Any | None = None,
        account: Any | None = None,
    ) -> None:
        self.settings = settings or TastySettings.from_env()
        self.sdk = bindings or _load_bindings()
        self.session = session or self.sdk.Session(
            self.settings.client_secret,
            self.settings.refresh_token,
            is_test=self.settings.is_test,
        )
        self._account = account
        self._audit_path = Path(self.settings.audit_path)

    @property
    def account_number(self) -> str:
        return self.settings.account_number

    @property
    def masked_account(self) -> str:
        return _mask(self.settings.account_number)

    @property
    def environment(self) -> str:
        return self.settings.environment

    async def _get_account_async(self) -> Any:
        if self._account is None:
            self._account = await self.sdk.Account.get(
                self.session, self.settings.account_number
            )
        return self._account

    def validate_session(self) -> bool:
        """Report whether the session can make authenticated requests.

        tastytrade>=13 mints the OAuth bearer lazily, so ``validate`` returns
        False on a brand-new session until the first token refresh. We warm the
        token with ``refresh`` first so a healthy session never reports False on
        the initial call. Any auth failure surfaces here as ``False`` rather than
        crashing a status/health readout.
        """
        validate = getattr(self.session, "validate", None)
        if validate is None:
            return True
        try:
            refresh = getattr(self.session, "refresh", None)
            if asyncio.iscoroutinefunction(refresh):
                _run(refresh())
            if asyncio.iscoroutinefunction(validate):
                return bool(_run(validate()))
            result = validate()
            if asyncio.iscoroutine(result):
                return bool(_run(result))
            return bool(result)
        except Exception:  # noqa: BLE001 — a health check must not raise
            return False

    def _audit(self, event: str, payload: dict[str, Any]) -> None:
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "environment": self.environment,
            "account": self.masked_account,
            "payload": _redact_payload(payload),
        }
        self._audit_path.touch(exist_ok=True)
        try:
            os.chmod(self._audit_path, 0o600)
        except OSError:
            pass
        with self._audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")

    def _require_production_confirmation(self, confirmation: str, *, action: str) -> None:
        if self.settings.is_test:
            return
        if confirmation.strip() != self.settings.account_number:
            self._audit(
                f"{action}_blocked",
                {"reason": "missing_or_invalid_confirmation", "account": self.account_number},
            )
            raise RuntimeError(
                f"Production {action} requires the configured account number "
                "as the confirmation value."
            )

    # ------------------------------------------------------------------
    # Account and positions

    def get_account(self) -> dict[str, float]:
        async def fetch() -> dict[str, float]:
            account = await self._get_account_async()
            balance = await account.get_balances(self.session)
            return {
                "equity": float(balance.net_liquidating_value),
                "cash": float(balance.cash_balance),
                "buying_power": float(
                    balance.equity_buying_power or balance.derivative_buying_power
                ),
                "maintenance_excess": _float(balance.maintenance_excess) or 0.0,
            }

        return _run(fetch())

    def get_positions_frame(self) -> list[dict[str, Any]]:
        async def fetch() -> list[dict[str, Any]]:
            account = await self._get_account_async()
            positions = await account.get_positions(self.session, include_marks=True)
            rows: list[dict[str, Any]] = []
            for position in positions:
                instrument_type = _enum_value(position.instrument_type)
                qty = float(position.quantity)
                if str(_enum_value(position.quantity_direction)).lower() == "short":
                    qty = -qty
                mark = _float(
                    getattr(position, "mark", None)
                    or getattr(position, "mark_price", None)
                    or getattr(position, "close_price", None)
                )
                multiplier = _float(getattr(position, "multiplier", 1)) or 1.0
                rows.append(
                    {
                        "symbol": position.symbol,
                        "instrument_type": instrument_type,
                        "quantity": qty,
                        "mark": mark,
                        "market_value": qty * mark * multiplier if mark is not None else None,
                        "average_open_price": _float(
                            getattr(position, "average_open_price", None)
                        ),
                        "realized_today": _float(
                            getattr(position, "realized_today", None)
                        ),
                        "updated_at": str(getattr(position, "updated_at", "") or ""),
                    }
                )
            return rows

        return _run(fetch())

    def get_positions(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for row in self.get_positions_frame():
            if row["instrument_type"] != "Equity":
                continue
            qty = float(row["quantity"])
            if abs(qty) > 1e-9:
                out[row["symbol"]] = out.get(row["symbol"], 0.0) + qty
        return out

    def pnl_report(self) -> dict[str, Any]:
        account = self.get_account()
        positions: list[dict[str, Any]] = []
        total_value = 0.0
        total_unrealized = 0.0
        total_day = 0.0
        for row in self.get_positions_frame():
            if row["instrument_type"] != "Equity":
                continue
            qty = float(row.get("quantity") or 0.0)
            mark = _float(row.get("mark")) or 0.0
            value = row.get("market_value")
            if value is None:
                value = qty * mark
            avg_open = _float(row.get("average_open_price"))
            unrealized = (mark - avg_open) * qty if avg_open is not None else 0.0
            day = _float(row.get("realized_today")) or 0.0
            positions.append(
                {
                    "symbol": row["symbol"],
                    "qty": qty,
                    "mark": mark,
                    "avg_open": avg_open,
                    "unrealized": round(unrealized, 2),
                    "pl_day": round(day, 2),
                    "value": round(float(value or 0.0), 2),
                }
            )
            total_value += float(value or 0.0)
            total_unrealized += unrealized
            total_day += day
        return {
            "account": self.masked_account,
            "positions": sorted(positions, key=lambda x: -abs(float(x["value"]))),
            "total_position_value": round(total_value, 2),
            "cash_balance": round(float(account.get("cash", 0.0)), 2),
            "pending_cash": 0.0,
            "net_liq": round(float(account.get("equity", 0.0)), 2),
            "total_unrealized": round(total_unrealized, 2),
            "total_pl_day": round(total_day, 2),
        }

    # ------------------------------------------------------------------
    # Quotes

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        symbol = symbol.upper().strip()
        if not symbol:
            raise ValueError("symbol is required")

        async def fetch() -> QuoteSnapshot:
            data = await self.sdk.get_market_data(
                self.session, symbol, self.sdk.InstrumentType.EQUITY
            )
            return self._quote_from_model(data)

        return _run(fetch())

    def get_market_snapshot(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        clean = sorted({str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()})
        if not clean:
            return {}

        async def fetch() -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for start in range(0, len(clean), 90):
                models = await self.sdk.get_market_data_by_type(
                    self.session, equities=clean[start : start + 90]
                )
                for model in models:
                    quote = self._quote_from_model(model)
                    out[quote.symbol] = asdict(quote) | {"mid": quote.mid}
            return out

        return _run(fetch())

    @staticmethod
    def _quote_from_model(data: Any) -> QuoteSnapshot:
        return QuoteSnapshot(
            symbol=str(data.symbol),
            bid=_float(getattr(data, "bid", None)),
            ask=_float(getattr(data, "ask", None)),
            last=_float(getattr(data, "last", None)),
            mark=_float(getattr(data, "mark", None)),
            close=_float(getattr(data, "close", None)),
            prev_close=_float(getattr(data, "prev_close", None)),
            volume=_float(getattr(data, "volume", None)),
            updated_at=str(getattr(data, "updated_at", "") or ""),
        )

    def execution_prices(self, symbols: list[str]) -> dict[str, float]:
        snapshot = self.get_market_snapshot(symbols)
        out: dict[str, float] = {}
        for symbol, quote in snapshot.items():
            price = (
                quote.get("mark")
                or quote.get("mid")
                or quote.get("last")
                or quote.get("close")
                or quote.get("prev_close")
            )
            if price and float(price) > 0:
                out[symbol] = float(price)
        return out

    # ------------------------------------------------------------------
    # Orders

    def _action_for_intent(self, intent: OrderIntent) -> Any:
        action = intent.order_action or (
            "buy_to_open" if intent.side == "buy" else "sell_to_close"
        )
        enum_name = action.upper()
        member = getattr(self.sdk.OrderAction, enum_name, None)
        if member is None:
            raise RuntimeError(f"Installed tastytrade SDK lacks OrderAction.{enum_name}")
        return member

    async def _build_order_async(self, intent: OrderIntent) -> Any:
        intent = intent.normalized()
        equity = await self.sdk.Equity.get(self.session, intent.symbol)
        if isinstance(equity, list):
            equity = equity[0]
        leg = equity.build_leg(intent.quantity, self._action_for_intent(intent))
        tif = (
            self.sdk.OrderTimeInForce.DAY
            if intent.tif == "day"
            else self.sdk.OrderTimeInForce.GTC
        )
        if intent.order_type == "market":
            return self.sdk.MarketOrder(time_in_force=tif, legs=[leg])
        # tastytrade uses negative prices for debits, positive for credits.
        signed = (
            -abs(intent.limit_price or 0)
            if intent.side == "buy"
            else abs(intent.limit_price or 0)
        )
        return self.sdk.LimitOrder(
            time_in_force=tif,
            legs=[leg],
            price=Decimal(str(round(signed, 4))),
        )

    def build_equity_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        order_type: str = "market",
        tif: str = "day",
        price: float | None = None,
        order_action: str | None = None,
    ) -> Any:
        return _run(
            self._build_order_async(
                OrderIntent(
                    symbol=symbol,
                    side=side,
                    quantity=int(qty),
                    order_type=order_type,
                    tif=tif,
                    limit_price=price,
                    dry_run=True,
                    order_action=order_action,
                )
            )
        )

    async def _preflight_async(self, intent: OrderIntent) -> dict[str, Any]:
        intent = intent.normalized()
        account = await self._get_account_async()
        order = await self._build_order_async(intent)
        response = await account.place_order(self.session, order, dry_run=True)
        warnings = [_model_dict(item) for item in (getattr(response, "warnings", None) or [])]
        errors = [_model_dict(item) for item in (getattr(response, "errors", None) or [])]
        buying_power = _model_dict(getattr(response, "buying_power_effect", None))
        fees = _model_dict(getattr(response, "fee_calculation", None))
        return {
            "status": "PASS" if not warnings and not errors else "BLOCKED",
            "intent": asdict(intent),
            "warnings": warnings,
            "errors": errors,
            "buying_power_effect": buying_power,
            "fees": fees,
            "order": _model_dict(getattr(response, "order", None)),
        }

    def preflight(self, intent: OrderIntent) -> dict[str, Any]:
        intent = intent.normalized()
        self._audit("order_intent", asdict(intent))
        try:
            result = _run(self._preflight_async(intent))
        except Exception as exc:
            self._audit("order_preflight_error", {"intent": asdict(intent), "error": str(exc)})
            raise
        self._audit("order_preflight", result)
        return result

    def submit_intent(
        self, intent: OrderIntent, *, confirmation: str = ""
    ) -> dict[str, Any]:
        intent = intent.normalized()
        preflight = self.preflight(intent)
        if intent.dry_run:
            return {
                **preflight,
                "status": "DRY_RUN",
                "message": "Preflight completed; no order submitted.",
            }
        if preflight["warnings"] or preflight["errors"]:
            return {
                **preflight,
                "status": "REJECTED_PREFLIGHT",
                "message": "Broker preflight returned warnings or errors; nothing submitted.",
            }
        if not self.settings.is_test and not self.settings.live_enabled:
            self._audit("order_submission_blocked", {"reason": "live_not_enabled", "intent": asdict(intent)})
            raise RuntimeError(
                "Production submission is disabled. Set SVYABLE_ENABLE_LIVE=true "
                "only after the production gates are satisfied."
            )
        self._require_production_confirmation(confirmation, action="submission")

        async def submit() -> dict[str, Any]:
            account = await self._get_account_async()
            order = await self._build_order_async(intent)
            response = await account.place_order(self.session, order, dry_run=False)
            placed = getattr(response, "order", None)
            result = {
                "status": str(_enum_value(getattr(placed, "status", "submitted"))),
                "id": getattr(placed, "id", None),
                "symbol": intent.symbol,
                "side": intent.side,
                "quantity": intent.quantity,
                "qty": intent.quantity,
                "order_type": intent.order_type,
                "order_action": intent.order_action,
                "limit_price": intent.limit_price,
                "fees": _model_dict(getattr(response, "fee_calculation", None)),
                "buying_power_effect": _model_dict(
                    getattr(response, "buying_power_effect", None)
                ),
                "warnings": [
                    _model_dict(item)
                    for item in (getattr(response, "warnings", None) or [])
                ],
                "errors": [
                    _model_dict(item)
                    for item in (getattr(response, "errors", None) or [])
                ],
            }
            return result

        try:
            result = _run(submit())
        except Exception as exc:
            self._audit("order_submission_error", {"intent": asdict(intent), "error": str(exc)})
            raise
        self._audit("order_response", result)
        return result

    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "market",
        tif: str = "day",
        price: float | None = None,
    ) -> dict[str, Any]:
        """BrokerConnector compatibility method for test/sandbox callers only.

        Production must use ``submit_intent(..., confirmation=account_number)`` so
        the live confirmation gate cannot be bypassed by a generic protocol call.
        """
        if not self.settings.is_test:
            raise RuntimeError(
                "Use submit_intent(..., confirmation=<account_number>) for production."
            )
        return self.submit_intent(
            OrderIntent(
                symbol=symbol,
                side=side,
                quantity=int(qty),
                order_type=order_type,
                tif=tif,
                limit_price=price,
                dry_run=False,
            )
        )

    def get_order(self, order_id: int) -> dict[str, Any]:
        order_id = int(order_id)
        if order_id <= 0:
            raise ValueError("order_id must be positive")

        async def fetch() -> dict[str, Any]:
            account = await self._get_account_async()
            order = await account.get_order(self.session, order_id)
            return self._order_dict(order)

        return _run(fetch())

    def search_orders(
        self,
        *,
        start_date: str | None = None,
        status: list[str] | None = None,
        per_page: int = 50,
    ) -> list[dict[str, Any]]:
        per_page = max(1, min(int(per_page), 250))

        async def fetch() -> list[dict[str, Any]]:
            account = await self._get_account_async()
            statuses = None
            if status:
                statuses = []
                for name in status:
                    enum_name = name.upper().replace(" ", "_")
                    member = getattr(self.sdk.OrderStatus, enum_name, None)
                    if member is not None:
                        statuses.append(member)
            orders = await account.get_order_history(
                self.session,
                per_page=per_page,
                page_offset=0,
                start_date=date.fromisoformat(start_date) if start_date else None,
                statuses=statuses or None,
                sort="Desc",
            )
            return [self._order_dict(order) for order in orders]

        return _run(fetch())

    def cancel_order(self, order_id: int, *, confirmation: str = "") -> dict[str, Any]:
        order_id = int(order_id)
        if order_id <= 0:
            raise ValueError("order_id must be positive")
        self._require_production_confirmation(confirmation, action="cancel")

        async def cancel() -> dict[str, Any]:
            account = await self._get_account_async()
            await account.delete_order(self.session, order_id)
            return {"id": order_id, "status": "Cancel Requested"}

        try:
            result = _run(cancel())
        except Exception as exc:
            self._audit("order_cancel_error", {"id": order_id, "error": str(exc)})
            raise
        self._audit("order_cancel", result)
        return result

    def poll_order(
        self, order_id: int, *, timeout_s: float = 120.0, interval_s: float = 5.0
    ) -> dict[str, Any]:
        import time

        order_id = int(order_id)
        if order_id <= 0:
            raise ValueError("order_id must be positive")
        timeout_s = max(0.0, float(timeout_s))
        interval_s = max(0.5, float(interval_s))
        started = time.monotonic()
        while True:
            order = self.get_order(order_id)
            if order.get("status") in TERMINAL_ORDER_STATUSES:
                return order
            if time.monotonic() - started >= timeout_s:
                return order
            time.sleep(interval_s)

    @staticmethod
    def _order_dict(order: Any) -> dict[str, Any]:
        return {
            "id": getattr(order, "id", None),
            "status": str(_enum_value(getattr(order, "status", ""))),
            "underlying_symbol": getattr(order, "underlying_symbol", ""),
            "order_type": str(_enum_value(getattr(order, "order_type", ""))),
            "time_in_force": str(_enum_value(getattr(order, "time_in_force", ""))),
            "size": _float(getattr(order, "size", None)),
            "price": _float(getattr(order, "price", None)),
            "cancellable": bool(getattr(order, "cancellable", False)),
            "editable": bool(getattr(order, "editable", False)),
            "updated_at": str(getattr(order, "updated_at", "") or ""),
        }

    def status_snapshot(self) -> dict[str, Any]:
        today = datetime.now().date().isoformat()
        return {
            "environment": self.environment,
            "sdk": "tastytrade>=13",
            "session_valid": self.validate_session(),
            "account": self.masked_account,
            "balances": self.get_account(),
            "positions": self.get_positions_frame(),
            "orders_today": self.search_orders(start_date=today),
        }
