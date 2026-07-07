"""Execution controls shared by the Streamlit dashboard service.

This mixin requires the host service to provide ``strategy_snapshot``,
``target_series``, ``broker``, ``settings``, ``ledger_path`` and ``strategy_id``.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

import pandas as pd

from svyable.calendar import expected_last_close
from svyable.config import nasdaq_lo_config
from svyable.execution_quality import execution_summary, fetch_order_fills, score_fills
from svyable.ledger import Ledger
from svyable.rebalancer import PlannedOrder, plan_orders, reconcile
from svyable.tastytrade_sdk import OrderIntent


class ExecutionControlMixin:
    def execution_inputs(self) -> dict[str, Any]:
        snapshot = self.strategy_snapshot()
        frame = snapshot.get("execution_inputs", pd.DataFrame()).copy()
        if frame.empty:
            raise FileNotFoundError(
                "No execution_inputs.csv artifact found. Run the updated "
                "`svyable daily` before dashboard rebalance."
            )
        required = {"price", "adv_dollars", "is_liquid"}
        missing_columns = sorted(required - set(frame.columns))
        if missing_columns:
            raise ValueError(
                "Execution artifact is missing columns: " + ", ".join(missing_columns)
            )
        frame.index = frame.index.astype(str)
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
        frame["adv_dollars"] = pd.to_numeric(frame["adv_dollars"], errors="coerce")
        frame["is_liquid"] = frame["is_liquid"].astype(str).str.lower().isin(
            {"true", "1", "yes"}
        )
        meta = snapshot.get("meta", {}).get("execution_inputs") or {}
        artifact_date = str(
            meta.get("date")
            or (snapshot.get("meta", {}).get("data") or {}).get("last_date")
            or ""
        )
        expected = str(expected_last_close(date.today()))
        return {
            "frame": frame,
            "artifact_date": artifact_date,
            "expected_date": expected,
            "stale": not artifact_date or artifact_date < expected,
            "meta": meta,
        }

    def build_rebalance_plan(
        self, *, min_order_notional: float = 100.0
    ) -> dict[str, Any]:
        targets = self.target_series()
        execution = self.execution_inputs()
        inputs = execution["frame"]
        account = self.broker.get_account()
        positions = self.broker.get_positions()
        symbols = sorted(set(targets.index) | set(positions))
        prices = self.broker.execution_prices(symbols)
        adv = inputs["adv_dollars"].dropna().astype(float).to_dict()
        missing_prices = sorted(set(symbols) - set(prices))
        missing_adv = sorted(set(symbols) - set(adv))
        non_liquid_targets = sorted(
            symbol
            for symbol, weight in targets.items()
            if float(weight) > 0
            and (symbol not in inputs.index or not bool(inputs.at[symbol, "is_liquid"]))
        )
        if non_liquid_targets:
            raise ValueError(
                "Positive targets fail the persisted liquidity mask: "
                + ", ".join(non_liquid_targets)
            )

        cfg = nasdaq_lo_config()
        orders = plan_orders(
            targets,
            account["equity"],
            prices,
            positions,
            cfg,
            adv=adv,
            min_order_notional=min_order_notional,
        )
        safety_complete = not (
            execution["stale"] or missing_prices or missing_adv or non_liquid_targets
        )
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "execution_inputs_date": execution["artifact_date"],
            "expected_inputs_date": execution["expected_date"],
            "inputs_stale": execution["stale"],
            "adv_window": int(execution["meta"].get("adv_window", cfg.adv_win)),
            "adv_participation_cap": float(
                execution["meta"].get(
                    "adv_participation_cap", cfg.adv_participation_cap
                )
            ),
            "account": account,
            "positions": positions,
            "targets": targets.to_dict(),
            "prices": prices,
            "adv": {symbol: adv[symbol] for symbol in symbols if symbol in adv},
            "missing_prices": missing_prices,
            "missing_adv": missing_adv,
            "non_liquid_targets": non_liquid_targets,
            "orders": [asdict(order) for order in orders],
            "adv_capped_orders": sum(order.reason == "adv_capped" for order in orders),
            "estimated_turnover": sum(order.est_notional for order in orders),
            "safety_complete": safety_complete,
        }

    def preflight_plan(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        if not plan.get("safety_complete"):
            raise RuntimeError(
                "Plan safety checks are incomplete; refresh daily artifacts and quotes."
            )
        return [
            self.broker.preflight(
                OrderIntent(
                    symbol=row["symbol"],
                    side=row["side"],
                    quantity=int(row["qty"]),
                    order_type="market",
                    dry_run=True,
                )
            )
            for row in plan.get("orders", [])
        ]

    def submit_plan(
        self, plan: dict[str, Any], *, confirmation: str
    ) -> dict[str, Any]:
        if not plan.get("safety_complete"):
            raise RuntimeError("Refusing to submit an incomplete or stale order plan.")
        if not self.settings.is_test:
            raise RuntimeError(
                "Production bulk submission from Streamlit remains disabled."
            )
        orders = [PlannedOrder(**row) for row in plan.get("orders", [])]
        submitted = [
            self.broker.submit_intent(
                OrderIntent(
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.qty,
                    order_type="market",
                    dry_run=False,
                ),
                confirmation=confirmation,
            )
            for order in orders
        ]

        final_orders: list[dict[str, Any]] = []
        for order, result in zip(orders, submitted):
            order_id = result.get("id")
            if order_id is None:
                final_orders.append(result)
                continue
            try:
                final = self.broker.poll_order(
                    int(order_id), timeout_s=30.0, interval_s=2.0
                )
                final_orders.append(
                    {"symbol": order.symbol, "side": order.side, **result, **final}
                )
            except Exception as exc:
                final_orders.append(
                    {**result, "symbol": order.symbol, "poll_error": str(exc)}
                )

        order_ids = [int(row["id"]) for row in submitted if row.get("id") is not None]
        fills: list[dict[str, Any]] = []
        quality: dict[str, Any]
        try:
            raw_fills = fetch_order_fills(
                self.broker,
                order_ids,
                start_date=plan.get("execution_inputs_date") or str(date.today()),
            )
            fills = score_fills(raw_fills, [asdict(order) for order in orders])
            quality = execution_summary(fills)
            # Cert-environment fills are synthetic (market orders fill at $1,
            # limits < $3 fill instantly); their slippage numbers must never be
            # read as execution quality or feed cost calibration.
            quality["synthetic_fills"] = bool(self.settings.is_test)
        except Exception as exc:
            quality = {
                "fills": 0,
                "notional": 0.0,
                "fees": 0.0,
                "mean_slippage_bps": None,
                "mean_abs_slippage_bps": None,
                "worst_slippage_bps": None,
                "error": str(exc),
            }

        account = self.broker.get_account()
        positions = self.broker.get_positions()
        fresh_prices = self.broker.execution_prices(
            sorted(set(plan["targets"]) | set(positions))
        )
        prices = {**plan["prices"], **fresh_prices}
        rec = reconcile(
            pd.Series(plan["targets"], dtype=float),
            account["equity"],
            prices,
            positions,
        )
        bad_statuses = {"error", "rejected", "rejected_preflight", "blocked"}
        status = "ok" if (
            rec["status"] == "ok"
            and all(
                str(item.get("status", "")).lower() not in bad_statuses
                for item in final_orders
            )
        ) else "degraded"
        self._record_submission(
            plan, orders, final_orders, fills, quality, account, rec, status
        )
        return {
            "status": status,
            "submitted": len(submitted),
            "orders": final_orders,
            "fills": fills,
            "execution_quality": quality,
            "account": account,
            "positions": positions,
            "reconciliation": rec,
        }

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
        ledger = Ledger(self.ledger_path)
        try:
            run_id = ledger.record_run(
                kind="rebalance",
                strategy=self.strategy_id,
                status=status,
                data_last_date=plan.get("execution_inputs_date", ""),
                data_status="ok" if plan.get("safety_complete") else "degraded",
                metrics={
                    "orders": len(orders),
                    "adv_capped_orders": plan.get("adv_capped_orders", 0),
                    "broker": "tastytrade-sdk",
                    "environment": self.settings.environment,
                    "execution_quality": quality,
                    "reconciliation": rec,
                },
            )
            ledger.record_orders(
                run_id,
                "tastytrade-sdk",
                False,
                [asdict(order) for order in orders],
                results,
            )
            if fills:
                ledger.record_fills(run_id, "tastytrade-sdk", fills)
            ledger.record_equity(
                plan.get("execution_inputs_date") or str(date.today()),
                paper_equity=account["equity"],
                note="Streamlit Tastytrade post-order snapshot",
            )
            ledger.record_event(
                "info" if status == "ok" else "warning",
                "streamlit",
                f"Submitted {len(orders)} orders; status={status}; "
                f"reconciliation={rec['status']}; fills={quality.get('fills', 0)}",
            )
            if quality.get("error"):
                ledger.record_event(
                    "warning", "execution_quality", str(quality["error"])
                )
            if rec["status"] != "ok":
                ledger.record_event(
                    "warning", "reconcile", json.dumps(rec["drifts"], sort_keys=True)
                )
        finally:
            ledger.close()

    def order_status(self, order_id: int) -> dict[str, Any]:
        return self.broker.get_order(int(order_id))

    def cancel_order(self, order_id: int, *, confirmation: str = "") -> dict[str, Any]:
        if not self.settings.is_test and confirmation.strip() != self.settings.account_number:
            raise RuntimeError(
                "Production cancellation requires the configured account number."
            )
        result = self.broker.cancel_order(int(order_id), confirmation=confirmation)
        ledger = Ledger(self.ledger_path)
        try:
            ledger.record_event(
                "warning",
                "streamlit",
                f"Cancellation requested for Tastytrade order {int(order_id)}",
            )
        finally:
            ledger.close()
        return result

    def reconcile_now(self, tolerance_w: float = 0.01) -> dict[str, Any]:
        plan = self.build_rebalance_plan(min_order_notional=0.0)
        result = reconcile(
            pd.Series(plan["targets"], dtype=float),
            plan["account"]["equity"],
            plan["prices"],
            plan["positions"],
            tolerance_w=tolerance_w,
        )
        ledger = Ledger(self.ledger_path)
        try:
            ledger.record_event(
                "info" if result["status"] == "ok" else "warning",
                "reconcile",
                f"Manual dashboard reconciliation: {json.dumps(result, sort_keys=True)}",
            )
        finally:
            ledger.close()
        return result
