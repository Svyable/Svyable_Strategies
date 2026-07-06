"""Chart/table view models for the Selection Meta Harness."""

from __future__ import annotations

from typing import Any


ALPHA_STRATEGY_IDS = {
    "svyable_alpha_catalyst",
    "svyable_tape_acceleration",
    "svyable_leadership_quality",
    "svyable_downside_resilience",
    "svyable_rotation_breadth",
}
ALPHA_STRATEGY_FAMILY = {
    "svyable_alpha_catalyst": "Alpha Catalyst",
    "svyable_tape_acceleration": "Tape Acceleration",
    "svyable_leadership_quality": "Leadership Quality",
    "svyable_downside_resilience": "Downside Resilience",
    "svyable_rotation_breadth": "Rotation Breadth",
}


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


def _candidate_strategy_id(item: dict[str, Any]) -> str:
    return str(item.get("strategy_id") or item.get("strategy") or item.get("strategy_name") or "")


def _candidate_score(item: dict[str, Any], key: str) -> float:
    score = item.get("score_breakdown", {}) or {}
    return _float(item.get(key, score.get(key)))


def alpha_candidate_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return alpha-family rows from the ranked candidate trace."""
    trace = context.get("meta_decision_trace", {}) or {}
    allowed = set(str(item) for item in ((context.get("rails", {}) or {}).get("allowed_candidate_ids", []) or []))
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(trace.get("ranked_candidate_trace", []) or [], start=1):
        strategy_id = _candidate_strategy_id(item)
        if strategy_id not in ALPHA_STRATEGY_IDS:
            continue
        candidate = str(item.get("candidate_id", ""))
        rows.append({
            "rank": rank,
            "candidate_id": candidate,
            "strategy_id": strategy_id,
            "family": ALPHA_STRATEGY_FAMILY.get(strategy_id, strategy_id),
            "eligible": bool(item.get("eligible")),
            "allowed": candidate in allowed,
            "action": str(item.get("action", "")),
            "expected_alpha_bps": round(_candidate_score(item, "expected_alpha_bps"), 3),
            "utility_bps": round(_candidate_score(item, "utility_bps"), 3),
            "cost_bps": round(_candidate_score(item, "estimated_cost_bps"), 3),
            "turnover_penalty_bps": round(_candidate_score(item, "turnover_penalty_bps"), 3),
            "risk_penalty_bps": round(_candidate_score(item, "risk_penalty_bps"), 3),
        })
    rows.sort(key=lambda row: row["utility_bps"], reverse=True)
    return rows


def alpha_candidate_metrics(context: dict[str, Any]) -> dict[str, Any]:
    """Return headline alpha-candidate metrics for the PM cockpit."""
    rows = alpha_candidate_rows(context)
    allowed = [row for row in rows if row["allowed"]]
    eligible = [row for row in rows if row["eligible"]]
    best = rows[0] if rows else {}
    return {
        "alpha_candidates": len(rows),
        "allowed_alpha_candidates": len(allowed),
        "eligible_alpha_candidates": len(eligible),
        "best_alpha_candidate": best.get("candidate_id", "—"),
        "best_alpha_strategy": best.get("strategy_id", "—"),
        "best_alpha_utility_bps": best.get("utility_bps", 0.0),
    }


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
