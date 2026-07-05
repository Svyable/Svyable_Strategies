"""Integrity audit for Svyable agent review receipts.

The audit verifies that files referenced by the latest review receipt still match
the hashes captured at review time. It is a read-only check for operator review:
it does not change candidate boards, portfolio targets, or operating artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def latest_receipt_path(output_root: str | Path) -> Path:
    return Path(output_root) / "strategy_selection" / "latest_agent_review_receipt.json"


def audit_review_receipt(output_root: str | Path) -> dict[str, Any]:
    """Return PASS/BLOCK by comparing current files to receipt file hashes."""
    receipt_path = latest_receipt_path(output_root)
    receipt = _read_json(receipt_path)
    blockers: list[str] = []
    warnings: list[str] = []
    if not receipt:
        return {
            "status": "BLOCK",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "receipt_path": str(receipt_path),
            "blockers": ["latest review receipt is missing or malformed"],
            "warnings": [],
            "file_checks": [],
        }

    if receipt.get("status") != "PASS":
        blockers.append("receipt status is not PASS")

    paths = receipt.get("paths", {}) or {}
    expected = receipt.get("file_hashes", {}) or {}
    mapping = {
        "context_sha256": "context",
        "memo_sha256": "memo",
        "decision_sha256": "decision",
        "guard_report_sha256": "guard_report",
    }
    checks: list[dict[str, Any]] = []
    for hash_key, path_key in mapping.items():
        expected_hash = expected.get(hash_key)
        raw_path = paths.get(path_key)
        if not raw_path:
            blockers.append(f"receipt is missing path for {path_key}")
            checks.append({"name": path_key, "status": "BLOCK", "reason": "missing path"})
            continue
        path = Path(str(raw_path))
        actual_hash = _sha256(path)
        if actual_hash is None:
            blockers.append(f"referenced file is missing: {path}")
            checks.append({"name": path_key, "path": str(path), "status": "BLOCK", "reason": "missing file"})
            continue
        status = "PASS" if actual_hash == expected_hash else "BLOCK"
        if status != "PASS":
            blockers.append(f"hash mismatch for {path_key}")
        checks.append({
            "name": path_key,
            "path": str(path),
            "status": status,
            "expected_sha256": expected_hash,
            "actual_sha256": actual_hash,
        })

    decision_id = receipt.get("candidate_id")
    if not decision_id:
        warnings.append("receipt has no candidate_id")
    fingerprint = receipt.get("decision_fingerprint")
    if not fingerprint:
        warnings.append("receipt has no decision fingerprint")

    status = "PASS" if not blockers else "BLOCK"
    return {
        "status": status,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "receipt_path": str(receipt_path),
        "candidate_id": decision_id,
        "candidate_set_hash": receipt.get("candidate_set_hash"),
        "decision_fingerprint": fingerprint,
        "blockers": blockers,
        "warnings": warnings,
        "file_checks": checks,
        "next_step": "review artifacts unchanged" if status == "PASS" else "regenerate context/guard/receipt before proceeding",
    }


def write_review_audit(output_root: str | Path) -> dict[str, Any]:
    report = audit_review_receipt(output_root)
    path = Path(output_root) / "strategy_selection" / "latest_agent_review_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True))
    report["report_path"] = str(path)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="svyable-agent-review-audit")
    result.add_argument("--out", default="outputs")
    result.add_argument("--write", action="store_true")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    report = write_review_audit(args.out) if args.write else audit_review_receipt(args.out)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
