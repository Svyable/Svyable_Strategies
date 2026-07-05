"""Tests for Selection Meta Harness chart models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_chart_model import activation_readiness_rows, candidate_ranking_rows, utility_waterfall_rows


def _context():
    return {
        "decision_readiness": {"status": "PASS", "next_step": "prepare decision artifact"},
        "focus_candidate_artifact_health": {"inputs_stale": False, "artifact_date": "2026-01-02", "expected_date": "2026-01-02"},
        "rails": {"allowed_candidate_ids": ["candidate_a"]},
        "meta_decision_trace": {
            "selected_score_breakdown": {
                "expected_alpha_bps": 10.0,
                "estimated_cost_bps": 1.0,
                "turnover_penalty_bps": 2.0,
                "risk_penalty_bps": 0.5,
                "utility_bps": 6.5,
            },
            "ranked_candidate_trace": [
                {"candidate_id": "candidate_b", "eligible": False, "action": "rebalance", "score_breakdown": {"utility_bps": 3.0, "expected_alpha_bps": 8.0}},
                {"candidate_id": "candidate_a", "eligible": True, "action": "rebalance", "score_breakdown": {"utility_bps": 6.5, "expected_alpha_bps": 10.0}},
            ],
        },
    }


def test_utility_waterfall_has_signed_components():
    rows = utility_waterfall_rows(_context())

    assert rows[0]["signed_bps"] == 10.0
    assert rows[1]["signed_bps"] == -1.0
    assert rows[-1]["signed_bps"] == 6.5


def test_candidate_ranking_sorts_by_utility():
    rows = candidate_ranking_rows(_context())

    assert rows[0]["candidate"] == "candidate_a"
    assert rows[0]["eligible"] is True


def test_activation_readiness_rows_capture_final_gates():
    rows = activation_readiness_rows(
        _context(),
        {"status": "PASS", "candidate_id": "candidate_a"},
        {"status": "PASS", "decision_fingerprint": "abc"},
        {"status": "PASS", "next_step": "review artifacts unchanged"},
    )

    by_gate = {row["gate"]: row for row in rows}
    assert by_gate["Allowed candidates"]["status"] == "PASS"
    assert by_gate["Artifact freshness"]["status"] == "PASS"
    assert by_gate["Integrity audit"]["status"] == "PASS"


if __name__ == "__main__":
    test_utility_waterfall_has_signed_components()
    test_candidate_ranking_sorts_by_utility()
    test_activation_readiness_rows_capture_final_gates()
    print("AGENT CHART MODEL TESTS PASSED")
