"""Pre-activation guard for agent PM decisions.

The guard validates the small agent decision artifact against the latest context
pack before activation. It does not activate portfolios and does not create
orders; it returns a PASS/BLOCK report that can be shown in the GUI, logged, or
used by automation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = ("as_of", "candidate_set_hash", "candidate_id", "confidence", "reason")


@dataclass(frozen=True)
class GuardPaths:
    context_path: Path
    decision_path: Path
    report_path: Path


def _read_json(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists():
        return {}, [f"missing file: {path}"]
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {}, [f"malformed json: {path}: {exc}"]
    if not isinstance(data, dict):
        return {}, [f"json root must be object: {path}"]
    return data, []


def _paths(output_root: str | Path, decision_path: str | Path | None = None) -> GuardPaths:
    root = Path(output_root)
    selection_root = root / "strategy_selection"
    return GuardPaths(
        context_path=selection_root / "latest_agent_context.json",
        decision_path=Path(decision_path) if decision_path else selection_root / "agent_decision.json",
        report_path=selection_root / "latest_agent_decision_guard.json",
    )


def _decision_fingerprint(decision: dict[str, Any]) -> str:
    canonical = {field: decision.get(field) for field in REQUIRED_FIELDS}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _confidence(value: Any) -> tuple[float | None, str | None]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, "confidence must be numeric"
    if number < 0.0 or number > 1.0:
        return number, "confidence must be between 0 and 1"
    return number, None


def validate_agent_decision(
    output_root: str | Path,
    *,
    decision_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate ``agent_decision.json`` against the latest context pack."""
    paths = _paths(output_root, decision_path)
    context, context_errors = _read_json(paths.context_path)
    decision, decision_errors = _read_json(paths.decision_path)
    blockers: list[str] = []
    warnings: list[str] = []
    blockers.extend(context_errors)
    blockers.extend(decision_errors)

    if blockers:
        return {
            "status": "BLOCK",
            "blockers": blockers,
            "warnings": warnings,
            "context_path": str(paths.context_path),
            "decision_path": str(paths.decision_path),
        }

    missing = [field for field in REQUIRED_FIELDS if field not in decision]
    if missing:
        blockers.append("decision missing required fields: " + ", ".join(missing))

    readiness = context.get("decision_readiness", {}) or {}
    if readiness.get("status") != "PASS":
        blockers.append("context decision_readiness is not PASS")
        issues = readiness.get("issues", []) or []
        blockers.extend(str(issue) for issue in issues)

    expected_as_of = str(context.get("as_of", ""))
    expected_hash = str(context.get("candidate_set_hash", ""))
    if str(decision.get("as_of", "")) != expected_as_of:
        blockers.append("decision as_of does not match latest context")
    if str(decision.get("candidate_set_hash", "")) != expected_hash:
        blockers.append("decision candidate_set_hash does not match latest context")

    allowed = [str(item) for item in (context.get("rails", {}) or {}).get("allowed_candidate_ids", [])]
    candidate_id = str(decision.get("candidate_id", ""))
    if candidate_id not in allowed:
        blockers.append("decision candidate_id is not in allowed_candidate_ids")

    confidence, confidence_error = _confidence(decision.get("confidence"))
    if confidence_error:
        blockers.append(confidence_error)
    reason = str(decision.get("reason", "")).strip()
    if len(reason) < 10:
        blockers.append("decision reason is too short")

    health = context.get("focus_candidate_artifact_health", {}) or {}
    if health.get("inputs_stale"):
        blockers.append("focus execution inputs are stale")
    if health.get("missing_execution_columns"):
        blockers.append("focus execution artifact is missing required columns")

    candidate_rows = context.get("candidates", []) or []
    candidate_ids_in_context = {str(row.get("candidate_id", "")) for row in candidate_rows}
    if candidate_id and candidate_id not in candidate_ids_in_context:
        warnings.append("candidate is allowed but not present in truncated context candidate table")

    if confidence is not None and confidence < 0.25:
        warnings.append("low confidence decision; human PM should review carefully")

    status = "PASS" if not blockers else "BLOCK"
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "context_path": str(paths.context_path),
        "decision_path": str(paths.decision_path),
        "as_of": expected_as_of,
        "candidate_set_hash": expected_hash,
        "candidate_id": candidate_id,
        "confidence": confidence,
        "decision_fingerprint": _decision_fingerprint(decision) if not missing else None,
        "next_step": "activate latest selection" if status == "PASS" else "fix decision/context before activation",
    }


def write_guard_report(
    output_root: str | Path,
    *,
    decision_path: str | Path | None = None,
) -> dict[str, Any]:
    report = validate_agent_decision(output_root, decision_path=decision_path)
    paths = _paths(output_root, decision_path)
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    report["report_path"] = str(paths.report_path)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="svyable-agent-decision-guard")
    result.add_argument("--out", default="outputs")
    result.add_argument("--decision", default=None, help="optional explicit decision json path")
    result.add_argument("--write", action="store_true", help="write latest_agent_decision_guard.json")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    report = write_guard_report(args.out, decision_path=args.decision) if args.write else validate_agent_decision(args.out, decision_path=args.decision)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
