"""Regression tests for strategy registry, selection, and activation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.providers import SyntheticProvider
from svyable.strategy_activation import activate_latest_selection
from svyable.strategy_registry import default_strategy_ids, get_strategy, registry_frame
from svyable.strategy_selector import (
    SelectionPolicy,
    _deterministic_choice,
    agent_decision_path,
    run_strategy_selection,
    save_policy,
)


def test_registry_contains_distinct_complete_strategies():
    registry = registry_frame()
    assert len(registry) >= 6
    assert "q23_neural_alpha" in registry.index
    assert "q23_ou_mean_reversion" in registry.index
    assert "q23_low_turnover" in registry.index
    assert "q23_flow_alpha" not in default_strategy_ids()
    assert get_strategy("q23_low_turnover").rebalance_interval_days == 3
    assert (
        get_strategy("q23_ou_mean_reversion").config_overrides["no_trade_band"]
        < get_strategy("q23_low_turnover").config_overrides["no_trade_band"]
    )


def test_concentrated_flagship_matches_mandate():
    """The flagship mandate: 7-10 positions at roughly 10% apiece, long only,
    built by the same Q23 factor ensemble — concentration via construction."""
    spec = get_strategy("q23_concentrated")
    cfg = spec.build_config()
    assert cfg.seats_min == 7 and cfg.seats_max == 10
    assert 7 <= cfg.seats_base <= 10
    # a full 10-seat book must be able to hold ~10% names; ceiling stays sane
    assert 0.10 <= cfg.max_pos <= 0.15
    assert spec.enabled_by_default
    # same alpha engine as the hybrid ensemble, not a bespoke factor set
    assert set(spec.factor_names) == set(get_strategy("q23_hybrid_alpha").factor_names)


def _board(candidate_utility: float) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "candidate_id": "q23_hybrid_alpha",
            "strategy_id": "q23_hybrid_alpha",
            "action": "rebalance",
            "eligible": True,
            "utility_bps": candidate_utility,
            "is_current_strategy": False,
        },
        {
            "candidate_id": "hold_current",
            "strategy_id": "q23_defensive_alpha",
            "action": "hold",
            "eligible": True,
            "utility_bps": 1.0,
            "is_current_strategy": True,
        },
    ])


def test_switch_requires_cost_aware_buffer():
    policy = SelectionPolicy(switch_buffer_bps=2.0)
    assert _deterministic_choice(_board(2.5), policy)["candidate_id"] == "hold_current"
    assert _deterministic_choice(_board(3.1), policy)["candidate_id"] == "q23_hybrid_alpha"


def test_synthetic_candidate_board_runs_complete_strategies():
    with TemporaryDirectory() as tmp:
        panel = SyntheticProvider(n_assets=20, n_days=360).get_panel()
        policy = SelectionPolicy(
            mode="deterministic",
            enabled_strategy_ids=("q23_hybrid_alpha", "q23_low_turnover"),
            max_one_way_turnover=1.0,
            min_expected_net_alpha_bps=-100.0,
        )
        result = run_strategy_selection(
            panel,
            tmp,
            policy=policy,
            tag="synthetic_board",
            activate=False,
        )
        assert set(result.board["candidate_id"]) == {
            "q23_hybrid_alpha",
            "q23_low_turnover",
            "hold_current",
        }
        assert result.board["candidate_set_hash"].nunique() == 1
        candidates = result.board[result.board["action"] == "rebalance"]
        assert (candidates["one_way_turnover"] > 0).all()
        assert (candidates["current_position_source"] == "canonical_target").all()
        for output_dir in candidates["output_dir"]:
            path = Path(output_dir)
            assert (path / "weights_today.csv").exists()
            assert (path / "execution_inputs.csv").exists()
            meta = json.loads((path / "meta.json").read_text())
            assert meta["factor_library"]["precomputed_cache"] is True
        assert (result.board_dir / "candidate_board.csv").exists()
        assert (result.board_dir / "selection.json").exists()


def test_agent_activation_is_canonical_and_idempotent():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        save_policy(
            root,
            SelectionPolicy(
                mode="agent",
                enabled_strategy_ids=("q23_hybrid_alpha",),
            ),
        )
        source = root / "candidate_q23_hybrid_alpha" / "run"
        source.mkdir(parents=True)
        pd.Series({"AAPL": 0.6, "MSFT": 0.4}, name="weight").to_csv(
            source / "weights_today.csv"
        )
        pd.DataFrame(
            [[0.6, 0.4]],
            index=["2026-07-02"],
            columns=["AAPL", "MSFT"],
        ).to_csv(source / "weights_history.csv")
        pd.DataFrame(
            {
                "price": [200.0, 500.0],
                "adv_dollars": [1e9, 1e9],
                "is_liquid": [True, True],
            },
            index=["AAPL", "MSFT"],
        ).to_csv(source / "execution_inputs.csv")
        (source / "meta.json").write_text(
            json.dumps({"strategy_id": "candidate_q23_hybrid_alpha"})
        )
        (source / "morning_report.md").write_text("# Candidate report\n")

        board_dir = root / "strategy_selection" / "20260702_073000"
        board_dir.mkdir(parents=True)
        board = pd.DataFrame([
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
                "output_dir": str(source),
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
        ])
        board.to_csv(board_dir / "candidate_board.csv", index=False)
        (board_dir / "selection.json").write_text(json.dumps({
            "candidate_id": "hold_current",
            "source": "deterministic_recommendation",
            "reason": "Awaiting agent",
            "as_of": "2026-07-02",
            "candidate_set_hash": "abc123",
        }))
        decision_path = agent_decision_path(root)
        decision_path.write_text(json.dumps({
            "as_of": "2026-07-02",
            "candidate_set_hash": "abc123",
            "candidate_id": "q23_hybrid_alpha",
            "confidence": 0.8,
            "reason": "Best net alpha after cost with acceptable turnover.",
        }))

        first = activate_latest_selection(root)
        second = activate_latest_selection(root)
        canonical = Path(first["canonical_output_dir"])
        weights = pd.read_csv(canonical / "weights_today.csv", index_col=0)["weight"]
        state = json.loads((root / "strategy_selection" / "state.json").read_text())
        meta = json.loads((canonical / "meta.json").read_text())

        assert first == second
        assert first["source"] == "agent"
        assert set(weights.index) == {"AAPL", "MSFT"}
        assert state["selected_strategy_id"] == "q23_hybrid_alpha"
        assert meta["selected_strategy_id"] == "q23_hybrid_alpha"
        assert (canonical / "execution_inputs.csv").exists()

        decision_path.write_text(json.dumps({
            "as_of": "2026-07-02",
            "candidate_set_hash": "abc123",
            "candidate_id": "hold_current",
            "confidence": 0.5,
            "reason": "Changed decision after activation.",
        }))
        try:
            activate_latest_selection(root)
            raise AssertionError("an activated board accepted a different decision")
        except RuntimeError as exc:
            assert "already activated" in str(exc)


if __name__ == "__main__":
    test_registry_contains_distinct_complete_strategies()
    test_switch_requires_cost_aware_buffer()
    test_synthetic_candidate_board_runs_complete_strategies()
    test_agent_activation_is_canonical_and_idempotent()
    print("STRATEGY SELECTION TESTS PASSED")
