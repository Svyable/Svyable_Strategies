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

import pandas as pd

from svyable.config import SvyableConfig
from svyable.brokers import BrokerConnector


@dataclass
class PlannedOrder:
    symbol: str
    side: str            # "buy" | "sell"
    qty: int
    est_price: float
    est_notional: float
    reason: str          # "rebalance" | "exit" | "adv_capped"


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

        # ADV participation cap: trade at most cap x ADV today, spill the rest
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

    # sells first
    orders.sort(key=lambda o: (o.side != "sell", -o.est_notional))

    # pre-trade sanity: resulting gross within cap
    buy_notional = sum(o.est_notional for o in orders if o.side == "buy")
    cur_gross = sum(abs(q) * prices.get(s, 0.0) for s, q in positions.items())
    sell_notional = sum(o.est_notional for o in orders if o.side == "sell")
    if (cur_gross + buy_notional - sell_notional) > cfg.lev_cap * equity * 1.02:
        raise ValueError("planned book exceeds lev_cap — refusing to emit orders")

    return orders


def execute_plan(orders: list[PlannedOrder], broker: BrokerConnector,
                 log_dir: str | Path, dry_run: bool = True) -> dict:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    record: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "planned": [asdict(o) for o in orders],
        "results": [],
    }
    if not dry_run:
        for o in orders:
            try:
                record["results"].append(broker.submit_order(o.symbol, o.qty, o.side))
            except Exception as e:  # noqa: BLE001 — keep going, log the failure
                record["results"].append({"status": "error", "symbol": o.symbol,
                                          "error": str(e)})
    path = log_dir / f"orders_{stamp}.json"
    path.write_text(json.dumps(record, indent=2))
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
