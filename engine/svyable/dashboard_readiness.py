"""Agent and human readiness checks for the PM command center.

This is the operational checklist agents and humans need before trusting a live
portfolio action. It intentionally combines local research state, strategy-policy
coverage, daily execution artifacts, broker session state, and live quote health.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import broker_ready
from svyable.strategy_selection_service import StrategySelectionService

_BLOCK = "BLOCK"
_WARN = "WARN"
_PASS = "PASS"


def _gate(name: str, status: str, detail: str, owner: str = "system") -> dict[str, str]:
    return {"gate": name, "status": status, "detail": detail, "owner": owner}


def _execution_gate(service: DashboardService) -> dict[str, str]:
    try:
        execution = service.execution_inputs()
    except Exception as exc:
        return _gate("Execution inputs", _BLOCK, str(exc), "daily pipeline")
    artifact = execution.get("artifact_date") or "missing"
    expected = execution.get("expected_date") or "unknown"
    if execution.get("stale"):
        return _gate(
            "Execution inputs",
            _BLOCK,
            f"stale artifact {artifact}; expected {expected}",
            "daily pipeline",
        )
    return _gate("Execution inputs", _PASS, f"fresh artifact {artifact}", "daily pipeline")


def _quote_gate(market_frame: pd.DataFrame | None) -> dict[str, str]:
    if market_frame is None or market_frame.empty:
        return _gate("Live quotes", _WARN, "quote board not loaded yet", "broker")
    missing = int((~market_frame.get("quote_ok", pd.Series(False, index=market_frame.index)).astype(bool)).sum())
    spreads = pd.to_numeric(market_frame.get("spread_bps"), errors="coerce")
    wide = int((spreads.dropna() > 25.0).sum())
    if missing:
        return _gate("Live quotes", _BLOCK, f"{missing} symbols missing live quotes", "broker")
    if wide:
        return _gate("Live quotes", _WARN, f"{wide} symbols have spreads > 25 bps", "broker")
    return _gate("Live quotes", _PASS, f"{len(market_frame)} symbols quoted; spreads acceptable", "broker")


def build_readiness_snapshot(
    service: DashboardService,
    strategy_service: StrategySelectionService,
    settings: TastySettings,
    *,
    broker_snapshot: dict[str, Any] | None = None,
    market_frame: pd.DataFrame | None = None,
    ledger_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic PM readiness checklist for rendering and agent use."""
    gates: list[dict[str, str]] = []

    gates.append(
        _gate(
            "Broker credentials",
            _PASS if broker_ready(settings) else _BLOCK,
            "configured" if broker_ready(settings) else "missing Tastytrade refresh token, account, or client secret",
            "broker",
        )
    )
    if broker_snapshot is not None:
        gates.append(
            _gate(
                "Broker session",
                _PASS if bool(broker_snapshot.get("session_valid", True)) else _BLOCK,
                "session valid" if bool(broker_snapshot.get("session_valid", True)) else "session failed validation",
                "broker",
            )
        )
    else:
        gates.append(_gate("Broker session", _WARN, "broker snapshot not loaded", "broker"))

    strategy_snapshot = service.strategy_snapshot()
    run_dir = strategy_snapshot.get("run_dir")
    gates.append(
        _gate(
            "Strategy artifacts",
            _PASS if run_dir is not None else _BLOCK,
            f"latest run {run_dir}" if run_dir is not None else "no latest strategy run found",
            "daily pipeline",
        )
    )
    gates.append(_execution_gate(service))

    frontier = strategy_service.frontier_status()
    if frontier.get("is_incomplete_latest_board"):
        gates.append(_gate("Strategy frontier", _BLOCK, frontier.get("explanation", "frontier incomplete"), "PM selector"))
    elif int(frontier.get("board_candidate_count", 0)) <= 0:
        gates.append(_gate("Strategy frontier", _WARN, "no candidate board yet", "PM selector"))
    else:
        gates.append(
            _gate(
                "Strategy frontier",
                _PASS,
                f"board covers {frontier.get('board_candidate_count')}/{frontier.get('expected_candidate_count')} candidates",
                "PM selector",
            )
        )

    gates.append(_quote_gate(market_frame))

    health = (ledger_snapshot or service.ledger_snapshot()).get("health", {}) if ledger_snapshot is not None else {}
    critical = int(health.get("critical_7d", 0) or 0)
    warnings = int(health.get("warnings_7d", 0) or 0)
    if critical:
        gates.append(_gate("Ops warnings", _BLOCK, f"{critical} critical events in the last 7d", "operations"))
    elif warnings:
        gates.append(_gate("Ops warnings", _WARN, f"{warnings} warnings in the last 7d", "operations"))
    else:
        gates.append(_gate("Ops warnings", _PASS, "no recent warnings", "operations"))

    blocked = sum(1 for row in gates if row["status"] == _BLOCK)
    warned = sum(1 for row in gates if row["status"] == _WARN)
    passed = sum(1 for row in gates if row["status"] == _PASS)
    status = _BLOCK if blocked else _WARN if warned else _PASS
    headline = {
        _PASS: "Ready for broker preflight",
        _WARN: "Ready for review, not autopilot",
        _BLOCK: "Blocked — fix gates before action",
    }[status]
    return {
        "status": status,
        "headline": headline,
        "passed": passed,
        "warned": warned,
        "blocked": blocked,
        "gates": gates,
    }


def render_readiness_panel(
    service: DashboardService,
    strategy_service: StrategySelectionService,
    settings: TastySettings,
    *,
    broker_snapshot: dict[str, Any] | None = None,
    market_frame: pd.DataFrame | None = None,
    ledger_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render the checklist and return the same snapshot for agent workflows."""
    snapshot = build_readiness_snapshot(
        service,
        strategy_service,
        settings,
        broker_snapshot=broker_snapshot,
        market_frame=market_frame,
        ledger_snapshot=ledger_snapshot,
    )
    cols = st.columns(4)
    cols[0].metric("PM readiness", snapshot["status"], help=snapshot["headline"])
    cols[1].metric("Passed", snapshot["passed"])
    cols[2].metric("Warnings", snapshot["warned"])
    cols[3].metric("Blocked", snapshot["blocked"])
    if snapshot["status"] == _PASS:
        st.success(snapshot["headline"])
    elif snapshot["status"] == _WARN:
        st.warning(snapshot["headline"])
    else:
        st.error(snapshot["headline"])

    frame = pd.DataFrame(snapshot["gates"])
    st.dataframe(frame, use_container_width=True, hide_index=True)
    return snapshot
