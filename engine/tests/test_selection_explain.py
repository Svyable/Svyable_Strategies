"""Tests for counterfactual candidate explanations."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.selection_explain import activation_readiness_from_context, explain_candidate_choice


def _board() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "candidate_id": "focus_alpha",
            "strategy_id": "focus_alpha",
            "action": "rebalance",
            "eligible": True,
            "utility_bps": 6.0,
            "expected_alpha_bps": 9.0,
            "net_expected_alpha_bps": 8.0,
            "estimated_cost_bps": 0.5,
            "turnover_penalty_bps": 0.7,
            "risk_penalty_bps": 0.2,
            "one_way_turnover": 0.12,
            "current_overlap": 0.65,
            "rebalance_required": True,
            "cadence_due": True,
            "hold_lock": False,
            "kill_switch": False,
            "family": "frontier",
        },
        {
            "candidate_id": "blocked_fast",
            "strategy_id": "blocked_fast",
            "action": "rebalance",
            "eligible": False,
            "utility_bps": 8.0,
            "expected_alpha_bps": 12.0,
            "net_expected_alpha_bps": 10.0,
            "estimated_cost_bps": 1.0,
            "turnover_penalty_bps": 1.0,
            "risk_penalty_bps": 0.5,
            "one_way_turnover": 0.52,
            "current_overlap": 0.10,
            "rebalance_required": True,
            "cadence_due": True,
            "hold_lock": False,
            "kill_switch": False,
            "family": "fast",
        },
    ])


def test_explain_candidate_choice_returns_counterfactual_deltas():
    explanation = explain_candidate_choice(_board(), selected_candidate_id="focus_alpha")

    assert explanation["status"] == "ok"
    assert explanation["focus_candidate_id"] == "focus_alpha"
    assert explanation["focus_blockers"] == ["eligible alternative"]
    assert explanation["alternatives"][0]["candidate_id"] == "blocked_fast"
    assert "one-way turnover exceeds policy ceiling" in explanation["alternatives"][0]["blockers"]
    assert explanation["alternatives"][0]["utility_bps_delta"] == -2.0


def test_activation_readiness_summarizes_context_gates():
    context = {
        "rails": {"allowed_candidate_ids": ["focus_alpha"]},
        "focus_candidate_artifact_health": {"inputs_stale": False, "missing_execution_columns": []},
    }
    assert activation_readiness_from_context(context)["status"] == "PASS"

    blocked = activation_readiness_from_context({
        "rails": {"allowed_candidate_ids": []},
        "focus_candidate_artifact_health": {"inputs_stale": True, "missing_execution_columns": ["price"]},
    })
    assert blocked["status"] == "BLOCK"
    assert len(blocked["issues"]) == 3


if __name__ == "__main__":
    test_explain_candidate_choice_returns_counterfactual_deltas()
    test_activation_readiness_summarizes_context_gates()
    print("SELECTION EXPLAIN TESTS PASSED")
