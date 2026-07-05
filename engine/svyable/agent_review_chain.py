"""One-click review chain runner for the Svyable PM harness.

This module orchestrates the non-trading review chain: optional context pack
refresh, decision guard, review receipt, and integrity audit. It never writes a
decision, never activates a portfolio, and never creates operating artifacts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from svyable.agent_decision_guard import write_guard_report
from svyable.agent_pm_harness import write_agent_pm_pack
from svyable.agent_review_audit import write_review_audit
from svyable.agent_review_receipt import write_review_receipt


def _stage(name: str, action: Callable[[], dict[str, Any] | Any]) -> dict[str, Any]:
    started = datetime.now().isoformat(timespec="seconds")
    try:
        result = action()
        payload = result if isinstance(result, dict) else {"result": str(result)}
        status = str(payload.get("status", "PASS")).upper()
        if status == "OK":
            status = "PASS"
        return {
            "name": name,
            "status": status,
            "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "payload": payload,
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "BLOCK",
            "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
        }


def run_review_chain(output_root: str | Path, *, refresh_context: bool = False) -> dict[str, Any]:
    """Run context/guard/receipt/audit review stages and persist a chain report."""
    root = Path(output_root)
    stages: list[dict[str, Any]] = []
    if refresh_context:
        stages.append(_stage("context_pack", lambda: write_agent_pm_pack(root).__dict__))
    else:
        context_path = root / "strategy_selection" / "latest_agent_context.json"
        stages.append({
            "name": "context_pack",
            "status": "PASS" if context_path.exists() else "BLOCK",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "payload": {"context_path": str(context_path), "exists": context_path.exists()},
        })
    stages.append(_stage("decision_guard", lambda: write_guard_report(root)))
    stages.append(_stage("review_receipt", lambda: write_review_receipt(root)))
    stages.append(_stage("integrity_audit", lambda: write_review_audit(root)))

    blockers = []
    for item in stages:
        if item.get("status") != "PASS":
            blockers.append(item.get("name"))
    report = {
        "status": "PASS" if not blockers else "BLOCK",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_root": str(root),
        "refresh_context": bool(refresh_context),
        "blockers": blockers,
        "stages": stages,
        "next_step": "canonical activation review" if not blockers else "resolve blocked review stages",
    }
    path = root / "strategy_selection" / "latest_agent_review_chain.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    report["report_path"] = str(path)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="svyable-agent-review-chain")
    result.add_argument("--out", default="outputs")
    result.add_argument("--refresh-context", action="store_true")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    report = run_review_chain(args.out, refresh_context=args.refresh_context)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
