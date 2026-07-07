"""Validate and activate the latest strategy-selection decision.

Activation is intentionally separate from candidate evaluation so an agent can
review the current day's immutable board before canonical Tastytrade weights are
emitted. A board can be activated only once.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
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


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_state(output_root: str | Path) -> dict[str, Any]:
    return _read_json_file(state_path(output_root))


def _require_agent_review_pass(
    board: pd.DataFrame,
    output_root: str | Path,
) -> dict[str, Any]:
    """Require the non-trading review chain to still validate the live decision.

    The Streamlit surface already exposes activation readiness, but activation is
    also reachable from CLI/direct Python. Recompute the guard and audit here so a
    stale PASS file cannot be replayed after ``agent_decision.json`` changes.
    """
    from svyable.agent_decision_guard import validate_agent_decision
    from svyable.agent_review_audit import audit_review_receipt

    root = Path(output_root)
    selection_root = root / "strategy_selection"
    board_as_of = str(board.iloc[0].get("as_of", ""))
    board_hash = str(board.iloc[0].get("candidate_set_hash", ""))
    guard = validate_agent_decision(root)
    chain = _read_json_file(selection_root / "latest_agent_review_chain.json")
    receipt = _read_json_file(selection_root / "latest_agent_review_receipt.json")
    audit = audit_review_receipt(root)

    blockers: list[str] = []
    if guard.get("status") != "PASS":
        blockers.append("decision guard is not PASS")
        blockers.extend(str(item) for item in guard.get("blockers", [])[:8])
    if chain.get("status") != "PASS":
        blockers.append("review chain is missing or not PASS")
        blockers.extend(str(item) for item in chain.get("blockers", [])[:8])
    if receipt.get("status") != "PASS":
        blockers.append("review receipt is missing or not PASS")
        blockers.extend(str(item) for item in receipt.get("blockers", [])[:8])
    if audit.get("status") != "PASS":
        blockers.append("review audit is not PASS")
        blockers.extend(str(item) for item in audit.get("blockers", [])[:8])

    if str(guard.get("as_of", "")) != board_as_of:
        blockers.append("guard date does not match the latest board")
    if str(guard.get("candidate_set_hash", "")) != board_hash:
        blockers.append("guard hash does not match the latest board")
    if receipt and str(receipt.get("as_of", "")) != board_as_of:
        blockers.append("review receipt date does not match the latest board")
    if receipt and str(receipt.get("candidate_set_hash", "")) != board_hash:
        blockers.append("review receipt hash does not match the latest board")
    if receipt and str(receipt.get("candidate_id", "")) != str(guard.get("candidate_id", "")):
        blockers.append("review receipt candidate does not match the current guarded decision")
    if audit and str(audit.get("candidate_set_hash", "")) != board_hash:
        blockers.append("review audit hash does not match the latest board")

    if blockers:
        unique_blockers = list(dict.fromkeys(blockers))
        raise RuntimeError(
            "Agent activation review has not passed: "
            + "; ".join(unique_blockers)
        )

    return {
        "guard": guard,
        "chain": chain,
        "receipt": receipt,
        "audit": audit,
    }


def _validated_agent_row(
    board: pd.DataFrame,
    output_root: str | Path,
) -> tuple[pd.Series, dict[str, Any]]:
    path = agent_decision_path(output_root)
    if not path.exists():
        raise FileNotFoundError(f"Agent mode requires a decision at {path}.")
    payload = json.loads(path.read_text())
    as_of = str(board.iloc[0]["as_of"])
    candidate_hash = str(board.iloc[0]["candidate_set_hash"])
    if payload.get("as_of") != as_of:
        raise RuntimeError("Agent decision date does not match the latest board.")
    if payload.get("candidate_set_hash") != candidate_hash:
        raise RuntimeError("Agent decision hash does not match the latest board.")
    candidate_id = str(payload.get("candidate_id", ""))
    matches = board[board["candidate_id"] == candidate_id]
    if matches.empty:
        raise RuntimeError("Agent selected a candidate not present on the board.")
    row = matches.iloc[0]
    if not bool(row["eligible"]):
        raise RuntimeError("Agent selected an ineligible candidate.")

    review = _require_agent_review_pass(board, output_root)
    guarded_candidate = str((review.get("guard") or {}).get("candidate_id", ""))
    if guarded_candidate != candidate_id:
        raise RuntimeError("Reviewed decision candidate does not match the agent decision.")
    receipt = review.get("receipt") or {}
    payload["_decision_fingerprint"] = receipt.get("decision_fingerprint")
    return row, payload


def _validated_planned_row(
    board_dir: Path,
    board: pd.DataFrame,
) -> tuple[pd.Series, dict[str, Any]]:
    path = board_dir / "selection.json"
    if not path.exists():
        raise FileNotFoundError("The latest board has no selection.json.")
    payload = json.loads(path.read_text())
    if str(payload.get("as_of")) != str(board.iloc[0]["as_of"]):
        raise RuntimeError("Planned selection date does not match the board.")
    if str(payload.get("candidate_set_hash")) != str(board.iloc[0]["candidate_set_hash"]):
        raise RuntimeError("Planned selection hash does not match the board.")
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


def _position_snapshot(
    root: Path,
    board: pd.DataFrame,
) -> tuple[pd.Series, str]:
    path = root / "strategy_selection" / "current_positions.json"
    if path.exists():
        payload = json.loads(path.read_text())
        if (
            str(payload.get("as_of")) == str(board.iloc[0]["as_of"])
            and str(payload.get("candidate_set_hash"))
            == str(board.iloc[0]["candidate_set_hash"])
        ):
            weights = pd.Series(payload.get("weights", {}), dtype=float)
            weights.index = weights.index.astype(str)
            return weights, str(payload.get("source", "position_snapshot"))
    return current_weights(root), "canonical_target"


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
        decision_fingerprint = payload.get("_decision_fingerprint")
    else:
        row, payload = _validated_planned_row(board_dir, board)
        source = str(payload.get("source", policy.mode))
        reason = str(payload.get("reason", "Validated planned selection."))[:1000]
        confidence = payload.get("agent_confidence")
        decision_fingerprint = payload.get("decision_fingerprint")

    activation_path = board_dir / "activation.json"
    if activation_path.exists():
        existing = json.loads(activation_path.read_text())
        if existing.get("candidate_id") == row.get("candidate_id"):
            return existing
        raise RuntimeError(
            "This candidate board was already activated with a different decision."
        )

    selected = row.to_dict()
    selected.update(
        {
            "source": source,
            "reason": reason,
            "agent_confidence": confidence,
            "decision_fingerprint": decision_fingerprint,
            "mode": policy.mode,
        }
    )
    held_weights, position_source = _position_snapshot(root, board)
    source_dir = _source_directory(board, row, state)
    tag = board_dir.name
    destination = root / CANONICAL_STRATEGY_ID / tag
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(
            f"Canonical destination already exists without activation record: {destination}"
        )
    shutil.copytree(source_dir, destination)

    if selected["action"] == "hold":
        held = (
            held_weights
            if selected["strategy_id"] != "cash"
            else pd.Series(dtype=float)
        )
        held[held.abs() > 1e-12].rename("weight").to_csv(
            destination / "weights_today.csv"
        )
        history_path = destination / "weights_history.csv"
        history = (
            pd.read_csv(history_path, index_col=0)
            if history_path.exists()
            else pd.DataFrame()
        )
        held_row = held.to_frame().T
        held_row.index = [str(row["as_of"])]
        pd.concat([history.iloc[:-1], held_row]).tail(63).to_csv(history_path)

    selected["current_position_source"] = position_source
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
        f"- Position source: {position_source}\n"
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
        "current_position_source": position_source,
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
    activation_path.write_text(
        json.dumps(activation, indent=2, sort_keys=True, default=str)
    )
    return activation
