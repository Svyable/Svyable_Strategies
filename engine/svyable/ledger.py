"""Run ledger — the local observability and execution-quality spine.

One SQLite file records every run, order plan, fill, daily equity point, and
operational event. The dashboard and supervision loop query this database
instead of scraping output directories.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  strategy TEXT NOT NULL,
  config_hash TEXT,
  data_last_date TEXT,
  data_status TEXT,
  status TEXT NOT NULL,
  metrics TEXT,
  output_dir TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  run_id INTEGER,
  broker TEXT,
  broker_order_id INTEGER,
  dry_run INTEGER,
  symbol TEXT, side TEXT, qty REAL, est_price REAL, est_notional REAL,
  status TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  run_id INTEGER,
  broker TEXT,
  broker_order_id INTEGER,
  transaction_id INTEGER,
  symbol TEXT,
  side TEXT,
  qty REAL,
  fill_price REAL,
  reference_price REAL,
  slippage_bps REAL,
  fees REAL,
  venue TEXT,
  exec_id TEXT
);
CREATE TABLE IF NOT EXISTS equity (
  d TEXT PRIMARY KEY,
  shadow_nav REAL,
  paper_equity REAL,
  drift_bps REAL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  level TEXT NOT NULL,
  source TEXT NOT NULL,
  message TEXT NOT NULL
);
"""

_FAILURE_STATUSES = frozenset({
    "error", "blocked", "rejected", "rejected_dry_run", "rejected_preflight",
    "cancelled", "expired", "removed", "partially removed", "skipped_after_failure",
})

_STATUS_SEVERITY = {
    "ok": 0,
    "planned": 0,
    "dry_run": 0,
    "awaiting_agent": 0,
    "evaluated": 0,
    "degraded": 1,
    "failed": 2,
}


def _result_failed(result: dict) -> bool:
    status = str(result.get("status", "")).strip().lower()
    return (
        status in _FAILURE_STATUSES
        or bool(result.get("error"))
        or bool(result.get("errors"))
        or bool(result.get("warnings"))
    )


def _execution_status_from_results(dry_run: bool, results: list[dict]) -> str | None:
    if dry_run or not results:
        return None
    if any(str(r.get("status", "")).strip().lower() == "skipped_after_failure" for r in results):
        return "failed"
    if any(_result_failed(r) for r in results):
        return "degraded"
    return "ok"


