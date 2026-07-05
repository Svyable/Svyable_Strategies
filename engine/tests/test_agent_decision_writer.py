"""Tests for guarded agent decision writer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_decision_writer import decision_template_from_context, write_agent_decision_from_context


def _write_context(root: Path) -> None:
    selection = root / "strategy_selection"
    selection.mkdir(parents=True)
    (selection / "latest_agent_context.json").write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "summary": {"top_eligible_candidate": "candidate_a"},
        "rails": {"allowed_candidate_ids": ["candidate_a", "hold_current"]},
        "decision_readiness": {"status": "PASS", "issues": []},
        "focus_candidate_artifact_health": {"inputs_stale": False, "missing_execution_columns": []},
        "candidates": [{"candidate_id": "candidate_a"}, {"candidate_id": "hold_current"}],
    }))


def test_template_uses_latest_context_hash_and_allowed_candidate(tmp_path: Path):
    _write_context(tmp_path)

    decision = decision_template_from_context(
        tmp_path,
        candidate_id="candidate_a",
        confidence=0.62,
        reason="Candidate passes review after checking the meta harness.",
    )

    assert decision["as_of"] == "2026-01-02"
    assert decision["candidate_set_hash"] == "hash123"
    assert decision["candidate_id"] == "candidate_a"
    assert decision["confidence"] == 0.62


def test_writer_persists_decision_and_runs_guard(tmp_path: Path):
    _write_context(tmp_path)

    result = write_agent_decision_from_context(
        tmp_path,
        candidate_id="hold_current",
        confidence=0.4,
        reason="Holding current after reviewing context and selecting the safe fallback.",
    )

    assert result["status"] == "PASS"
    assert Path(result["decision_path"]).exists()
    saved = json.loads(Path(result["decision_path"]).read_text())
    assert saved["candidate_id"] == "hold_current"
    assert result["guard"]["candidate_id"] == "hold_current"


def test_writer_rejects_disallowed_candidate(tmp_path: Path):
    _write_context(tmp_path)

    try:
        decision_template_from_context(
            tmp_path,
            candidate_id="not_allowed",
            confidence=0.5,
            reason="This candidate should be rejected by the guarded writer.",
        )
    except ValueError as exc:
        assert "not currently allowed" in str(exc)
    else:
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_template_uses_latest_context_hash_and_allowed_candidate(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_writer_persists_decision_and_runs_guard(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_writer_rejects_disallowed_candidate(Path(tmp))
    print("AGENT DECISION WRITER TESTS PASSED")
