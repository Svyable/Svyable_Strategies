"""Normalize Tastytrade trade transactions and calculate execution slippage."""

from __future__ import annotations

import asyncio
import threading
from datetime import date
from typing import Any, Awaitable, TypeVar

T = TypeVar("T")


def _run(awaitable: Awaitable[T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: list[T] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def fetch_order_fills(
    broker: Any,
    order_ids: list[int],
    *,
    start_date: str,
) -> list[dict[str, Any]]:
    """Fetch equity trade transactions for a known set of broker order IDs."""
    wanted = {int(order_id) for order_id in order_ids}
    if not wanted:
        return []

    async def fetch() -> list[dict[str, Any]]:
        account = await broker._get_account_async()
        history = await account.get_history(
            broker.session,
            per_page=250,
            page_offset=0,
            sort="Desc",
            type="Trade",
            start_date=date.fromisoformat(start_date),
            instrument_type=broker.sdk.InstrumentType.EQUITY,
        )
        rows: list[dict[str, Any]] = []
        for tx in history:
            order_id = getattr(tx, "order_id", None)
            if order_id is None or int(order_id) not in wanted:
                continue
            action = str(_enum_value(getattr(tx, "action", "")))
            side = "buy" if action.lower().startswith("buy") else "sell"
            fee_fields = (
                "commission",
                "regulatory_fees",
                "clearing_fees",
                "proprietary_index_option_fees",
                "other_charge",
            )
            fees = sum(abs(_float(getattr(tx, name, None)) or 0.0) for name in fee_fields)
            rows.append(
                {
                    "transaction_id": getattr(tx, "id", None),
                    "order_id": int(order_id),
                    "symbol": getattr(tx, "symbol", None)
                    or getattr(tx, "underlying_symbol", None),
                    "side": side,
                    "quantity": abs(_float(getattr(tx, "quantity", None)) or 0.0),
                    "fill_price": _float(getattr(tx, "price", None)),
                    "fees": round(fees, 6),
                    "executed_at": str(getattr(tx, "executed_at", "") or ""),
                    "venue": getattr(tx, "destination_venue", None)
                    or getattr(tx, "exchange", None),
                    "exec_id": getattr(tx, "exec_id", None),
                }
            )
        return rows

    return _run(fetch())


def score_fills(
    fills: list[dict[str, Any]],
    planned_orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Signed slippage: positive is worse for both buys and sells."""
    references = {
        (str(order["symbol"]), str(order["side"]).lower()): float(order["est_price"])
        for order in planned_orders
        if float(order.get("est_price") or 0.0) > 0
    }
    scored: list[dict[str, Any]] = []
    for fill in fills:
        side = str(fill.get("side", "")).lower()
        reference = references.get((str(fill.get("symbol")), side))
        fill_price = _float(fill.get("fill_price"))
        slippage = None
        if reference and fill_price and fill_price > 0:
            raw_bps = (fill_price / reference - 1.0) * 1e4
            slippage = raw_bps if side == "buy" else -raw_bps
        scored.append(
            {
                **fill,
                "reference_price": reference,
                "slippage_bps": round(slippage, 3) if slippage is not None else None,
            }
        )
    return scored


def execution_summary(fills: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        float(row["slippage_bps"])
        for row in fills
        if row.get("slippage_bps") is not None
    ]
    fees = sum(float(row.get("fees") or 0.0) for row in fills)
    notional = sum(
        float(row.get("quantity") or 0.0) * float(row.get("fill_price") or 0.0)
        for row in fills
    )
    return {
        "fills": len(fills),
        "notional": round(notional, 2),
        "fees": round(fees, 6),
        "mean_slippage_bps": round(sum(scored) / len(scored), 3) if scored else None,
        "mean_abs_slippage_bps": round(sum(abs(x) for x in scored) / len(scored), 3)
        if scored else None,
        "worst_slippage_bps": round(max(scored), 3) if scored else None,
    }
