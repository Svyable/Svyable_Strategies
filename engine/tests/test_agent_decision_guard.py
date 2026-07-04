"""Tests for pre-activation agent decision guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_decision_guard import validate_agent_decision, write_guard_report


def _write_context(root: Path) -> None:
    selection = root / "strategy_selection"
    selection.mkdir(parents=True)
    (selection / "latest_agent_context.json").write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "rails": {"allowed_candidate_ids": ["candidate_a", "hold_current"]},
        "decision_readiness": {"status": "PASS", "issues": []},
        "focus_candidate_artifact_health": {"inputs_stale": False, "missing_execution_columns": []},
        "candidates": [{"candidate_id": "candidate_a"}, {"candidate_id": "hold_current"}],
    }))


def test_guard_passes_hash_matched_allowed_decision(tmp_path: Path):
    _write_context(tmp_path)
    decision = tmp_path / "strategy_selection" / "agent_decision.json"
    decision.write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "candidate_id": "candidate_a",
        "confidence": 0.72,
        "reason": "Candidate has the strongest ready utility after review.",
    }))

    report = validate_agent_decision(tmp_path)

    assert report["status"] == "PASS"
    assert report["candidate_id"] == "candidate_a"
    assert report["decision_fingerprint"]


def test_guard_blocks_stale_hash_and_disallowed_candidate(tmp_path: Path):
    _write_context(tmp_path)
    decision = tmp_path / "strategy_selection" / "agent_decision.json"
    decision.write_text(json.dumps({
        "as_of": "2026-01-03",
        "candidate_set_hash": "wrong",
        "candidate_id": "not_allowed",
        "confidence": 1.2,
        "reason": "bad",
    }))

    report = validate_agent_decision(tmp_path)

    assert report["status"] == "BLOCK"
    assert any("as_of" in item for item in report["blockers"])
    assert any("candidate_set_hash" in item for item in report["blockers"])
    assert any("not in allowed" in item for item in report["blockers"])
    assert any("confidence" in item for item in report["blockers"])
    assert any("reason" in item for item in report["blockers"])


def test_guard_report_is_written(tmp_path: Path):
    _write_context(tmp_path)
    (tmp_path / "strategy_selection" / "agent_decision.json").write_text(json.dumps({
        "as_of": "2026-01-02",
        "candidate_set_hash": "hash123",
        "candidate_id": "hold_current",
        "confidence": 0.2,
        "reason": "Hold current while reviewing low-confidence state.",
    }))

    report = write_guard_report(tmp_path)

    assert report["status"] == "PASS"
    assert Path(report["report_path"]).exists()
    assert report["warnings"]


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_guard_passes_hash_matched_allowed_decision(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_guard_blocks_stale_hash_and_disallowed_candidate(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_guard_report_is_written(Path(tmp))
    print("AGENT DECISION GUARD TESTS PASSED")