def _worse_status(left: str, right: str) -> str:
    l_key = str(left or "ok").strip().lower()
    r_key = str(right or "ok").strip().lower()
    return right if _STATUS_SEVERITY.get(r_key, 0) > _STATUS_SEVERITY.get(l_key, 0) else left


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.executescript(_SCHEMA)
        self._ensure_column("orders", "broker_order_id", "INTEGER")
        self._dedupe_fill_transactions()
        self.con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS fills_transaction_uq "
            "ON fills(transaction_id)"
        )
        self.con.commit()

    def _ensure_column(self, table: str, column: str, sql_type: str) -> None:
        existing = {row[1] for row in self.con.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            self.con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")

    def _dedupe_fill_transactions(self) -> None:
        self.con.execute(
            "DELETE FROM fills WHERE transaction_id IS NOT NULL AND id NOT IN ("
            " SELECT MIN(id) FROM fills WHERE transaction_id IS NOT NULL"
            " GROUP BY transaction_id)"
        )

    def record_run(self, *, kind: str, strategy: str, status: str,
                   config_hash: str = "", data_last_date: str = "",
                   data_status: str = "", metrics: dict | None = None,
                   output_dir: str = "") -> int:
        cur = self.con.execute(
            "INSERT INTO runs (ts, kind, strategy, config_hash, data_last_date,"
            " data_status, status, metrics, output_dir) VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), kind, strategy,
             config_hash, data_last_date, data_status, status,
             json.dumps(metrics or {}, default=str), output_dir))
        self.con.commit()
        return int(cur.lastrowid)

    def update_run_status(self, run_id: int, status: str, *, worse_only: bool = True) -> None:
        row = self.con.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run_id not found: {run_id}")
        new_status = _worse_status(str(row[0]), status) if worse_only else status
        self.con.execute("UPDATE runs SET status=? WHERE id=?", (new_status, run_id))
        self.con.commit()

    def record_orders(self, run_id: int, broker: str, dry_run: bool,
                      planned: list[dict], results: list[dict]) -> None:
        result_by_symbol = {r.get("symbol"): r for r in results}
        for order in planned:
            result = result_by_symbol.get(order["symbol"], {})
            self.con.execute(
                "INSERT INTO orders (ts, run_id, broker, broker_order_id, dry_run,"
                " symbol, side, qty, est_price, est_notional, status, reason)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), run_id, broker,
                 result.get("id"), int(dry_run), order["symbol"], order["side"],
                 order["qty"], order["est_price"], order["est_notional"],
                 "planned" if dry_run else result.get("status", "submitted"),
                 order.get("reason", "")))
        inferred_status = _execution_status_from_results(dry_run, results)
        if inferred_status and inferred_status != "ok":
            self.con.execute(
                "UPDATE runs SET status=? WHERE id=? AND kind='rebalance'",
                (inferred_status, run_id),
            )
        self.con.commit()

    def record_fills(self, run_id: int, broker: str, fills: list[dict]) -> None:
        for fill in fills:
            self.con.execute(
                "INSERT OR IGNORE INTO fills (ts, run_id, broker, broker_order_id,"
                " transaction_id, symbol, side, qty, fill_price, reference_price,"
                " slippage_bps, fees, venue, exec_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fill.get("executed_at") or datetime.now().isoformat(timespec="seconds"),
                    run_id,
                    broker,
                    fill.get("order_id"),
                    fill.get("transaction_id"),
                    fill.get("symbol"),
                    fill.get("side"),
                    fill.get("quantity"),
                    fill.get("fill_price"),
                    fill.get("reference_price"),
                    fill.get("slippage_bps"),
                    fill.get("fees"),
                    fill.get("venue"),
                    fill.get("exec_id"),
                ),
            )
        self.con.commit()

    def unfilled_orders(self, since_days: int = 5) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT o.run_id, o.broker_order_id, o.symbol, o.side, o.qty,"
            " o.est_price, o.ts FROM orders o LEFT JOIN fills f"
            " ON f.broker_order_id = o.broker_order_id"
            " WHERE o.broker_order_id IS NOT NULL AND f.id IS NULL"
            " AND o.ts >= datetime('now', ?) ORDER BY o.id",
            self.con,
            params=(f"-{since_days} days",),
        )

    def record_equity(self, d: date | str, *, shadow_nav: float | None = None,
                      paper_equity: float | None = None, note: str = "") -> None:
        d = str(d)
        row = self.con.execute(
            "SELECT shadow_nav, paper_equity FROM equity WHERE d=?", (d,)
        ).fetchone()
        if row:
            shadow_nav = shadow_nav if shadow_nav is not None else row[0]
            paper_equity = paper_equity if paper_equity is not None else row[1]
        drift = self._compute_drift(d, shadow_nav, paper_equity)
        self.con.execute(
            "INSERT INTO equity (d, shadow_nav, paper_equity, drift_bps, note)"
            " VALUES (?,?,?,?,?) ON CONFLICT(d) DO UPDATE SET shadow_nav=excluded.shadow_nav,"
            " paper_equity=excluded.paper_equity, drift_bps=excluded.drift_bps,"
            " note=excluded.note",
            (d, shadow_nav, paper_equity, drift, note))
        self.con.commit()

    def _compute_drift(self, d: str, shadow_nav, paper_equity) -> float | None:
        if shadow_nav is None or paper_equity is None:
            return None
        prev = self.con.execute(
            "SELECT shadow_nav, paper_equity FROM equity WHERE d < ? AND"
            " shadow_nav IS NOT NULL AND paper_equity IS NOT NULL"
            " ORDER BY d DESC LIMIT 1", (d,)).fetchone()
        if not prev or not prev[0] or not prev[1]:
            return None
        shadow_ret = shadow_nav / prev[0] - 1.0
        live_ret = paper_equity / prev[1] - 1.0
        return round((live_ret - shadow_ret) * 1e4, 2)

    def record_event(self, level: str, source: str, message: str) -> None:
        self.con.execute(
            "INSERT INTO events (ts, level, source, message) VALUES (?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), level, source, message))
        self.con.commit()

    def recent_runs(self, n: int = 20) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", self.con, params=(n,))

    def equity_frame(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM equity ORDER BY d", self.con)

    def execution_quality_frame(self, n: int = 250) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM fills ORDER BY id DESC LIMIT ?", self.con, params=(n,))

    def open_warnings(self, since_days: int = 7) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM events WHERE level != 'info' AND ts >= datetime('now', ?)"
            " ORDER BY id DESC", self.con, params=(f"-{since_days} days",))

    def health(self) -> dict:
        last = self.con.execute(
            "SELECT ts, kind, status FROM runs WHERE kind='daily'"
            " ORDER BY id DESC LIMIT 1").fetchone()
        eq = self.equity_frame()
        drift = eq["drift_bps"].dropna() if len(eq) else pd.Series(dtype=float)
        warning_count = self.con.execute(
            "SELECT COUNT(*) FROM events WHERE level='warning'"
            " AND ts >= datetime('now','-7 days')").fetchone()[0]
        critical_count = self.con.execute(
            "SELECT COUNT(*) FROM events WHERE level='critical'"
            " AND ts >= datetime('now','-7 days')").fetchone()[0]
        fill_stats = self.con.execute(
            "SELECT COUNT(*), AVG(ABS(slippage_bps)), MAX(ABS(slippage_bps))"
            " FROM fills WHERE slippage_bps IS NOT NULL"
        ).fetchone()
        return {
            "last_daily_run": {"ts": last[0], "status": last[2]} if last else None,
            "tracking_days": int(len(drift)),
            "drift_bps_mean_abs": round(float(drift.abs().mean()), 2) if len(drift) else None,
            "drift_bps_worst": round(float(drift.abs().max()), 2) if len(drift) else None,
            "drift_within_30bps_frac": round(float((drift.abs() <= 30).mean()), 3)
            if len(drift) else None,
            "warnings_7d": int(warning_count),
            "critical_7d": int(critical_count),
            "fills": int(fill_stats[0] or 0),
            "slippage_bps_mean_abs": round(float(fill_stats[1]), 2)
            if fill_stats[1] is not None else None,
            "slippage_bps_worst": round(float(fill_stats[2]), 2)
            if fill_stats[2] is not None else None,
        }

    def close(self) -> None:
        self.con.close()
