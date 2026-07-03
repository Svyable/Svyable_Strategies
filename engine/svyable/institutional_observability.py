"""Read-only institutional diagnostics assembled from candidate artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, **kwargs)
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def load_metric_series(run_dir: Path) -> dict[str, float]:
    path = run_dir / "institutional_metrics.csv"
    frame = _read_csv(path, index_col=0)
    if frame.empty:
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            return {}
        try:
            return dict(json.loads(meta_path.read_text()).get("perf_1y_net") or {})
        except (OSError, json.JSONDecodeError):
            return {}
    column = "value" if "value" in frame.columns else frame.columns[0]
    return {
        str(index): float(value)
        for index, value in frame[column].items()
        if pd.notna(value)
    }


def enrich_candidate_board(board: pd.DataFrame) -> pd.DataFrame:
    """Join each candidate row to its persisted institutional metrics."""
    if board.empty:
        return board.copy()
    rows: list[dict[str, Any]] = []
    for _, row in board.iterrows():
        record = row.to_dict()
        output = str(record.get("output_dir", ""))
        if output:
            record.update(load_metric_series(Path(output)))
        rows.append(record)
    return pd.DataFrame(rows)


def candidate_artifacts(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    record = row.to_dict() if isinstance(row, pd.Series) else dict(row)
    output = str(record.get("output_dir", ""))
    if not output:
        return {
            "run_dir": None,
            "weights": pd.DataFrame(),
            "pnl": pd.DataFrame(),
            "regime": pd.DataFrame(),
            "factors": pd.DataFrame(),
            "components": pd.DataFrame(),
            "meta": {},
        }
    run_dir = Path(output)
    meta = {}
    try:
        meta = json.loads((run_dir / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "run_dir": run_dir,
        "weights": _read_csv(run_dir / "weights_today.csv", index_col=0),
        "pnl": _read_csv(run_dir / "pnl_diag.csv", index_col=0, parse_dates=True),
        "regime": _read_csv(run_dir / "regime.csv", index_col=0, parse_dates=True),
        "factors": _read_csv(run_dir / "factor_catalog.csv", index_col=0),
        "components": _read_csv(
            run_dir / "component_weights_history.csv",
            index_col=0,
            parse_dates=True,
        ),
        "meta": meta,
    }


def candidate_frontier_columns(frame: pd.DataFrame) -> list[str]:
    preferred = [
        "candidate_id",
        "family",
        "eligible",
        "utility_bps",
        "expected_alpha_bps",
        "estimated_cost_bps",
        "one_way_turnover",
        "ann_return",
        "ann_vol",
        "sharpe",
        "sortino",
        "regression_alpha_ann",
        "beta",
        "market_correlation",
        "info_ratio",
        "upside_capture",
        "downside_capture",
        "capture_spread",
        "max_dd",
        "calmar",
        "tail_ratio_95_5",
        "positions",
        "gross",
        "components",
    ]
    return [column for column in preferred if column in frame.columns]
