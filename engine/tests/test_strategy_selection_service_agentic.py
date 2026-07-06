"""Service-level tests for the Streamlit-first agentic PM workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.strategy_selection_service import StrategySelectionService


def _write_board_and_context(root: Path) -> None:
    selection = root / "strategy_selection"
    board_dir = selection / "20260705_073000"
    board_dir.mkdir(parents=True)
    as_of = "2026-07-05"
    candidate_hash = "hash-streamlit-agentic-test"
    pd.DataFrame(
        [
            {
                "candidate_id": "candidate_a",
                "strategy_id": "candidate_a",
                "action": "rebalance",
                "eligible": True,
                "utility_bps": 6.5,
                "expected_alpha_bps": 8.0,
                "net_expected_alpha_bps": 7.4,
                "estimated_cost_bps": 0.6,
                "one_way_turnover": 0.05,
                "current_overlap": 0.80,
                "family": "test",
                "as_of": as_of,
                "candidate_set_hash": candidate_hash,
            },
            {
                "candidate_id": "hold_current",
                "strategy_id": "cash",
                "action": "hold",
                "eligible": True,
                "utility_bps": 0.0,
                "expected_alpha_bps": 0.0,
                "net_expected_alpha_bps": 0.0,
                "estimated_cost_bps": 0.0,
                "one_way_turnover": 0.0,
                "current_overlap": 1.0,
                "family": "baseline",
                "as_of": as_of,
                "candidate_set_hash": candidate_hash,
            },
        ]
    ).to_csv(board_dir / "candidate_board.csv", index=False)

    context = {
        "as_of": as_of,
        "candidate_set_hash": candidate_hash,
        "summary": {"top_eligible_candidate": "candidate_a"},
        "rails": {"allowed_candidate_ids": ["candidate_a", "hold_current"]},
        "decision_readiness": {"status": "PASS", "issues": []},
        "focus_candidate_artifact_health": {
            "inputs_stale": False,
            "missing_execution_columns": [],
        },
        "candidates": [
            {"candidate_id": "candidate_a"},
            {"candidate_id": "hold_current"},
        ],
        "meta_decision_trace": {"visible_regime": {"state": "risk_on"}},
        "selection_explanation": {"summary": "Candidate A has the best test utility."},
    }
    selection.mkdir(parents=True, exist_ok=True)
    (selection / "latest_agent_context.json").write_text(json.dumps(context, indent=2))
    (selection / "latest_agent_pm_memo.md").write_text("# Test memo\n")


def test_write_guarded_decision_uses_latest_context(tmp_path: Path):
    _write_board_and_context(tmp_path)
    service = StrategySelectionService(tmp_path)

    result = service.write_guarded_decision(
        candidate_id="candidate_a",
        confidence=0.65,
        reason="Candidate A has the cleanest reviewed edge for this test board.",
    )

    assert result["status"] == "PASS"
    decision = json.loads((tmp_path / "strategy_selection" / "agent_decision.json").read_text())
    assert decision["candidate_id"] == "candidate_a"
    assert decision["candidate_set_hash"] == "hash-streamlit-agentic-test"
    assert decision["writer"] == "svyable.agent_decision_writer"


def test_review_chain_pass_unlocks_activation_readiness(tmp_path: Path):
    _write_board_and_context(tmp_path)
    service = StrategySelectionService(tmp_path)
    service.write_guarded_decision(
        candidate_id="candidate_a",
        confidence=0.65,
        reason="Candidate A has the cleanest reviewed edge for this test board.",
    )

    before = service.activation_readiness()
    assert before["status"] == "BLOCK"
    assert any("Review chain" in blocker for blocker in before["blockers"])

    chain = service.run_review_chain()
    assert chain["status"] == "PASS"

    after = service.activation_readiness()
    assert after["status"] == "PASS"
    assert after["candidate_id"] == "candidate_a"
    assert after["decision_fingerprint"]


def test_guarded_decision_rejects_disallowed_candidate(tmp_path: Path):
    _write_board_and_context(tmp_path)
    service = StrategySelectionService(tmp_path)

    try:
        service.write_guarded_decision(
            candidate_id="not_allowed",
            confidence=0.5,
            reason="This candidate should be rejected before activation.",
        )
    except ValueError as exc:
        assert "not currently allowed" in str(exc)
    else:
        raise AssertionError("expected ValueError")
