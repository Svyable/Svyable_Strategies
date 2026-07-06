"""Actionable candidate-board decision scorecard.

This layer does not create a new optimizer. It translates the already-computed
candidate board into plain PM language so the human can quickly see which plays
clear the hold-current hurdle, which are reviewable, and which are blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DecisionThresholds:
    go_edge_bps: float = 2.0
    review_edge_bps: float = 0.0
    max_turnover: float = 0.35
    max_drawdown: float = 0.15
    high_vol: float = 0.35
    low_overlap: float = 0.25


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _num(value: object, default: float = np.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _fmt_bps(value: object) -> str:
    return f"{_num(value, 0.0):.2f} bps"


def _fmt_pct(value: object) -> str:
    number = _num(value, np.nan)
    return "n/a" if not np.isfinite(number) else f"{number:.1%}"


def _hold_utility(board: pd.DataFrame) -> float:
    if board.empty or "candidate_id" not in board.columns:
        return 0.0
    hold = board[board["candidate_id"].astype(str) == "hold_current"]
    if hold.empty:
        return 0.0
    return _num(hold.iloc[0].get("utility_bps"), 0.0)


def _risk_flags(row: pd.Series, thresholds: DecisionThresholds) -> list[str]:
    flags: list[str] = []
    if _truthy(row.get("kill_switch", False)):
        flags.append("kill switch")
    turnover = _num(row.get("one_way_turnover"), 0.0)
    if turnover > thresholds.max_turnover:
        flags.append("high turnover")
    drawdown = abs(_num(row.get("recent_max_drawdown"), 0.0))
    if drawdown > thresholds.max_drawdown:
        flags.append("drawdown risk")
    vol = _num(row.get("recent_vol"), 0.0)
    if vol > thresholds.high_vol:
        flags.append("high vol")
    overlap = _num(row.get("current_overlap"), np.nan)
    action = str(row.get("action", "")).lower()
    if np.isfinite(overlap) and overlap < thresholds.low_overlap and action in {"switch", "rebalance"}:
        flags.append("low overlap")
    if _truthy(row.get("hold_lock", False)):
        flags.append("hold lock")
    if not _truthy(row.get("cadence_due", True)):
        flags.append("cadence not due")
    if not _truthy(row.get("rebalance_required", True)) and action not in {"hold", ""}:
        flags.append("rebalance not required")
    return flags


def _play_call(row: pd.Series, edge_bps: float, flags: list[str], thresholds: DecisionThresholds) -> str:
    candidate_id = str(row.get("candidate_id", ""))
    eligible = _truthy(row.get("eligible", False))
    if candidate_id == "hold_current":
        return "HOLD BASELINE"
    if not eligible or "kill switch" in flags:
        return "BLOCK"
    if edge_bps >= thresholds.go_edge_bps and not flags:
        return "GREENLIGHT"
    if edge_bps >= thresholds.review_edge_bps:
        return "REVIEW"
    return "HOLD CURRENT"


def _risk_points(row: pd.Series, flags: list[str]) -> float:
    turnover = max(0.0, _num(row.get("one_way_turnover"), 0.0))
    drawdown = abs(_num(row.get("recent_max_drawdown"), 0.0))
    vol = max(0.0, _num(row.get("recent_vol"), 0.0))
    cost = max(0.0, _num(row.get("estimated_cost_bps"), 0.0)) / 100.0
    return round(100.0 * (0.35 * turnover + 0.25 * drawdown + 0.20 * vol + 0.20 * cost) + 4.0 * len(flags), 2)


def build_decision_scorecard(
    board: pd.DataFrame,
    thresholds: DecisionThresholds | None = None,
) -> pd.DataFrame:
    """Return an actionable PM scorecard for a candidate board."""
    thresholds = thresholds or DecisionThresholds()
    if board.empty:
        return pd.DataFrame()
    hold_utility = _hold_utility(board)
    rows: list[dict[str, Any]] = []
    for _, row in board.iterrows():
        utility = _num(row.get("utility_bps"), 0.0)
        edge = utility - hold_utility
        flags = _risk_flags(row, thresholds)
        call = _play_call(row, edge, flags, thresholds)
        risk_points = _risk_points(row, flags)
        conviction = edge - risk_points * 0.05
        rows.append(
            {
                "candidate_id": str(row.get("candidate_id", "")),
                "name": row.get("name", row.get("candidate_id", "")),
                "family": row.get("family", ""),
                "play_call": call,
                "eligible": _truthy(row.get("eligible", False)),
                "edge_vs_hold_bps": round(edge, 3),
                "utility_bps": round(utility, 3),
                "net_expected_alpha_bps": round(_num(row.get("net_expected_alpha_bps", row.get("expected_alpha_bps")), 0.0), 3),
                "estimated_cost_bps": round(_num(row.get("estimated_cost_bps"), 0.0), 3),
                "one_way_turnover": round(_num(row.get("one_way_turnover"), 0.0), 4),
                "current_overlap": round(_num(row.get("current_overlap"), np.nan), 4),
                "recent_vol": round(_num(row.get("recent_vol"), np.nan), 4),
                "recent_max_drawdown": round(_num(row.get("recent_max_drawdown"), np.nan), 4),
                "risk_points": risk_points,
                "conviction_score": round(conviction, 3),
                "risk_flags": ", ".join(flags) if flags else "clear",
                "action": row.get("action", ""),
            }
        )
    frame = pd.DataFrame(rows)
    order = {"GREENLIGHT": 0, "REVIEW": 1, "HOLD CURRENT": 2, "HOLD BASELINE": 3, "BLOCK": 4}
    frame["_order"] = frame["play_call"].map(order).fillna(9).astype(int)
    frame = frame.sort_values(["_order", "conviction_score", "utility_bps"], ascending=[True, False, False])
    return frame.drop(columns=["_order"]).reset_index(drop=True)


def best_play(scorecard: pd.DataFrame) -> dict[str, Any]:
    """Top non-baseline actionable play, falling back to hold current."""
    if scorecard.empty:
        return {"play_call": "NO BOARD", "candidate_id": "", "next_action": "Run candidate evaluation"}
    actionable = scorecard[scorecard["play_call"].isin(["GREENLIGHT", "REVIEW"])]
    row = (actionable if not actionable.empty else scorecard).iloc[0].to_dict()
    call = str(row.get("play_call", ""))
    if call == "GREENLIGHT":
        row["next_action"] = "Review memo, then write guarded decision"
    elif call == "REVIEW":
        row["next_action"] = "Inspect playbook and risk flags before deciding"
    elif call in {"HOLD CURRENT", "HOLD BASELINE"}:
        row["next_action"] = "Hold current book unless PM evidence says otherwise"
    elif call == "BLOCK":
        row["next_action"] = "Resolve blockers; do not activate this candidate"
    else:
        row["next_action"] = "Run candidate evaluation"
    return row


def decision_reason(row: dict[str, Any]) -> str:
    """Plain-English guarded-decision rationale draft for the selected play."""
    candidate = str(row.get("candidate_id", ""))
    call = str(row.get("play_call", ""))
    flags = str(row.get("risk_flags", "clear"))
    if call == "GREENLIGHT":
        lead = "Approved for guarded review"
    elif call == "REVIEW":
        lead = "Reviewable candidate"
    elif call == "BLOCK":
        lead = "Blocked candidate"
    else:
        lead = "Hold-current preference"
    return (
        f"{lead}: {candidate}. Scorecard call={call}; edge versus hold is "
        f"{_fmt_bps(row.get('edge_vs_hold_bps'))}, utility is {_fmt_bps(row.get('utility_bps'))}, "
        f"net expected alpha is {_fmt_bps(row.get('net_expected_alpha_bps'))}, estimated cost is "
        f"{_fmt_bps(row.get('estimated_cost_bps'))}, one-way turnover is {_fmt_pct(row.get('one_way_turnover'))}, "
        f"current overlap is {_fmt_pct(row.get('current_overlap'))}, recent drawdown is "
        f"{_fmt_pct(row.get('recent_max_drawdown'))}, and risk flags are {flags}."
    )


def render_decision_ticket(scorecard: pd.DataFrame) -> str:
    """Markdown ticket for the human PM to review before writing a guarded decision."""
    top = best_play(scorecard)
    lines = [
        "# Svyable PM decision ticket",
        "",
        "This ticket summarizes the latest candidate-board scorecard. It is a review aid, not an order ticket.",
        "",
        "## Recommended next action",
        "",
        f"- candidate: `{top.get('candidate_id', '')}`",
        f"- call: **{top.get('play_call', '')}**",
        f"- next action: {top.get('next_action', '')}",
        f"- edge vs hold: {_fmt_bps(top.get('edge_vs_hold_bps'))}",
        f"- risk flags: {top.get('risk_flags', 'clear')}",
        "",
        "## Draft guarded-decision rationale",
        "",
        decision_reason(top),
        "",
        "## Scorecard",
        "",
        "| Candidate | Call | Edge vs hold | Utility | Cost | Turnover | Overlap | Drawdown | Flags |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for _, row in scorecard.iterrows():
        rec = row.to_dict()
        lines.append(
            f"| `{rec.get('candidate_id', '')}` | {rec.get('play_call', '')} | "
            f"{_fmt_bps(rec.get('edge_vs_hold_bps'))} | {_fmt_bps(rec.get('utility_bps'))} | "
            f"{_fmt_bps(rec.get('estimated_cost_bps'))} | {_fmt_pct(rec.get('one_way_turnover'))} | "
            f"{_fmt_pct(rec.get('current_overlap'))} | {_fmt_pct(rec.get('recent_max_drawdown'))} | "
            f"{rec.get('risk_flags', 'clear')} |"
        )
    lines += [
        "",
        "## Rails",
        "",
        "Only write a guarded decision from an allowed candidate ID and matching latest board hash. Run the guard, receipt, and audit before activation.",
    ]
    return "\n".join(lines) + "\n"
