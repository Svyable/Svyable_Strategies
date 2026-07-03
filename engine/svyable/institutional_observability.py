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


def _read_meta(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def load_metric_series(run_dir: Path) -> dict[str, float]:
    frame = _read_csv(run_dir / "institutional_metrics.csv", index_col=0)
    if frame.empty:
        return dict(_read_meta(run_dir / "meta.json").get("perf_1y_net") or {})
    column = "value" if "value" in frame.columns else frame.columns[0]
    return {
        str(index): float(value)
        for index, value in frame[column].items()
        if pd.notna(value)
    }


def enrich_candidate_board(board: pd.DataFrame) -> pd.DataFrame:
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


def _component_factor_catalog(meta: dict[str, Any]) -> pd.DataFrame:
    catalogs: list[pd.DataFrame] = []
    for strategy_id, output in (meta.get("component_output_dirs") or {}).items():
        frame = _read_csv(Path(output) / "factor_catalog.csv", index_col=0)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["component_strategy"] = str(strategy_id)
        catalogs.append(frame)
    if not catalogs:
        return pd.DataFrame()
    combined = pd.concat(catalogs)
    combined.index.name = "factor"
    return (
        combined.reset_index()
        .drop_duplicates(subset=["factor", "component_strategy"])
        .set_index("factor")
    )


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
    meta = _read_meta(run_dir / "meta.json")
    factors = _read_csv(run_dir / "factor_catalog.csv", index_col=0)
    if factors.empty and meta.get("kind") == "chimera_blend":
        factors = _component_factor_catalog(meta)
    return {
        "run_dir": run_dir,
        "weights": _read_csv(run_dir / "weights_today.csv", index_col=0),
        "pnl": _read_csv(run_dir / "pnl_diag.csv", index_col=0, parse_dates=True),
        "regime": _read_csv(run_dir / "regime.csv", index_col=0, parse_dates=True),
        "factors": factors,
        "components": _read_csv(
            run_dir / "component_weights_history.csv",
            index_col=0,
            parse_dates=True,
        ),
        "meta": meta,
    }


def candidate_frontier_columns(frame: pd.DataFrame) -> list[str]:
    preferred = [
        "candidate_id", "family", "eligible", "utility_bps",
        "expected_alpha_bps", "estimated_cost_bps", "one_way_turnover",
        "ann_return", "ann_vol", "sharpe", "sortino",
        "regression_alpha_ann", "beta", "market_correlation", "info_ratio",
        "upside_capture", "downside_capture", "capture_spread", "max_dd",
        "calmar", "tail_ratio_95_5", "positions", "gross", "components",
    ]
    return [column for column in preferred if column in frame.columns]
