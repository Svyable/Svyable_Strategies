"""Idempotency guard for strategy order batches.

A deterministic plan fingerprint is reserved in SQLite before any order call.
The same plan cannot be submitted twice, even across Streamlit reruns or process
restarts. Ambiguous failures remain locked for human review rather than being
silently retried.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import pandas as pd

from svyable.ledger import Ledger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submission_batches (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  plan_hash TEXT NOT NULL UNIQUE,
  environment TEXT NOT NULL,
  status TEXT NOT NULL,
  details TEXT
);
"""


class SubmissionGuardMixin:
    def _plan_hash(self, plan: dict[str, Any]) -> str:
        payload = {
            "environment": self.settings.environment,
            "execution_inputs_date": plan.get("execution_inputs_date"),
            "targets": plan.get("targets", {}),
            "positions": plan.get("positions", {}),
            "orders": plan.get("orders", []),
            "adv_participation_cap": plan.get("adv_participation_cap"),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()[:24]

    def build_rebalance_plan(
        self, *, min_order_notional: float = 100.0
    ) -> dict[str, Any]:
        plan = super().build_rebalance_plan(
            min_order_notional=min_order_notional
        )
        plan["plan_hash"] = self._plan_hash(plan)
        return plan

    def _reserve_plan(self, plan_hash: str) -> None:
        ledger = Ledger(self.ledger_path)
        try:
            ledger.con.executescript(_SCHEMA)
            cursor = ledger.con.execute(
                "INSERT OR IGNORE INTO submission_batches "
                "(ts, plan_hash, environment, status, details) VALUES (?,?,?,?,?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    plan_hash,
                    self.settings.environment,
                    "reserved",
                    "{}",
                ),
            )
            ledger.con.commit()
            if cursor.rowcount == 0:
                row = ledger.con.execute(
                    "SELECT ts, status FROM submission_batches WHERE plan_hash=?",
                    (plan_hash,),
                ).fetchone()
                when, status = row if row else ("unknown", "unknown")
                raise RuntimeError(
                    f"Plan {plan_hash} was already reserved at {when} "
                    f"with status={status}. Rebuild from fresh broker state before retrying."
                )
        finally:
            ledger.close()

    def _finish_plan(
        self,
        plan_hash: str,
        *,
        status: str,
        details: dict[str, Any],
    ) -> None:
        ledger = Ledger(self.ledger_path)
        try:
            ledger.con.executescript(_SCHEMA)
            ledger.con.execute(
                "UPDATE submission_batches SET status=?, details=? WHERE plan_hash=?",
                (status, json.dumps(details, default=str), plan_hash),
            )
            ledger.con.commit()
        finally:
            ledger.close()

    def submit_plan(
        self, plan: dict[str, Any], *, confirmation: str
    ) -> dict[str, Any]:
        plan_hash = plan.get("plan_hash") or self._plan_hash(plan)
        self._reserve_plan(plan_hash)
        try:
            result = super().submit_plan(plan, confirmation=confirmation)
        except Exception as exc:
            self._finish_plan(
                plan_hash,
                status="review_required",
                details={"error": str(exc)[:1000]},
            )
            ledger = Ledger(self.ledger_path)
            try:
                ledger.record_event(
                    "critical",
                    "submission_guard",
                    f"Batch {plan_hash} failed after reservation; inspect broker state "
                    "before any retry.",
                )
            finally:
                ledger.close()
            raise

        result = {**result, "plan_hash": plan_hash}
        self._finish_plan(
            plan_hash,
            status=str(result.get("status", "complete")),
            details={
                "submitted": result.get("submitted"),
                "reconciliation": result.get("reconciliation"),
                "execution_quality": result.get("execution_quality"),
            },
        )
        return result

    def submission_batches(self, n: int = 100) -> pd.DataFrame:
        ledger = Ledger(self.ledger_path)
        try:
            ledger.con.executescript(_SCHEMA)
            return pd.read_sql_query(
                "SELECT * FROM submission_batches ORDER BY id DESC LIMIT ?",
                ledger.con,
                params=(n,),
            )
        finally:
            ledger.close()
