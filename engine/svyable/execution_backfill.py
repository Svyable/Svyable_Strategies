"""Late-fill recovery and slippage escalation for dashboard execution."""

from __future__ import annotations

from typing import Any

import pandas as pd

from svyable.execution_quality import execution_summary, fetch_order_fills, score_fills
from svyable.ledger import Ledger
from svyable.rebalancer import PlannedOrder
from svyable.submission_guard import SubmissionGuardMixin


class ExecutionBackfillMixin(SubmissionGuardMixin):
    """Composes guard, backfill, and execution controls through normal Python MRO."""

    def _record_slippage_event(
        self,
        ledger: Ledger,
        quality: dict[str, Any],
        *,
        source: str,
    ) -> None:
        worst = quality.get("worst_slippage_bps")
        if worst is None:
            return
        worst = float(worst)
        if quality.get("synthetic_fills") or self.settings.is_test:
            # Sandbox fill prices are simulator artifacts; keep the audit trail
            # without paging anyone or polluting slippage statistics.
            ledger.record_event(
                "info",
                source,
                f"Sandbox synthetic fills: worst signed slippage {worst:.2f} bps "
                "(cert-environment simulator prices; excluded from escalation).",
            )
            return
        if worst >= self.settings.slippage_critical_bps:
            level = "critical"
        elif worst >= self.settings.slippage_warn_bps:
            level = "warning"
        else:
            return
        ledger.record_event(
            level,
            source,
            f"Worst signed slippage {worst:.2f} bps; "
            f"warning={self.settings.slippage_warn_bps:.2f}, "
            f"critical={self.settings.slippage_critical_bps:.2f}",
        )

    def _record_submission(
        self,
        plan: dict[str, Any],
        orders: list[PlannedOrder],
        results: list[dict[str, Any]],
        fills: list[dict[str, Any]],
        quality: dict[str, Any],
        account: dict[str, Any],
        rec: dict[str, Any],
        status: str,
    ) -> None:
        super()._record_submission(
            plan, orders, results, fills, quality, account, rec, status
        )
        ledger = Ledger(self.ledger_path)
        try:
            self._record_slippage_event(
                ledger, quality, source="execution_quality"
            )
            if results and not fills and not quality.get("error"):
                ledger.record_event(
                    "info",
                    "execution_quality",
                    "No trade transactions available yet; recent orders remain eligible "
                    "for idempotent fill backfill.",
                )
        finally:
            ledger.close()

    def backfill_execution_quality(self, since_days: int = 5) -> dict[str, Any]:
        """Re-query recent broker order IDs and insert newly visible transactions."""
        since_days = max(1, min(int(since_days), 30))
        ledger = Ledger(self.ledger_path)
        try:
            orders = pd.read_sql_query(
                "SELECT run_id, broker_order_id, symbol, side, qty, est_price, ts "
                "FROM orders WHERE broker_order_id IS NOT NULL "
                "AND ts >= datetime('now', ?) ORDER BY id",
                ledger.con,
                params=(f"-{since_days} days",),
            )
            if orders.empty:
                return {
                    "status": "no_orders",
                    "orders_checked": 0,
                    "fills_found": 0,
                    "fills_recorded": 0,
                    "execution_quality": execution_summary([]),
                }

            order_ids = sorted({int(value) for value in orders["broker_order_id"]})
            start_date = str(pd.to_datetime(orders["ts"]).min().date())
            raw_fills = fetch_order_fills(
                self.broker, order_ids, start_date=start_date
            )
            fills = score_fills(raw_fills, orders.to_dict(orient="records"))
            existing_ids = {
                int(row[0])
                for row in ledger.con.execute(
                    "SELECT transaction_id FROM fills WHERE transaction_id IS NOT NULL"
                )
            }
            new_fills = [
                fill
                for fill in fills
                if fill.get("transaction_id") is not None
                and int(fill["transaction_id"]) not in existing_ids
            ]

            run_by_order = {
                int(row.broker_order_id): int(row.run_id)
                for row in orders.itertuples()
            }
            for run_id in sorted(set(run_by_order.values())):
                run_fills = [
                    fill
                    for fill in new_fills
                    if run_by_order.get(int(fill["order_id"])) == run_id
                ]
                if run_fills:
                    ledger.record_fills(run_id, "tastytrade-sdk", run_fills)

            quality = execution_summary(new_fills)
            ledger.record_event(
                "info",
                "execution_quality",
                f"Backfill checked {len(order_ids)} broker orders, found "
                f"{len(fills)} transactions, and recorded {len(new_fills)} new rows.",
            )
            if new_fills:
                self._record_slippage_event(
                    ledger, quality, source="execution_quality_backfill"
                )
            return {
                "status": "ok",
                "orders_checked": len(order_ids),
                "fills_found": len(fills),
                "fills_recorded": len(new_fills),
                "execution_quality": quality,
                "fills": new_fills,
            }
        finally:
            ledger.close()
