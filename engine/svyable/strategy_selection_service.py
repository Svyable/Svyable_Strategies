"""Filesystem service for the strategy-selector GUI and PM agent."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from svyable.strategy_activation import activate_latest_selection
from svyable.strategy_blend import blend_frame, blend_spec_from_dict
from svyable.strategy_registry import get_strategy, registry_frame
from svyable.strategy_selector import (
    CANONICAL_STRATEGY_ID,
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

    def strategy_details(self, strategy_id: str) -> dict[str, Any]:
        spec = get_strategy(strategy_id)
        cfg = spec.build_config()
        return {
            "strategy_id": spec.strategy_id,
            "name": spec.display_name,
            "family": spec.family,
            "description": spec.description,
            "maturity": spec.maturity,
            "factor_names": list(spec.factor_names),
            "factor_count": len(spec.factor_names),
            "rebalance_interval_days": spec.rebalance_interval_days,
            "minimum_hold_days": spec.minimum_hold_days,
            "forecast_horizon_days": spec.forecast_horizon_days,
            "config_overrides": spec.config_overrides,
            "resolved_config_hash": cfg.config_hash(),
        }

    def policy(self) -> SelectionPolicy:
        return load_policy(self.output_root)

    def save_policy(self, policy: SelectionPolicy) -> Path:
        return save_policy(self.output_root, policy)

    def blend_registry(self) -> pd.DataFrame:
        return blend_frame()

    def add_custom_blend(self, payload: dict[str, Any]) -> Path:
        """Validate and persist a user-defined chimera with the policy. The
        blend definition is data; weights are still only ever materialized by
        the deterministic board evaluation."""
        from dataclasses import replace

        spec = blend_spec_from_dict(payload)   # raises on invalid definitions
        policy = self.policy()
        kept = tuple(
            item for item in policy.custom_blends
            if str(item.get("blend_id")) != spec.blend_id
        )
        updated = replace(policy, custom_blends=kept + (dict(payload),))
        return self.save_policy(updated)

    def remove_custom_blend(self, blend_id: str) -> Path:
        from dataclasses import replace

        policy = self.policy()
        kept = tuple(
            item for item in policy.custom_blends
            if str(item.get("blend_id")) != blend_id
        )
        return self.save_policy(replace(policy, custom_blends=kept))

    def latest_regime(self) -> pd.DataFrame:
        """Newest regime diagnostics. All candidates share the market panel,
        so any candidate's regime artifact describes the same tape."""
        paths = list(self.output_root.glob("candidate_*/*/regime.csv")) + list(
            self.output_root.glob(f"{CANONICAL_STRATEGY_ID}/*/regime.csv")
        )
        if not paths:
            return pd.DataFrame()
        newest = max(paths, key=lambda path: path.parent.name)
        frame = pd.read_csv(newest, index_col=0, parse_dates=True)
        frame.attrs["source"] = str(newest)
        return frame

    def pending_agent_decision(self) -> dict[str, Any]:
        """The agent's morning proposal awaiting approval, if it matches the
        latest board and has not been activated yet."""
        board_dir = self.latest_board_dir()
        path = agent_decision_path(self.output_root)
        if board_dir is None or not path.exists():
            return {}
        if (board_dir / "activation.json").exists():
            return {}
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
        board = self.latest_board()
        if board.empty:
            return {}
        first = board.iloc[0]
        if (
            str(payload.get("as_of")) != str(first["as_of"])
            or str(payload.get("candidate_set_hash")) != str(first["candidate_set_hash"])
        ):
            return {}
        matches = board[board["candidate_id"] == str(payload.get("candidate_id"))]
        if matches.empty:
            return {}
        row = matches.iloc[0]
        return {
            **payload,
            "eligible": bool(row["eligible"]),
            "name": row.get("name"),
            "family": row.get("family"),
            "components": row.get("components", ""),
            "expected_alpha_bps": row.get("expected_alpha_bps"),
            "one_way_turnover": row.get("one_way_turnover"),
            "estimated_cost_bps": row.get("estimated_cost_bps"),
            "utility_bps": row.get("utility_bps"),
        }

    def run_evaluation(
        self,
        *,
        start: str = "2020-01-01",
        provider: str = "yf",
        force: bool = True,
    ) -> dict[str, Any]:
        if provider not in {"yf", "tasty"}:
            raise ValueError("provider must be yf or tasty")
        command = [
            sys.executable,
            "-m",
            "svyable.strategy_daily",
            "--out",
            str(self.output_root),
            "--start",
            str(start),
            "--provider",
            provider,
            "--evaluate-only",
        ]
        if force:
            command.append("--force")
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        result = {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
            "command": command,
        }
        if completed.returncode != 0:
            raise RuntimeError(
                "Candidate evaluation failed.\n"
                + (completed.stderr or completed.stdout)[-4000:]
            )
        return result

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

Choose exactly one eligible `candidate_id`. The board contains single
registered strategies AND chimera blends (`chimera_*` rows; the `components`
column holds the exact composition). Consider expected alpha, estimated cost,
one-way turnover, current overlap, cadence, volatility, drawdown, the regime
throttle, and the cost-aware utility. A chimera earns its seat through
diversification and trade netting — pick one over a single strategy when the
blended book beats every component after costs. Prefer `hold_current` when no
candidate has a robust edge. Never edit weights or strategy code during this
review; your decision is a proposal that a human approves at activation.

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
            "blends": self.blend_registry(),
            "policy": asdict(policy),
            "state": self.state(),
            "board": self.latest_board(),
            "decision": self.latest_decision(),
            "pending_agent_decision": self.pending_agent_decision(),
            "policy_path": str(policy_path(self.output_root)),
            "agent_decision_path": str(agent_decision_path(self.output_root)),
        }
