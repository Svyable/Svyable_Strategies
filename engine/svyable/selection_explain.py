"""Counterfactual explanations for Svyable candidate selection.

This module turns candidate-board rows into plain, auditable explanations:
why the focus candidate is preferred, which alternatives are close, and why
blocked candidates are blocked. It is deliberately artifact-derived and does not
attempt to reveal hidden model reasoning.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _truthy(value: Any) -> bool:
    return str(value).lower() in {"true", "1", "yes"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _row_by_candidate(board: pd.DataFrame, candidate_id: str | None) -> pd.Series | None:
    if board.empty or "candidate_id" not in board or not candidate_id:
        return None
    rows = board[board["candidate_id"].astype(str) == str(candidate_id)]
    return None if rows.empty else rows.iloc[0]


def explain_blockers(row: pd.Series) -> list[str]:
    """Return human-readable blocking reasons for one candidate row."""
    reasons: list[str] = []
    if not _truthy(row.get("eligible")):
        reasons.append("not eligible under selector policy")
    if "hold_lock" in row and _truthy(row.get("hold_lock")):
        reasons.append("minimum hold lock is active")
    if "kill_switch" in row and _truthy(row.get("kill_switch")):
        reasons.append("risk kill switch is active")
    if "cadence_due" in row and not _truthy(row.get("cadence_due")):
        reasons.append("rebalance cadence is not due")
    if "rebalance_required" in row and not _truthy(row.get("rebalance_required")):
        reasons.append("target drift does not require rebalance")
    if _float(row.get("one_way_turnover")) > 0.35:
        reasons.append("one-way turnover exceeds policy ceiling")
    if not reasons:
        reasons.append("eligible alternative")
    return reasons


def candidate_delta(focus: pd.Series, other: pd.Series) -> dict[str, Any]:
    """Compare one alternative against the focus candidate."""
    fields = [
        "utility_bps",
        "expected_alpha_bps",
        "net_expected_alpha_bps",
        "estimated_cost_bps",
        "turnover_penalty_bps",
        "risk_penalty_bps",
        "one_way_turnover",
        "current_overlap",
    ]
    deltas = {
        field + "_delta": round(_float(focus.get(field)) - _float(other.get(field)), 6)
        for field in fields
        if field in focus or field in other
    }
    return {
        "candidate_id": str(other.get("candidate_id", "")),
        "strategy_id": str(other.get("strategy_id", "")),
        "eligible": _truthy(other.get("eligible")),
        "action": str(other.get("action", "")),
        "family": str(other.get("family", "")),
        "blockers": explain_blockers(other),
        **deltas,
    }


def explain_candidate_choice(
    board: pd.DataFrame,
    *,
    selected_candidate_id: str | None,
    max_alternatives: int = 8,
) -> dict[str, Any]:
    """Explain a selected/focus candidate against alternatives on the board."""
    if board.empty:
        return {"status": "empty_board", "summary": "No candidate board available.", "alternatives": []}
    focus = _row_by_candidate(board, selected_candidate_id) or board.iloc[0]
    focus_id = str(focus.get("candidate_id", ""))
    ordered = board.sort_values("utility_bps", ascending=False) if "utility_bps" in board.columns else board
    alternatives = []
    for _, row in ordered.iterrows():
        if str(row.get("candidate_id", "")) == focus_id:
            continue
        alternatives.append(candidate_delta(focus, row))
        if len(alternatives) >= max_alternatives:
            break
    utility = _float(focus.get("utility_bps"))
    alpha = _float(focus.get("expected_alpha_bps"))
    cost = _float(focus.get("estimated_cost_bps"))
    turnover = _float(focus.get("one_way_turnover"))
    summary = (
        f"{focus_id} is the focus candidate with {utility:.2f} bps utility, "
        f"{alpha:.2f} bps expected alpha, {cost:.2f} bps estimated cost, "
        f"and {turnover:.2%} one-way turnover."
    )
    return {
        "status": "ok",
        "focus_candidate_id": focus_id,
        "focus_strategy_id": str(focus.get("strategy_id", "")),
        "focus_action": str(focus.get("action", "")),
        "summary": summary,
        "focus_blockers": explain_blockers(focus),
        "alternatives": alternatives,
    }


def activation_readiness_from_context(context: dict[str, Any]) -> dict[str, Any]:
    """Summarize whether the context pack is ready for a decision file."""
    rails = context.get("rails", {}) or {}
    health = context.get("focus_candidate_artifact_health", {}) or {}
    allowed = rails.get("allowed_candidate_ids", []) or []
    issues: list[str] = []
    if not allowed:
        issues.append("no allowed candidate IDs")
    if health.get("inputs_stale"):
        issues.append("focus execution inputs are stale")
    if health.get("missing_execution_columns"):
        issues.append("focus execution artifact is missing required columns")
    status = "PASS" if not issues else "BLOCK"
    return {
        "status": status,
        "allowed_candidate_count": len(allowed),
        "issues": issues,
        "next_step": "write hash-matched agent_decision.json" if status == "PASS" else "refresh board/artifacts before decision",
    }
