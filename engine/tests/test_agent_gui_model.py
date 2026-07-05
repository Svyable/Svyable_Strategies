"""Tests for Selection Meta Harness GUI view-model helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_gui_model import artifact_inventory, issue_summary, recommended_next_step, status_icon, workflow_steps


def test_workflow_steps_and_next_action_are_deterministic():
    context = {
        "candidate_set_hash": "hash123",
        "rails": {"allowed_candidate_ids": ["candidate_a"]},
        "decision_readiness": {"status": "PASS", "next_step": "prepare decision artifact"},
    }
    guard = {"status": "BLOCK", "candidate_id": "candidate_a", "next_step": "fix decision"}

    steps = workflow_steps(context, guard, {}, {})

    assert steps[0]["status"] == "PASS"
    assert steps[2]["status"] == "BLOCK"
    assert recommended_next_step(steps) == "fix decision"
    assert status_icon("PASS") == "✅"
    assert status_icon("BLOCK") == "🛑"


def test_artifact_inventory_reports_existing_files(tmp_path: Path):
    selection = tmp_path / "strategy_selection"
    selection.mkdir()
    (selection / "latest_agent_context.json").write_text(json.dumps({"ok": True}))

    rows = artifact_inventory(tmp_path)
    by_name = {row["artifact"]: row for row in rows}

    assert by_name["Context"]["exists"] is True
    assert by_name["Decision"]["exists"] is False
    assert by_name["Context"]["size_bytes"] > 0


def test_issue_summary_collects_blockers_and_warnings():
    summary = issue_summary(
        {"decision_readiness": {"issues": ["stale context"]}},
        {"blockers": ["bad hash"], "warnings": ["low confidence"]},
    )

    assert summary["status"] == "BLOCK"
    assert "bad hash" in summary["blockers"]
    assert "stale context" in summary["blockers"]
    assert "low confidence" in summary["warnings"]


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    test_workflow_steps_and_next_action_are_deterministic()
    with TemporaryDirectory() as tmp:
        test_artifact_inventory_reports_existing_files(Path(tmp))
    test_issue_summary_collects_blockers_and_warnings()
    print("AGENT GUI MODEL TESTS PASSED")
