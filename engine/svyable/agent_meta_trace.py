"""Visible agent decision trace for the Svyable PM harness.

This module does not expose private chain-of-thought and does not generate
portfolio weights. It turns the immutable candidate board and candidate artifacts
into a transparent, auditable rationale tree: regime proxy, gate states, score
components, artifact health, and the provenance of the selected candidate's
weights.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd


def _truthy(value: Any) -> bool:
    return str(value).lower() in {"true", "1", "yes"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _score(value: float, scale: float) -> float:
    return float(math.tanh(value / max(scale, 1e-9)))


def infer_visible_regime(board: pd.DataFrame, artifact_health: dict[str, Any]) -> dict[str, Any]:
    """Infer an auditable HMM-like regime proxy from board-level observables.

    The states are intentionally simple and visible. They are not a hidden model;
    they summarize the tape that the candidate selector already exposes.
    """
    if board.empty:
        return {"state": "unknown", "probabilities": {}, "drivers": ["empty candidate board"]}
    eligible = board[board.get("eligible", False).astype(str).str.lower().isin({"true", "1", "yes"})]
    sample = eligible if not eligible.empty else board
    utility = sample.get("utility_bps", pd.Series(dtype=float)).map(_float)
    alpha = sample.get("expected_alpha_bps", pd.Series(dtype=float)).map(_float)
    turnover = sample.get("one_way_turnover", pd.Series(dtype=float)).map(_float)
    risk_penalty = sample.get("risk_penalty_bps", pd.Series(dtype=float)).map(_float)
    drawdown = sample.get("recent_max_drawdown", pd.Series(dtype=float)).map(_float)
    vol = sample.get("recent_vol", pd.Series(dtype=float)).map(_float)

    risk_on = 0.50 + 0.20 * _score(float(utility.mean()), 8.0) + 0.15 * _score(float(alpha.mean()), 10.0)
    risk_off = 0.25 + 0.20 * _score(float(risk_penalty.mean()), 10.0) + 0.20 * _score(float(drawdown.mean()), 0.10)
    chop = 0.20 + 0.20 * _score(float(turnover.mean()), 0.25) - 0.10 * _score(float(utility.mean()), 8.0)
    stress = 0.15 + 0.20 * _score(float(vol.mean()), 0.20)
    if artifact_health.get("inputs_stale"):
        stress += 0.25
        risk_on -= 0.15

    raw = {
        "risk_on": max(0.01, risk_on),
        "risk_off": max(0.01, risk_off),
        "chop": max(0.01, chop),
        "ops_stress": max(0.01, stress),
    }
    total = sum(raw.values()) or 1.0
    probs = {key: round(value / total, 4) for key, value in raw.items()}
    state = max(probs, key=probs.get)
    drivers = [
        f"eligible candidates {len(eligible)} of {len(board)}",
        f"mean utility {float(utility.mean()) if len(utility) else 0.0:.2f} bps",
        f"mean expected alpha {float(alpha.mean()) if len(alpha) else 0.0:.2f} bps",
        f"mean one-way turnover {float(turnover.mean()) if len(turnover) else 0.0:.2%}",
    ]
    if artifact_health.get("inputs_stale"):
        drivers.append("execution artifact is stale")
    summary = artifact_health.get("factor_trend_summary", {}) or {}
    if summary.get("deteriorating"):
        drivers.append(f"{summary.get('deteriorating')} factor series deteriorating")
    return {"state": state, "probabilities": probs, "drivers": drivers}


def candidate_decision_nodes(row: pd.Series) -> list[dict[str, Any]]:
    """Make the candidate decision tree visible as PASS/WARN/BLOCK nodes."""
    nodes: list[dict[str, Any]] = []
    eligible = _truthy(row.get("eligible"))
    nodes.append({"node": "selector_eligibility", "state": "PASS" if eligible else "BLOCK", "detail": "candidate passed selector gates" if eligible else "candidate is not eligible"})
    for column, good_when_true, label in [
        ("rebalance_required", True, "rebalance threshold"),
        ("cadence_due", True, "cadence due"),
        ("hold_lock", False, "minimum hold lock"),
        ("kill_switch", False, "risk kill switch"),
    ]:
        if column not in row:
            continue
        value = _truthy(row.get(column))
        ok = value is good_when_true
        nodes.append({"node": column, "state": "PASS" if ok else "BLOCK", "detail": label})
    turnover = _float(row.get("one_way_turnover"))
    nodes.append({"node": "turnover", "state": "PASS" if turnover <= 0.35 else "BLOCK", "value": round(turnover, 5), "detail": "policy max one-way turnover 35%"})
    utility = _float(row.get("utility_bps"))
    nodes.append({"node": "utility", "state": "PASS" if utility >= 0 else "WARN", "value": round(utility, 3), "detail": "net utility after costs and penalties"})
    return nodes


def score_breakdown(row: pd.Series) -> dict[str, Any]:
    expected = _float(row.get("expected_alpha_bps"))
    cost = _float(row.get("estimated_cost_bps"))
    turnover_penalty = _float(row.get("turnover_penalty_bps"))
    risk_penalty = _float(row.get("risk_penalty_bps"))
    utility = _float(row.get("utility_bps"))
    return {
        "formula": "expected_alpha - estimated_cost - turnover_penalty - risk_penalty",
        "expected_alpha_bps": round(expected, 3),
        "estimated_cost_bps": round(cost, 3),
        "turnover_penalty_bps": round(turnover_penalty, 3),
        "risk_penalty_bps": round(risk_penalty, 3),
        "utility_bps": round(utility, 3),
    }


def weight_provenance(row: pd.Series, *, max_symbols: int = 20) -> dict[str, Any]:
    output_dir = str(row.get("output_dir", "") or "")
    if not output_dir:
        return {"status": "missing_output_dir", "message": "hold/current rows may not have candidate weights"}
    path = Path(output_dir) / "weights_today.csv"
    if not path.exists():
        return {"status": "missing_weights", "path": str(path)}
    frame = pd.read_csv(path, index_col=0)
    column = "weight" if "weight" in frame.columns else frame.columns[0]
    weights = pd.to_numeric(frame[column], errors="coerce").dropna()
    gross = float(weights.abs().sum())
    net = float(weights.sum())
    effective_n = float(1.0 / (weights.pow(2).sum() + 1e-12)) if len(weights) else 0.0
    top = weights.reindex(weights.abs().sort_values(ascending=False).head(max_symbols).index)
    return {
        "status": "ok",
        "path": str(path),
        "provenance": "weights are generated by the deterministic candidate pipeline; the agent only selects the candidate_id",
        "gross": round(gross, 5),
        "net": round(net, 5),
        "positions": int((weights.abs() > 1e-9).sum()),
        "effective_n": round(effective_n, 2),
        "top_weights": {str(symbol): round(float(value), 6) for symbol, value in top.items()},
    }


def build_meta_trace(
    board: pd.DataFrame,
    *,
    selected_candidate_id: str | None,
    artifact_health: dict[str, Any],
    max_candidates: int = 8,
) -> dict[str, Any]:
    """Build an auditable visible rationale trace for agent and human review."""
    if board.empty:
        return {"status": "empty_board", "regime": {"state": "unknown"}, "candidates": []}
    focus_id = selected_candidate_id or str(board.iloc[0].get("candidate_id", ""))
    selected = board[board["candidate_id"].astype(str) == str(focus_id)] if "candidate_id" in board else pd.DataFrame()
    focus = selected.iloc[0] if not selected.empty else board.iloc[0]
    view = board.sort_values("utility_bps", ascending=False).head(max_candidates) if "utility_bps" in board.columns else board.head(max_candidates)
    candidates = []
    for _, row in view.iterrows():
        candidates.append({
            "candidate_id": str(row.get("candidate_id", "")),
            "strategy_id": str(row.get("strategy_id", "")),
            "action": str(row.get("action", "")),
            "eligible": _truthy(row.get("eligible")),
            "score_breakdown": score_breakdown(row),
            "decision_nodes": candidate_decision_nodes(row),
        })
    return {
        "status": "ok",
        "selected_candidate_id": str(focus.get("candidate_id", "")),
        "visible_regime": infer_visible_regime(board, artifact_health),
        "selected_score_breakdown": score_breakdown(focus),
        "selected_decision_nodes": candidate_decision_nodes(focus),
        "weight_provenance": weight_provenance(focus),
        "ranked_candidate_trace": candidates,
    }
