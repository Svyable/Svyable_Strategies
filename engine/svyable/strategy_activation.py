"""Validate and activate the latest strategy-selection decision.

Activation is intentionally separate from candidate evaluation so an agent can
review the current day's immutable board before the canonical Tastytrade weights
are emitted.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from svyable.strategy_selector import (
    CANONICAL_STRATEGY_ID,
    agent_decision_path,
    current_weights,
    load_policy,
    state_path,
)


def latest_board_dir(output_root: str | Path) -> Path:
    root = Path(output_root) / "strategy_selection"
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "candidate_board.csv").exists()
    ) if root.exists() else []
    if not candidates:
        raise FileNotFoundError("No strategy candidate board exists.")
    return candidates[-1]


def _read_state(output_root: str | Path) -> dict[str, Any]:
    path = state_path(output_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _validated_agent_row(
    board: pd.DataFrame,
    output_root: str | Path,
) -> tuple[pd.Series, dict[str, Any]]:
    path = agent_decision_path(output_root)
    if not path.exists():
        raise FileNotFoundError(
            f"Agent mode requires a decision at {path}."
        )
    payload = json.loads(path.read_text())
    as_of = str(board.iloc[0]["as_of"])
    candidate_hash = str(board.iloc[0]["candidate_set_hash"])
    if payload.get("as_of") != as_of:
        raise RuntimeError("Agent decision date does not match the latest board.")
    if payload.get("candidate_set_hash") != candidate_hash:
        raise RuntimeError("Agent decision hash does not match the latest board.")
    matches = board[board["candidate_id"] == str(payload.get("candidate_id", ""))]
    if matches.empty:
        raise RuntimeError("Agent selected a candidate not present on the board.")
    row = matches.iloc[0]
    if not bool(row["eligible"]):
        raise RuntimeError("Agent selected an ineligible candidate.")
    return row, payload


def _validated_planned_row(board_dir: Path, board: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    path = board_dir / "selection.json"
    if not path.exists():
        raise FileNotFoundError("The latest board has no selection.json.")
    payload = json.loads(path.read_text())
    matches = board[board["candidate_id"] == str(payload.get("candidate_id", ""))]
    if matches.empty:
        raise RuntimeError("Planned selection is not present on the latest board.")
    row = matches.iloc[0]
    if not bool(row["eligible"]):
        raise RuntimeError("Planned selection is no longer eligible.")
    return row, payload


def _source_directory(
    board: pd.DataFrame,
    row: pd.Series,
    state: dict[str, Any],
) -> Path:
    output = str(row.get("output_dir", ""))
    if output:
        path = Path(output)
        if path.exists():
            return path

    current_strategy = state.get("selected_strategy_id")
    if current_strategy and current_strategy != "cash":
        matches = board[
            (board["strategy_id"] == current_strategy)
            & (board["action"] == "rebalance")
        ]
        if not matches.empty:
            path = Path(str(matches.iloc[0]["output_dir"]))
            if path.exists():
                return path

    fallback = board[board["action"] == "rebalance"]
    for value in fallback["output_dir"].astype(str):
        path = Path(value)
        if value and path.exists():
            return path
    raise RuntimeError("No candidate artifact directory is available for activation.")


def activate_latest_selection(output_root: str | Path) -> dict[str, Any]:
    root = Path(output_root)
    board_dir = latest_board_dir(root)
    board = pd.read_csv(board_dir / "candidate_board.csv")
    if board.empty:
        raise RuntimeError("Latest candidate board is empty.")
    policy = load_policy(root)
    state = _read_state(root)

    if policy.mode == "agent":
        row, payload = _validated_agent_row(board, root)
        source = "agent"
        reason = str(payload.get("reason", "Agent-selected eligible strategy."))[:1000]
        confidence = payload.get("confidence")
    else:
        row, payload = _validated_planned_row(board_dir, board)
        source = str(payload.get("source", policy.mode))
        reason = str(payload.get("reason", "Validated planned selection."))[:1000]
        confidence = payload.get("agent_confidence")

    selected = row.to_dict()
    selected.update(
        {
            "source": source,
            "reason": reason,
            "agent_confidence": confidence,
            "mode": policy.mode,
        }
    )
    source_dir = _source_directory(board, row, state)
    tag = board_dir.name
    destination = root / CANONICAL_STRATEGY_ID / tag
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_dir, destination)

    current = current_weights(root)
    if selected["action"] == "hold":
        held = current if selected["strategy_id"] != "cash" else pd.Series(dtype=float)
        held[held.abs() > 1e-12].rename("weight").to_csv(
            destination / "weights_today.csv"
        )
        history_path = destination / "weights_history.csv"
        history = pd.read_csv(history_path, index_col=0) if history_path.exists() else pd.DataFrame()
        held_row = held.to_frame().T
        held_row.index = [str(row["as_of"])]
        pd.concat([history.iloc[:-1], held_row]).tail(63).to_csv(history_path)

    meta_path = destination / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta["strategy_id"] = CANONICAL_STRATEGY_ID
    meta["selected_strategy_id"] = selected["strategy_id"]
    meta["selection"] = {
        key: value
        for key, value in selected.items()
        if key != "output_dir"
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True, default=str))

    report_path = destination / "morning_report.md"
    existing = report_path.read_text() if report_path.exists() else ""
    existing += (
        "\n\n## Strategy activation\n\n"
        f"- Strategy: **{selected['strategy_id']}**\n"
        f"- Action: **{selected['action']}**\n"
        f"- Source: {source}\n"
        f"- Expected alpha: {selected.get('expected_alpha_bps')} bps\n"
        f"- One-way turnover: {float(selected.get('one_way_turnover', 0.0)):.1%}\n"
        f"- Estimated cost: {selected.get('estimated_cost_bps')} bps\n"
        f"- Reason: {reason}\n"
        f"- Candidate hash: `{selected.get('candidate_set_hash')}`\n"
    )
    report_path.write_text(existing)

    as_of = str(row["as_of"])
    new_state = {
        "selected_strategy_id": selected["strategy_id"],
        "selected_action": selected["action"],
        "selected_at": (
            state.get("selected_at")
            if selected["action"] == "hold" and state.get("selected_at")
            else as_of
        ),
        "last_rebalanced_at": (
            as_of
            if selected["action"] == "rebalance"
            else state.get("last_rebalanced_at")
        ),
        "candidate_set_hash": selected.get("candidate_set_hash"),
        "canonical_output_dir": str(destination),
        "source": source,
        "reason": reason,
        "activated_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new_state, indent=2, sort_keys=True, default=str))

    activation = {
        **selected,
        "canonical_output_dir": str(destination),
        "activated_at": new_state["activated_at"],
    }
    (board_dir / "activation.json").write_text(
        json.dumps(activation, indent=2, sort_keys=True, default=str)
    )
    return activation
