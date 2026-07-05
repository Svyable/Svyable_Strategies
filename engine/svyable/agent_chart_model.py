"""Chart/table view models for the Selection Meta Harness."""

from __future__ import annotations

from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def utility_waterfall_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return signed utility components for a selected-candidate chart."""
    score = ((context.get("meta_decision_trace", {}) or {}).get("selected_score_breakdown", {}) or {})
    expected = _float(score.get("expected_alpha_bps"))
    cost = _float(score.get("estimated_cost_bps"))
    turnover = _float(score.get("turnover_penalty_bps"))
    risk = _float(score.get("risk_penalty_bps"))
    utility = _float(score.get("utility_bps"))
    return [
        {"component": "Expected alpha", "signed_bps": round(expected, 3)},
        {"component": "Cost", "signed_bps": round(-abs(cost), 3)},
        {"component": "Turnover penalty", "signed_bps": round(-abs(turnover), 3)},
        {"component": "Risk penalty", "signed_bps": round(-abs(risk), 3)},
        {"component": "Net utility", "signed_bps": round(utility, 3)},
    ]


def candidate_ranking_rows(context: dict[str, Any], *, top_n: int = 12) -> list[dict[str, Any]]:
    """Return ranked candidates with compact plotting columns."""
    rows: list[dict[str, Any]] = []
    trace = context.get("meta_decision_trace", {}) or {}
    for item in trace.get("ranked_candidate_trace", []) or []:
        score = item.get("score_breakdown", {}) or {}
        candidate = str(item.get("candidate_id", ""))
        rows.append({
            "candidate": candidate,
            "label": candidate[:28],
            "utility_bps": round(_float(score.get("utility_bps")), 3),
            "expected_alpha_bps": round(_float(score.get("expected_alpha_bps")), 3),
            "eligible": bool(item.get("eligible")),
            "action": str(item.get("action", "")),
        })
    rows.sort(key=lambda row: row["utility_bps"], reverse=True)
    return rows[:top_n]


def activation_readiness_rows(
    context: dict[str, Any],
    guard: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return final activation readiness gates for the operator cockpit."""
    guard = guard or {}
    receipt = receipt or {}
    audit = audit or {}
    readiness = context.get("decision_readiness", {}) or {}
    health = context.get("focus_candidate_artifact_health", {}) or {}
    rails = context.get("rails", {}) or {}
    allowed = rails.get("allowed_candidate_ids", []) or []
    return [
        {
            "gate": "Context readiness",
            "status": readiness.get("status", "PENDING"),
            "detail": readiness.get("next_step", "no context readiness yet"),
        },
        {
            "gate": "Allowed candidates",
            "status": "PASS" if allowed else "BLOCK",
            "detail": f"{len(allowed)} allowed candidate IDs",
        },
        {
            "gate": "Artifact freshness",
            "status": "BLOCK" if health.get("inputs_stale") else "PASS",
            "detail": f"artifact={health.get('artifact_date')} expected={health.get('expected_date')}",
        },
        {
            "gate": "Decision guard",
            "status": guard.get("status", "PENDING"),
            "detail": guard.get("candidate_id", "no guard report"),
        },
        {
            "gate": "Review receipt",
            "status": receipt.get("status", "PENDING"),
            "detail": receipt.get("decision_fingerprint", "no receipt"),
        },
        {
            "gate": "Integrity audit",
            "status": audit.get("status", "PENDING"),
            "detail": audit.get("next_step", "no audit"),
        },
    ]
