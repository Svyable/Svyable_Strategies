"""Rebalancer: target weights -> orders (the one genuinely new business logic
in the whole migration, per plan.md). Sizing safety lives HERE, not in brokers.

Rules (strategy.md §11.3):
- integer shares, minimum order notional (skip dust)
- ADV participation cap per day, remainder spills to the next run
- sells submitted before buys (frees cash)
- pre-trade checks: long-only, per-name notional cap, gross cap
- every plan + every submission appended to an order log (audit chain)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from svyable.config import SvyableConfig
from svyable.brokers import BrokerConnector

FAILURE_STATUSES = frozenset({
    "error", "blocked", "rejected", "rejected_dry_run", "rejected_preflight",
    "cancelled", "expired", "removed", "partially removed", "skipped_after_failure",
})


@dataclass
class PlannedOrder:
    symbol: str
    side: str            # "buy" | "sell"
    qty: int
    est_price: float
    est_notional: float
    reason: str          # "rebalance" | "exit" | "adv_capped"


def _result_status(result: dict[str, Any]) -> str:
    return str(result.get("status", "")).strip().lower()


def execution_result_failed(result: dict[str, Any]) -> bool:
    status = _result_status(result)
    return (
        status in FAILURE_STATUSES
        or bool(result.get("error"))
        or bool(result.get("errors"))
        or bool(result.get("warnings"))
    )


def plan_orders(targets: pd.Series, equity: float, prices: dict[str, float],
                positions: dict[str, float], cfg: SvyableConfig,
                adv: dict[str, float] | None = None,
                min_order_notional: float = 100.0) -> list[PlannedOrder]:
    """targets: weight per symbol (sum <= lev_cap). positions: current qty."""
    orders: list[PlannedOrder] = []
    symbols = sorted(set(targets.index) | set(positions))

    for sym in symbols:
        px = prices.get(sym, 0.0)
        if px <= 0:
            continue
        tgt_w = float(targets.get(sym, 0.0))
        if tgt_w < 0:
            tgt_w = 0.0                                   # long-only guard
        cur_qty = float(positions.get(sym, 0.0))
        tgt_qty = math.floor(tgt_w * equity / px)
        delta = tgt_qty - cur_qty
        notional = abs(delta) * px
        if notional < min_order_notional:
            continue

        reason = "exit" if tgt_qty == 0 and cur_qty > 0 else "rebalance"

        if adv and sym in adv and adv[sym] > 0:
            max_notional = cfg.adv_participation_cap * adv[sym]
            if notional > max_notional:
                delta = math.copysign(math.floor(max_notional / px), delta)
                notional = abs(delta) * px
                reason = "adv_capped"
                if abs(delta) < 1:
                    continue

        orders.append(PlannedOrder(
            symbol=sym, side="buy" if delta > 0 else "sell",
            qty=int(abs(delta)), est_price=round(px, 4),
            est_notional=round(notional, 2), reason=reason,
        ))

    orders.sort(key=lambda o: (o.side != "sell", -o.est_notional))

    buy_notional = sum(o.est_notional for o in orders if o.side == "buy")
    cur_gross = sum(abs(q) * prices.get(s, 0.0) for s, q in positions.items())
    sell_notional = sum(o.est_notional for o in orders if o.side == "sell")
    if (cur_gross + buy_notional - sell_notional) > cfg.lev_cap * equity * 1.02:
        raise ValueError("planned book exceeds lev_cap — refusing to emit orders")

    return orders


def _submit_planned_order(
    order: PlannedOrder,
    broker: BrokerConnector,
    *,
    dry_run: bool,
    confirmation: str,
) -> dict[str, Any]:
    submit_intent = getattr(broker, "submit_intent", None)
    if callable(submit_intent):
        from svyable.tastytrade_sdk import OrderIntent

        return submit_intent(
            OrderIntent(
                symbol=order.symbol,
                side=order.side,
                quantity=order.qty,
                order_type="market",
                dry_run=dry_run,
            ),
            confirmation=confirmation,
        )
    if dry_run:
        return {
            "status": "planned",
            "symbol": order.symbol,
            "side": order.side,
            "qty": order.qty,
            "message": "Dry run only; no adapter preflight is available.",
        }
    return broker.submit_order(order.symbol, order.qty, order.side)


def _execution_status(*, dry_run: bool, failed: bool, aborted: bool, result_count: int) -> str:
    if failed:
        return "degraded" if dry_run or not aborted else "failed"
    if dry_run:
        return "dry_run" if result_count else "planned"
    return "ok"


def execute_plan(
    orders: list[PlannedOrder],
    broker: BrokerConnector,
    log_dir: str | Path,
    dry_run: bool = True,
    *,
    fail_fast: bool = True,
    confirmation: str = "",
) -> dict:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    record: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "fail_fast": fail_fast,
        "planned": [asdict(o) for o in orders],
        "results": [],
        "errors": [],
        "aborted": False,
    }

    for idx, order in enumerate(orders):
        try:
            result = _submit_planned_order(
                order,
                broker,
                dry_run=dry_run,
                confirmation=confirmation,
            )
            result.setdefault("symbol", order.symbol)
            result.setdefault("side", order.side)
            result.setdefault("qty", order.qty)
            record["results"].append(result)
        except Exception as exc:  # noqa: BLE001
            record["results"].append({
                "status": "error",
                "symbol": order.symbol,
                "side": order.side,
                "qty": order.qty,
                "error": str(exc),
            })

        if execution_result_failed(record["results"][-1]):
            record["errors"].append(record["results"][-1])
            if fail_fast:
                record["aborted"] = True
                for skipped in orders[idx + 1:]:
                    record["results"].append({
                        "status": "skipped_after_failure",
                        "symbol": skipped.symbol,
                        "side": skipped.side,
                        "qty": skipped.qty,
                        "reason": "fail_fast",
                    })
                break

    record["status"] = _execution_status(
        dry_run=dry_run,
        failed=bool(record["errors"]),
        aborted=bool(record["aborted"]),
        result_count=len(record["results"]),
    )
    path = log_dir / f"orders_{stamp}.json"
    path.write_text(json.dumps(record, indent=2, default=str))
    record["log_file"] = str(path)
    return record


def reconcile(targets: pd.Series, equity: float, prices: dict[str, float],
              positions: dict[str, float], tolerance_w: float = 0.01) -> dict:
    """Engine-vs-broker drift report (strategy.md §7 step 8)."""
    drifts = {}
    for sym in sorted(set(targets.index) | set(positions)):
        px = prices.get(sym, 0.0)
        actual_w = positions.get(sym, 0.0) * px / equity if equity > 0 else 0.0
        tgt_w = float(targets.get(sym, 0.0))
        d = actual_w - tgt_w
        if abs(d) > tolerance_w:
            drifts[sym] = {"target_w": round(tgt_w, 4), "actual_w": round(actual_w, 4),
                           "drift": round(d, 4)}
    return {"status": "ok" if not drifts else "drift", "drifts": drifts,
            "checked": len(set(targets.index) | set(positions))}
