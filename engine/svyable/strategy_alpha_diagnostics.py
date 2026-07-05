"""Pre-flight diagnostics for strategy factor packs.

These diagnostics are intentionally data-only and portfolio-neutral. They help
humans and agents inspect whether a new strategy's factor pack is usable before
it competes on the candidate board: coverage, latest dispersion, cross-factor
redundancy, and current strongest/weakest names. They do not estimate returns,
choose weights, or activate portfolios.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.factor_library import compute_all, factor_metadata
from svyable.panel import Panel
from svyable.strategy_registry import get_strategy


def _last_valid(frame: pd.DataFrame) -> pd.Series:
    valid = frame.dropna(how="all")
    return pd.Series(dtype=float) if valid.empty else valid.iloc[-1].dropna()


def factor_snapshot(panel: Panel, cfg: SvyableConfig, factor_names: list[str] | tuple[str, ...]) -> pd.DataFrame:
    """Return coverage/dispersion/latest-leader diagnostics for factors."""
    scores = compute_all(panel, cfg, names=list(factor_names))
    meta = factor_metadata(factor_names)
    rows: list[dict[str, Any]] = []
    for name in factor_names:
        frame = scores[name]
        recent = frame.tail(63)
        latest = _last_valid(frame)
        top_symbol = str(latest.idxmax()) if not latest.empty else ""
        bottom_symbol = str(latest.idxmin()) if not latest.empty else ""
        rows.append({
            "factor": name,
            "sleeve": meta.loc[name, "sleeve"] if name in meta.index else "unknown",
            "stage": meta.loc[name, "stage"] if name in meta.index else "unknown",
            "coverage_63d": round(float(recent.notna().mean().mean()), 4) if not recent.empty else 0.0,
            "latest_assets": int(latest.shape[0]),
            "latest_dispersion": round(float(latest.std(ddof=0)), 6) if not latest.empty else 0.0,
            "latest_abs_mean": round(float(latest.abs().mean()), 6) if not latest.empty else 0.0,
            "top_symbol": top_symbol,
            "top_score": round(float(latest.max()), 6) if not latest.empty else 0.0,
            "bottom_symbol": bottom_symbol,
            "bottom_score": round(float(latest.min()), 6) if not latest.empty else 0.0,
        })
    return pd.DataFrame(rows).set_index("factor")


def factor_correlation_matrix(
    panel: Panel,
    cfg: SvyableConfig,
    factor_names: list[str] | tuple[str, ...],
    *,
    lookback: int = 126,
) -> pd.DataFrame:
    """Return correlation of flattened recent factor score panels."""
    scores = compute_all(panel, cfg, names=list(factor_names))
    columns: dict[str, pd.Series] = {}
    for name, frame in scores.items():
        columns[name] = frame.tail(lookback).stack(dropna=True)
    combined = pd.DataFrame(columns)
    if combined.empty:
        return pd.DataFrame(index=factor_names, columns=factor_names, dtype=float)
    return combined.corr().reindex(index=factor_names, columns=factor_names)


def redundancy_warnings(corr: pd.DataFrame, *, threshold: float = 0.85) -> list[dict[str, Any]]:
    """Return highly correlated factor pairs for review."""
    warnings: list[dict[str, Any]] = []
    names = list(corr.index)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            value = corr.loc[left, right]
            if pd.notna(value) and abs(float(value)) >= threshold:
                warnings.append({
                    "left": left,
                    "right": right,
                    "corr": round(float(value), 6),
                    "severity": "high_redundancy" if abs(float(value)) >= 0.92 else "watch",
                })
    return warnings


def strategy_alpha_diagnostics(
    strategy_id: str,
    panel: Panel,
    cfg: SvyableConfig | None = None,
    *,
    lookback: int = 126,
) -> dict[str, Any]:
    """Build a diagnostics packet for a registered strategy's factor pack."""
    config = cfg or SvyableConfig()
    spec = get_strategy(strategy_id)
    names = tuple(spec.factor_names)
    snapshot = factor_snapshot(panel, config, names)
    corr = factor_correlation_matrix(panel, config, names, lookback=lookback)
    warnings = redundancy_warnings(corr)
    coverage_min = float(snapshot["coverage_63d"].min()) if not snapshot.empty else 0.0
    dispersion_min = float(snapshot["latest_dispersion"].min()) if not snapshot.empty else 0.0
    blockers: list[str] = []
    if coverage_min < 0.50:
        blockers.append("low recent factor coverage")
    if dispersion_min <= 0.0:
        blockers.append("one or more factors have zero latest dispersion")
    return {
        "strategy_id": spec.strategy_id,
        "display_name": spec.display_name,
        "factor_count": len(names),
        "stage_counts": snapshot["stage"].value_counts().to_dict() if not snapshot.empty else {},
        "coverage_min_63d": round(coverage_min, 4),
        "latest_dispersion_min": round(dispersion_min, 6),
        "redundancy_warning_count": len(warnings),
        "blockers": blockers,
        "status": "PASS" if not blockers else "WATCH",
        "snapshot": snapshot.reset_index().to_dict(orient="records"),
        "correlation": corr.round(6).reset_index().rename(columns={"index": "factor"}).to_dict(orient="records"),
        "redundancy_warnings": warnings,
        "contract": "Diagnostics only: does not choose weights, estimate future returns, or activate portfolios.",
    }
