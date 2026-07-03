"""Load and classify persisted factor-health artifacts for PM review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _read(path: Path, *, multi_index: bool = False) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, index_col=[0, 1] if multi_index else 0)


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if pd.notna(value) else default


def _pm_state(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    min_history = float(config.get("ic_min_history", 21))
    min_coverage = float(config.get("ic_min_coverage", 0.50))
    states = []
    for _, row in frame.iterrows():
        observations = _number(row.get("observations"))
        coverage = _number(row.get("coverage"))
        ic_ir = _number(row.get("ic_ir"))
        weight = _number(row.get("weight"))
        stage = str(row.get("stage", "proven"))
        if observations < min_history or coverage < min_coverage:
            state = "insufficient_evidence"
        elif ic_ir <= 0 and weight <= 1e-6:
            state = "quarantined"
        elif stage == "shadow" and ic_ir > 0 and weight > 0:
            state = "shadow_active"
        elif ic_ir > 0 and weight > 0:
            state = "active"
        else:
            state = "monitor"
        states.append(state)
    return pd.Series(states, index=frame.index, name="pm_state")


def load_factor_monitor(service) -> dict[str, Any]:
    run_dir = service.latest_run_dir()
    if run_dir is None:
        return {
            "catalog": pd.DataFrame(),
            "sleeves": pd.DataFrame(),
            "factors": {},
        }

    catalog = _read(run_dir / "factor_catalog.csv")
    sleeves = _read(run_dir / "sleeve_health.csv")
    config = service.strategy_snapshot().get("meta", {}).get("config") or {}
    factors: dict[str, pd.DataFrame] = {}
    for path in sorted(run_dir.glob("factor_health_*.csv")):
        name = path.stem.removeprefix("factor_health_")
        frame = _read(path, multi_index=True)
        if not frame.empty:
            frame["pm_state"] = _pm_state(frame, config)
        factors[name] = frame
    return {"catalog": catalog, "sleeves": sleeves, "factors": factors}
