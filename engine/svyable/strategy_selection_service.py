"""Filesystem service for the strategy-selector GUI and PM agent."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from svyable.strategy_activation import activate_latest_selection
from svyable.strategy_registry import registry_frame
from svyable.strategy_selector import (
    SelectionPolicy,
    agent_decision_path,
    load_policy,
    policy_path,
    save_policy,
    state_path,
)


class StrategySelectionService:
    def __init__(self, output_root: str | Path):
        self.output_root = Path(output_root)
        self.selection_root = self.output_root / "strategy_selection"

    def registry(self) -> pd.DataFrame:
        return registry_frame()

    def policy(self) -> SelectionPolicy:
        return load_policy(self.output_root)

    def save_policy(self, policy: SelectionPolicy) -> Path:
        return save_policy(self.output_root, policy)

    def state(self) -> dict[str, Any]:
        path = state_path(self.output_root)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}

    def latest_board_dir(self) -> Path | None:
        if not self.selection_root.exists():
            return None
        directories = sorted(
            path
            for path in self.selection_root.iterdir()
            if path.is_dir() and (path / "candidate_board.csv").exists()
        )
        return directories[-1] if directories else None

    def latest_board(self) -> pd.DataFrame:
        directory = self.latest_board_dir()
        if directory is None:
            return pd.DataFrame()
        return pd.read_csv(directory / "candidate_board.csv")

    def latest_decision(self) -> dict[str, Any]:
        directory = self.latest_board_dir()
        if directory is None or not (directory / "selection.json").exists():
            return {}
        return json.loads((directory / "selection.json").read_text())

    def save_agent_decision(
        self,
        *,
        candidate_id: str,
        reason: str,
        confidence: float,
    ) -> Path:
        board = self.latest_board()
        if board.empty:
            raise FileNotFoundError("No candidate board exists. Run the daily PM job first.")
        matches = board[board["candidate_id"] == candidate_id]
        if matches.empty:
            raise ValueError(f"Candidate {candidate_id!r} is not on the latest board.")
        if not bool(matches.iloc[0]["eligible"]):
            raise ValueError(f"Candidate {candidate_id!r} is not eligible.")
        payload = {
            "as_of": str(matches.iloc[0]["as_of"]),
            "candidate_set_hash": str(matches.iloc[0]["candidate_set_hash"]),
            "candidate_id": candidate_id,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "reason": str(reason).strip()[:1000],
        }
        path = agent_decision_path(self.output_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return path

    def activate_latest(self) -> dict[str, Any]:
        return activate_latest_selection(self.output_root)

    def agent_prompt(self) -> str:
        board_dir = self.latest_board_dir()
        if board_dir is None:
            return "Run the daily PM job to create a candidate board."
        return f"""Svyable strategy-selection review.

Read:
- {board_dir / 'candidate_board.csv'}
- {board_dir / 'selection.json'}
- {self.output_root / 'ledger.db'}

Choose exactly one eligible `candidate_id`. Consider expected alpha, estimated
cost, one-way turnover, current overlap, cadence, volatility, drawdown, and the
cost-aware utility. Prefer `hold_current` when no candidate has a robust edge.
Never edit weights or strategy code during this review.

Write JSON to:
{agent_decision_path(self.output_root)}

Required schema:
{{
  "as_of": "<candidate board as_of>",
  "candidate_set_hash": "<candidate board hash>",
  "candidate_id": "<eligible candidate_id>",
  "confidence": 0.0,
  "reason": "<concise PM rationale>"
}}

Then run:
python -m svyable.strategy_activate

Activation re-validates the date, board hash, eligibility, and registered
strategy before writing the canonical Tastytrade weights.
"""

    def snapshot(self) -> dict[str, Any]:
        policy = self.policy()
        return {
            "registry": self.registry(),
            "policy": asdict(policy),
            "state": self.state(),
            "board": self.latest_board(),
            "decision": self.latest_decision(),
            "policy_path": str(policy_path(self.output_root)),
            "agent_decision_path": str(agent_decision_path(self.output_root)),
        }
