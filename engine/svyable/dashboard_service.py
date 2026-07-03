"""Backend service for the Streamlit operations console.

The service owns filesystem, ledger, strategy-artifact, and broker access.
Streamlit only renders returned data and collects explicit confirmations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from svyable.broker_settings import TastySettings
from svyable.execution_backfill import ExecutionBackfillMixin
from svyable.execution_control import ExecutionControlMixin
from svyable.ledger import Ledger
from svyable.tastytrade_sdk import OrderIntent, TastySdkBroker

ENGINE_ROOT = Path(__file__).resolve().parents[1]


class DashboardService(ExecutionBackfillMixin, ExecutionControlMixin):
    def __init__(
        self,
        *,
        output_root: str | Path | None = None,
        settings: TastySettings | None = None,
        broker: TastySdkBroker | None = None,
    ) -> None:
        self.settings = settings or TastySettings.from_env(require_credentials=False)
        if output_root is None:
            default = "outputs" if self.settings.is_test else "outputs-production"
            output_root = ENGINE_ROOT / default
        self.output_root = Path(output_root)
        if not self.settings.audit_path.is_absolute():
            self.settings = replace(
                self.settings,
                audit_path=self.output_root / "audit" / "tastytrade.jsonl",
            )
        self.strategy_id = "svyable_nasdaq_lo"
        self._broker = broker

    @property
    def broker(self) -> TastySdkBroker:
        if self._broker is None:
            settings = TastySettings.from_env(require_credentials=True)
            settings = replace(settings, audit_path=self.settings.audit_path)
            self._broker = TastySdkBroker(settings=settings)
        return self._broker

    @property
    def ledger_path(self) -> Path:
        return self.output_root / "ledger.db"

    def latest_run_dir(self) -> Path | None:
        strategy_root = self.output_root / self.strategy_id
        if not strategy_root.exists():
            return None
        runs = sorted(
            path
            for path in strategy_root.iterdir()
            if path.is_dir() and (path / "weights_today.csv").exists()
        )
        return runs[-1] if runs else None

    @staticmethod
    def _read_frame(path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, index_col=0)

    def strategy_snapshot(self) -> dict[str, Any]:
        run_dir = self.latest_run_dir()
        if run_dir is None:
            return {
                "run_dir": None,
                "weights": pd.DataFrame(),
                "weights_history": pd.DataFrame(),
                "budget": pd.DataFrame(),
                "sleeve_weights": pd.DataFrame(),
                "ic_health": pd.DataFrame(),
                "pnl": pd.DataFrame(),
                "execution_inputs": pd.DataFrame(),
                "meta": {},
                "report": "",
                "factor_weights": {},
            }

        meta_path = run_dir / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        factor_weights = {
            path.stem.removeprefix("factor_weights_"): self._read_frame(path)
            for path in sorted(run_dir.glob("factor_weights_*.csv"))
        }
        return {
            "run_dir": run_dir,
            "weights": self._read_frame(run_dir / "weights_today.csv"),
            "weights_history": self._read_frame(run_dir / "weights_history.csv"),
            "budget": self._read_frame(run_dir / "budget.csv"),
            "sleeve_weights": self._read_frame(run_dir / "sleeve_weights.csv"),
            "ic_health": self._read_frame(run_dir / "ic_health.csv"),
            "pnl": self._read_frame(run_dir / "pnl_diag.csv"),
            "execution_inputs": self._read_frame(run_dir / "execution_inputs.csv"),
            "meta": meta,
            "report": (run_dir / "morning_report.md").read_text()
            if (run_dir / "morning_report.md").exists()
            else "",
            "factor_weights": factor_weights,
        }

    def ledger_snapshot(self) -> dict[str, Any]:
        ledger = Ledger(self.ledger_path)
        try:
            orders = pd.read_sql_query(
                "SELECT * FROM orders ORDER BY id DESC LIMIT 100", ledger.con
            )
            events = pd.read_sql_query(
                "SELECT * FROM events ORDER BY id DESC LIMIT 100", ledger.con
            )
            return {
                "health": ledger.health(),
                "runs": ledger.recent_runs(50),
                "equity": ledger.equity_frame(),
                "warnings": ledger.open_warnings(30),
                "orders": orders,
                "events": events,
            }
        finally:
            ledger.close()

    def broker_snapshot(self) -> dict[str, Any]:
        return {
            "environment": self.broker.environment,
            "account_number": self.broker.account_number,
            "session_valid": self.broker.validate_session(),
            "account": self.broker.get_account(),
            "positions": pd.DataFrame(self.broker.get_positions_frame()),
            "orders": pd.DataFrame(
                self.broker.search_orders(
                    start_date=datetime.now().date().isoformat(), per_page=100
                )
            ),
        }

    def quote(self, symbol: str) -> dict[str, Any]:
        return asdict(self.broker.get_quote(symbol))

    def target_series(self) -> pd.Series:
        snapshot = self.strategy_snapshot()
        weights = snapshot["weights"]
        if weights.empty:
            raise FileNotFoundError(
                "No strategy weights found. Run `svyable daily` before planning orders."
            )
        column = "weight" if "weight" in weights.columns else weights.columns[0]
        targets = weights[column].astype(float)
        targets.index = targets.index.astype(str)
        return targets

    def reconcile_now(self, tolerance_w: float = 0.01) -> dict[str, Any]:
        execution = self.execution_inputs()
        if execution["stale"]:
            raise RuntimeError(
                "Execution inputs are stale; run `svyable daily` before reconciliation."
            )
        return super().reconcile_now(tolerance_w=tolerance_w)

    def preview_manual_order(self, intent: OrderIntent) -> dict[str, Any]:
        return self.broker.preflight(intent.normalized())

    def submit_manual_order(
        self, intent: OrderIntent, *, confirmation: str
    ) -> dict[str, Any]:
        result = self.broker.submit_intent(
            OrderIntent(**(asdict(intent.normalized()) | {"dry_run": False})),
            confirmation=confirmation,
        )
        ledger = Ledger(self.ledger_path)
        try:
            run_id = ledger.record_run(
                kind="manual_order",
                strategy=self.strategy_id,
                status="ok",
                metrics={
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "quantity": intent.quantity,
                    "broker": "tastytrade-sdk",
                },
            )
            quote = self.broker.get_quote(intent.symbol)
            planned = [
                {
                    "symbol": intent.symbol.upper(),
                    "side": intent.side.lower(),
                    "qty": intent.quantity,
                    "est_price": quote.execution_price or 0.0,
                    "est_notional": (quote.execution_price or 0.0) * intent.quantity,
                    "reason": "manual",
                }
            ]
            ledger.record_orders(
                run_id, "tastytrade-sdk", False, planned, [result]
            )
        finally:
            ledger.close()
        return result

    def audit_tail(self, n: int = 100) -> pd.DataFrame:
        path = Path(self.settings.audit_path)
        if not path.exists():
            return pd.DataFrame()
        lines = path.read_text(encoding="utf-8").splitlines()[-n:]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"event": "malformed", "payload": line})
        return pd.DataFrame(records)
