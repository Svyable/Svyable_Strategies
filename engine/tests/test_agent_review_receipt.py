"""Tests for agent review receipt artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_review_receipt import build_review_receipt, write_review_receipt


def _write_inputs(root: Path) -> None:
    selection = root / "strategy_selection"
    selection.mkdir(parents=True)
    (selection / "latest_agent_context.json").write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "rails": {"allowed_candidate_ids": ["candidate_a"]},
        "decision_readiness": {"status": "PASS", "issues": []},
        "focus_candidate_artifact_health": {"inputs_stale": False, "missing_execution_columns": []},
        "summary": {"candidate_count": 1, "eligible_count": 1},
        "meta_decision_trace": {"visible_regime": {"state": "risk_on", "probabilities": {"risk_on": 0.7}}},
        "selection_explanation": {"summary": "candidate_a is preferred in the test context"},
        "candidates": [{"candidate_id": "candidate_a"}],
    }))
    (selection / "latest_agent_pm_memo.md").write_text("# memo\n")
    (selection / "latest_agent_decision_guard.json").write_text(json.dumps({"status": "PASS"}))
    (selection / "agent_decision.json").write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "candidate_id": "candidate_a",
        "confidence": 0.8,
        "reason": "Candidate has a clean review receipt in the test context.",
    }))


def test_build_review_receipt_contains_hashes_and_context(tmp_path: Path):
    _write_inputs(tmp_path)

    receipt = build_review_receipt(tmp_path)

    assert receipt["status"] == "PASS"
    assert receipt["candidate_id"] == "candidate_a"
    assert receipt["file_hashes"]["context_sha256"]
    assert receipt["visible_regime"]["state"] == "risk_on"
    assert receipt["choice_explanation"]["summary"].startswith("candidate_a")


def test_write_review_receipt_outputs_json_and_markdown(tmp_path: Path):
    _write_inputs(tmp_path)

    receipt = write_review_receipt(tmp_path)

    assert Path(receipt["receipt_json"]).exists()
    assert Path(receipt["receipt_md"]).exists()
    assert "Svyable Agent Review Receipt" in Path(receipt["receipt_md"]).read_text()


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_build_review_receipt_contains_hashes_and_context(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_write_review_receipt_outputs_json_and_markdown(Path(tmp))
    print("AGENT REVIEW RECEIPT TESTS PASSED")
