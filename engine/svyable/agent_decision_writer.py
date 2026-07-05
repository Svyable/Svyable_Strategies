"""Guarded writer for the small agent decision artifact.

Humans should not have to hand-edit date/hash fields. This module writes
``strategy_selection/agent_decision.json`` from the latest context pack, verifies
that the candidate is currently allowed, and immediately runs the decision guard.
It never writes weights, quantities, or operating artifacts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from svyable.agent_decision_guard import validate_agent_decision


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing context file: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed json: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"json root must be object: {path}")
    return data


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc
    if number < 0.0 or number > 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return number


def latest_context_path(output_root: str | Path) -> Path:
    return Path(output_root) / "strategy_selection" / "latest_agent_context.json"


def decision_path(output_root: str | Path) -> Path:
    return Path(output_root) / "strategy_selection" / "agent_decision.json"


def decision_template_from_context(
    output_root: str | Path,
    *,
    candidate_id: str | None = None,
    confidence: float = 0.0,
    reason: str = "Review pending.",
    operator: str = "human_pm",
) -> dict[str, Any]:
    """Build a hash-matched decision object from the latest context."""
    context = _read_json(latest_context_path(output_root))
    allowed = [str(item) for item in (context.get("rails", {}) or {}).get("allowed_candidate_ids", [])]
    if not allowed:
        raise ValueError("latest context has no allowed candidate IDs")
    selected = str(candidate_id or context.get("summary", {}).get("top_eligible_candidate") or allowed[0])
    if selected not in allowed:
        raise ValueError(f"candidate_id is not currently allowed: {selected}")
    clean_reason = str(reason or "").strip()
    if len(clean_reason) < 10:
        raise ValueError("reason must be at least 10 characters")
    return {
        "as_of": str(context.get("as_of", "")),
        "candidate_set_hash": str(context.get("candidate_set_hash", "")),
        "candidate_id": selected,
        "confidence": _confidence(confidence),
        "reason": clean_reason,
        "operator": str(operator or "human_pm"),
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "writer": "svyable.agent_decision_writer",
    }


def write_agent_decision_from_context(
    output_root: str | Path,
    *,
    candidate_id: str | None = None,
    confidence: float = 0.0,
    reason: str = "Review pending.",
    operator: str = "human_pm",
) -> dict[str, Any]:
    """Write a safe decision artifact and return its guard report."""
    decision = decision_template_from_context(
        output_root,
        candidate_id=candidate_id,
        confidence=confidence,
        reason=reason,
        operator=operator,
    )
    path = decision_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision, indent=2, sort_keys=True))
    guard = validate_agent_decision(output_root)
    return {
        "status": guard.get("status"),
        "decision_path": str(path),
        "decision": decision,
        "guard": guard,
        "next_step": guard.get("next_step"),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="svyable-agent-decide")
    result.add_argument("--out", default="outputs")
    result.add_argument("--candidate", required=True)
    result.add_argument("--confidence", type=float, default=0.0)
    result.add_argument("--reason", required=True)
    result.add_argument("--operator", default="human_pm")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    result = write_agent_decision_from_context(
        args.out,
        candidate_id=args.candidate,
        confidence=args.confidence,
        reason=args.reason,
        operator=args.operator,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
