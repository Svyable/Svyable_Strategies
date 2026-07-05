"""Tests for one-click review chain runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_review_chain import run_review_chain


def _write_valid_review_inputs(root: Path) -> None:
    selection = root / "strategy_selection"
    selection.mkdir(parents=True)
    (selection / "latest_agent_context.json").write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "summary": {"candidate_count": 1, "eligible_count": 1},
        "rails": {"allowed_candidate_ids": ["candidate_a"]},
        "decision_readiness": {"status": "PASS", "issues": []},
        "focus_candidate_artifact_health": {"inputs_stale": False, "missing_execution_columns": []},
        "meta_decision_trace": {"visible_regime": {"state": "risk_on", "probabilities": {"risk_on": 1.0}}},
        "selection_explanation": {"summary": "candidate_a is the test focus"},
        "candidates": [{"candidate_id": "candidate_a"}],
    }))
    (selection / "latest_agent_pm_memo.md").write_text("# memo\n")
    (selection / "agent_decision.json").write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "candidate_id": "candidate_a",
        "confidence": 0.75,
        "reason": "Candidate passes the one-click review chain test.",
    }))


def test_review_chain_passes_with_valid_inputs(tmp_path: Path):
    _write_valid_review_inputs(tmp_path)

    report = run_review_chain(tmp_path)

    assert report["status"] == "PASS"
    assert Path(report["report_path"]).exists()
    assert [stage["name"] for stage in report["stages"]] == [
        "context_pack",
        "decision_guard",
        "review_receipt",
        "integrity_audit",
    ]


def test_review_chain_blocks_when_decision_missing(tmp_path: Path):
    _write_valid_review_inputs(tmp_path)
    (tmp_path / "strategy_selection" / "agent_decision.json").unlink()

    report = run_review_chain(tmp_path)

    assert report["status"] == "BLOCK"
    assert "decision_guard" in report["blockers"]


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_review_chain_passes_with_valid_inputs(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_review_chain_blocks_when_decision_missing(Path(tmp))
    print("AGENT REVIEW CHAIN TESTS PASSED")
