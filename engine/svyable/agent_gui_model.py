"""View-model helpers for the Selection Meta Harness GUI.

The functions here convert context/guard/receipt/audit artifacts into simple
rows that Streamlit can render. Keeping this logic outside Streamlit makes the
operator cockpit easier to test and keeps the GUI focused on presentation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


CRITICAL_PATHS = {
    "Context": "strategy_selection/latest_agent_context.json",
    "Memo": "strategy_selection/latest_agent_pm_memo.md",
    "Decision": "strategy_selection/agent_decision.json",
    "Guard": "strategy_selection/latest_agent_decision_guard.json",
    "Receipt": "strategy_selection/latest_agent_review_receipt.json",
    "Audit": "strategy_selection/latest_agent_review_audit.json",
}


def _status(value: Any, *, default: str = "PENDING") -> str:
    text = str(value or default).upper()
    if text in {"PASS", "BLOCK", "WARN", "PENDING", "OK"}:
        return text
    return text


def status_icon(status: Any) -> str:
    value = _status(status)
    if value in {"PASS", "OK"}:
        return "✅"
    if value == "BLOCK":
        return "🛑"
    if value == "WARN":
        return "⚠️"
    return "⏳"


def workflow_steps(
    context: dict[str, Any],
    guard: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a compact stepper for the human/agent PM review flow."""
    guard = guard or {}
    receipt = receipt or {}
    audit = audit or {}
    readiness = context.get("decision_readiness", {}) if context else {}
    rails = context.get("rails", {}) if context else {}
    allowed = rails.get("allowed_candidate_ids", []) or []
    return [
        {
            "step": "Context pack",
            "status": "PASS" if context else "PENDING",
            "detail": context.get("candidate_set_hash", "not generated") if context else "not generated",
            "next_action": "Review Selection Meta Harness" if context else "Run daily evaluate-only or agent pack",
        },
        {
            "step": "Decision readiness",
            "status": _status(readiness.get("status")) if context else "PENDING",
            "detail": f"{len(allowed)} allowed candidates",
            "next_action": readiness.get("next_step", "generate context"),
        },
        {
            "step": "Decision guard",
            "status": _status(guard.get("status")) if guard else "PENDING",
            "detail": guard.get("candidate_id", "no decision yet") if guard else "no report",
            "next_action": guard.get("next_step", "write or validate agent_decision.json") if guard else "Run guard",
        },
        {
            "step": "Review receipt",
            "status": _status(receipt.get("status")) if receipt else "PENDING",
            "detail": receipt.get("decision_fingerprint", "no receipt") if receipt else "no receipt",
            "next_action": receipt.get("next_step", "write review receipt") if receipt else "Write receipt",
        },
        {
            "step": "Integrity audit",
            "status": _status(audit.get("status")) if audit else "PENDING",
            "detail": f"{len(audit.get('file_checks', []) or [])} file checks" if audit else "no audit",
            "next_action": audit.get("next_step", "write integrity audit") if audit else "Write audit",
        },
    ]


def artifact_inventory(output_root: str | Path) -> list[dict[str, Any]]:
    """Return existence, size, and mtime rows for key PM review artifacts."""
    root = Path(output_root)
    rows: list[dict[str, Any]] = []
    for label, rel in CRITICAL_PATHS.items():
        path = root / rel
        exists = path.exists()
        stat = path.stat() if exists else None
        rows.append({
            "artifact": label,
            "exists": exists,
            "path": str(path),
            "size_bytes": stat.st_size if stat else 0,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else "",
        })
    return rows


def issue_summary(*reports: dict[str, Any]) -> dict[str, Any]:
    """Collect blockers and warnings across context, guard, receipt, and audit."""
    blockers: list[str] = []
    warnings: list[str] = []
    for report in reports:
        if not report:
            continue
        blockers.extend(str(item) for item in (report.get("blockers", []) or []))
        warnings.extend(str(item) for item in (report.get("warnings", []) or []))
        issues = ((report.get("decision_readiness", {}) or {}).get("issues", []) or [])
        blockers.extend(str(item) for item in issues)
    return {
        "status": "BLOCK" if blockers else ("WARN" if warnings else "PASS"),
        "blockers": blockers,
        "warnings": warnings,
    }


def recommended_next_step(steps: list[dict[str, Any]]) -> str:
    """Return the next incomplete PM workflow action."""
    for step in steps:
        if _status(step.get("status")) not in {"PASS", "OK"}:
            return str(step.get("next_action") or step.get("step"))
    return "Ready for canonical activation review"
