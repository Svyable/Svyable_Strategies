"""Tests for review receipt integrity audit."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_review_audit import audit_review_receipt, write_review_audit


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_receipt_tree(root: Path) -> dict[str, Path]:
    selection = root / "strategy_selection"
    selection.mkdir(parents=True)
    paths = {
        "context": selection / "latest_agent_context.json",
        "memo": selection / "latest_agent_pm_memo.md",
        "decision": selection / "agent_decision.json",
        "guard_report": selection / "latest_agent_decision_guard.json",
        "receipt": selection / "latest_agent_review_receipt.json",
    }
    paths["context"].write_text(json.dumps({"summary": {"candidate_count": 1}}))
    paths["memo"].write_text("# memo\n")
    paths["decision"].write_text(json.dumps({"candidate_id": "candidate_a"}))
    paths["guard_report"].write_text(json.dumps({"status": "PASS"}))
    receipt = {
        "status": "PASS",
        "candidate_id": "candidate_a",
        "candidate_set_hash": "hash123",
        "decision_fingerprint": "fingerprint123",
        "paths": {key: str(path) for key, path in paths.items() if key != "receipt"},
        "file_hashes": {
            "context_sha256": _sha(paths["context"]),
            "memo_sha256": _sha(paths["memo"]),
            "decision_sha256": _sha(paths["decision"]),
            "guard_report_sha256": _sha(paths["guard_report"]),
        },
    }
    paths["receipt"].write_text(json.dumps(receipt))
    return paths


def test_review_audit_passes_when_hashes_match(tmp_path: Path):
    _write_receipt_tree(tmp_path)

    report = audit_review_receipt(tmp_path)

    assert report["status"] == "PASS"
    assert report["candidate_id"] == "candidate_a"
    assert all(item["status"] == "PASS" for item in report["file_checks"])


def test_review_audit_blocks_on_hash_mismatch(tmp_path: Path):
    paths = _write_receipt_tree(tmp_path)
    paths["decision"].write_text(json.dumps({"candidate_id": "candidate_b"}))

    report = audit_review_receipt(tmp_path)

    assert report["status"] == "BLOCK"
    assert any("hash mismatch" in item for item in report["blockers"])


def test_write_review_audit_persists_report(tmp_path: Path):
    _write_receipt_tree(tmp_path)

    report = write_review_audit(tmp_path)

    assert report["status"] == "PASS"
    assert Path(report["report_path"]).exists()


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_review_audit_passes_when_hashes_match(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_review_audit_blocks_on_hash_mismatch(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_write_review_audit_persists_report(Path(tmp))
    print("AGENT REVIEW AUDIT TESTS PASSED")
