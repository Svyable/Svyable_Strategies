"""Review receipt writer for the Svyable PM harness.

The receipt freezes the validated decision, context identifiers, file hashes, and
operator checklist as a read-only review artifact. It does not create targets or
modify portfolio artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from svyable.agent_decision_guard import validate_agent_decision


def _file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def receipt_paths(output_root: str | Path) -> dict[str, Path]:
    root = Path(output_root) / "strategy_selection"
    return {
        "context": root / "latest_agent_context.json",
        "memo": root / "latest_agent_pm_memo.md",
        "decision": root / "agent_decision.json",
        "guard_report": root / "latest_agent_decision_guard.json",
        "receipt_json": root / "latest_agent_review_receipt.json",
        "receipt_md": root / "latest_agent_review_receipt.md",
    }


def build_review_receipt(output_root: str | Path) -> dict[str, Any]:
    paths = receipt_paths(output_root)
    guard = validate_agent_decision(output_root)
    context = _read_json(paths["context"])
    decision = _read_json(paths["decision"])
    trace = context.get("meta_decision_trace", {}) or {}
    return {
        "status": guard.get("status"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": guard.get("as_of"),
        "candidate_set_hash": guard.get("candidate_set_hash"),
        "candidate_id": guard.get("candidate_id"),
        "confidence": guard.get("confidence"),
        "decision_fingerprint": guard.get("decision_fingerprint"),
        "blockers": guard.get("blockers", []),
        "warnings": guard.get("warnings", []),
        "reason": decision.get("reason"),
        "context_summary": context.get("summary", {}),
        "readiness": context.get("decision_readiness", {}),
        "visible_regime": trace.get("visible_regime", {}),
        "choice_explanation": context.get("selection_explanation", {}),
        "file_hashes": {
            "context_sha256": _file_sha256(paths["context"]),
            "memo_sha256": _file_sha256(paths["memo"]),
            "decision_sha256": _file_sha256(paths["decision"]),
            "guard_report_sha256": _file_sha256(paths["guard_report"]),
        },
        "paths": {key: str(value) for key, value in paths.items()},
        "next_step": "review complete" if guard.get("status") == "PASS" else "resolve blockers",
    }


def render_review_receipt(receipt: dict[str, Any]) -> str:
    regime = receipt.get("visible_regime", {}) or {}
    explanation = receipt.get("choice_explanation", {}) or {}
    lines = [
        "# Svyable Agent Review Receipt",
        "",
        f"- Status: **{receipt.get('status')}**",
        f"- Generated: `{receipt.get('generated_at')}`",
        f"- Board date: `{receipt.get('as_of')}`",
        f"- Candidate hash: `{receipt.get('candidate_set_hash')}`",
        f"- Candidate: `{receipt.get('candidate_id')}`",
        f"- Confidence: `{receipt.get('confidence')}`",
        f"- Decision fingerprint: `{receipt.get('decision_fingerprint')}`",
        "",
        "## Review notes",
        str(receipt.get("reason") or ""),
        "",
        "## Choice explanation",
        str(explanation.get("summary") or "No explanation available."),
        "",
        "## Visible regime",
        f"- State: `{regime.get('state')}`",
        f"- Probabilities: `{regime.get('probabilities')}`",
        "",
        "## Blockers and warnings",
    ]
    blockers = receipt.get("blockers", []) or []
    warnings = receipt.get("warnings", []) or []
    lines.append(f"- Blockers: {len(blockers)}")
    lines.append(f"- Warnings: {len(warnings)}")
    lines.extend(f"  - {item}" for item in blockers + warnings)
    lines.extend(["", "## File hashes"])
    for key, value in (receipt.get("file_hashes", {}) or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def write_review_receipt(output_root: str | Path) -> dict[str, Any]:
    paths = receipt_paths(output_root)
    paths["receipt_json"].parent.mkdir(parents=True, exist_ok=True)
    receipt = build_review_receipt(output_root)
    paths["receipt_json"].write_text(json.dumps(receipt, indent=2, sort_keys=True))
    paths["receipt_md"].write_text(render_review_receipt(receipt))
    receipt["receipt_json"] = str(paths["receipt_json"])
    receipt["receipt_md"] = str(paths["receipt_md"])
    return receipt


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="svyable-agent-review-receipt")
    result.add_argument("--out", default="outputs")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    receipt = write_review_receipt(args.out)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
