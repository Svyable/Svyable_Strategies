"""Regression tests for strategy-frontier observability."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.strategy_blend import default_blend_ids
from svyable.strategy_registry import default_strategy_ids
from svyable.strategy_selection_service import StrategySelectionService
from svyable.strategy_selector import SelectionPolicy, save_policy


def _write_tiny_board(root: Path) -> None:
    board_dir = root / "strategy_selection" / "20260702_073000"
    board_dir.mkdir(parents=True)
    pd.DataFrame([
        {
            "candidate_id": "q23_hybrid_alpha",
            "strategy_id": "q23_hybrid_alpha",
            "action": "rebalance",
            "eligible": True,
            "expected_alpha_bps": 8.0,
            "one_way_turnover": 0.15,
            "estimated_cost_bps": 0.9,
            "utility_bps": 6.5,
            "candidate_set_hash": "abc123",
            "as_of": "2026-07-02",
            "output_dir": "",
        },
        {
            "candidate_id": "hold_current",
            "strategy_id": "cash",
            "action": "hold",
            "eligible": True,
            "expected_alpha_bps": 0.0,
            "one_way_turnover": 0.0,
            "estimated_cost_bps": 0.0,
            "utility_bps": 0.0,
            "candidate_set_hash": "abc123",
            "as_of": "2026-07-02",
            "output_dir": "",
        },
    ]).to_csv(board_dir / "candidate_board.csv", index=False)
    (board_dir / "selection.json").write_text(json.dumps({
        "candidate_id": "hold_current",
        "source": "deterministic_recommendation",
        "as_of": "2026-07-02",
        "candidate_set_hash": "abc123",
    }))


def test_full_frontier_policy_action_enables_defaults():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        save_policy(
            root,
            SelectionPolicy(
                enabled_strategy_ids=("q23_hybrid_alpha",),
                enabled_blend_ids=(),
            ),
        )
        service = StrategySelectionService(root)
        service.save_full_frontier_policy()
        policy = service.policy()

        assert set(policy.enabled_strategy_ids) == set(default_strategy_ids())
        assert set(policy.enabled_blend_ids) == set(default_blend_ids())


def test_frontier_status_detects_narrow_candidate_board():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        service = StrategySelectionService(root)
        service.save_full_frontier_policy()
        _write_tiny_board(root)

        status = service.frontier_status()

        assert status["board_candidate_count"] == 2
        assert status["expected_candidate_count"] > 2
        assert status["is_incomplete_latest_board"] is True
        assert "q23_hybrid_alpha" not in status["missing_enabled_strategy_ids"]
        assert status["missing_enabled_strategy_ids"]
        assert status["missing_enabled_blend_ids"]
        assert "narrower than the current policy frontier" in status["explanation"]


if __name__ == "__main__":
    test_full_frontier_policy_action_enables_defaults()
    test_frontier_status_detects_narrow_candidate_board()
    print("STRATEGY FRONTIER STATUS TESTS PASSED")
