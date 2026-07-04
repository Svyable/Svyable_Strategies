"""Tests for the visible selection meta trace."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_meta_trace import build_meta_trace, candidate_decision_nodes, infer_visible_regime, score_breakdown


def _board(tmp_path: Path) -> pd.DataFrame:
    out = tmp_path / "candidate_a"
    out.mkdir()
    pd.Series({"AAA": 0.35, "BBB": 0.25, "CCC": -0.10}).rename("weight").to_csv(out / "weights_today.csv")
    return pd.DataFrame([
        {
            "candidate_id": "candidate_a",
            "strategy_id": "candidate_a",
            "action": "rebalance",
            "eligible": True,
            "expected_alpha_bps": 9.0,
            "estimated_cost_bps": 0.8,
            "turnover_penalty_bps": 0.5,
            "risk_penalty_bps": 0.2,
            "utility_bps": 7.5,
            "one_way_turnover": 0.10,
            "rebalance_required": True,
            "cadence_due": True,
            "hold_lock": False,
            "kill_switch": False,
            "recent_vol": 0.12,
            "recent_max_drawdown": 0.03,
            "output_dir": str(out),
        },
        {
            "candidate_id": "candidate_b",
            "strategy_id": "candidate_b",
            "action": "rebalance",
            "eligible": False,
            "expected_alpha_bps": 11.0,
            "estimated_cost_bps": 1.0,
            "turnover_penalty_bps": 2.0,
            "risk_penalty_bps": 3.0,
            "utility_bps": 5.0,
            "one_way_turnover": 0.55,
            "rebalance_required": True,
            "cadence_due": True,
            "hold_lock": False,
            "kill_switch": False,
            "recent_vol": 0.28,
            "recent_max_drawdown": 0.12,
            "output_dir": "",
        },
    ])


def test_meta_trace_exposes_score_tree_and_weights(tmp_path: Path):
    board = _board(tmp_path)
    trace = build_meta_trace(board, selected_candidate_id="candidate_a", artifact_health={"inputs_stale": False})

    assert trace["status"] == "ok"
    assert trace["selected_candidate_id"] == "candidate_a"
    assert trace["weight_provenance"]["status"] == "ok"
    assert "AAA" in trace["weight_provenance"]["top_weights"]
    assert trace["selected_score_breakdown"]["utility_bps"] == 7.5
    assert any(node["node"] == "selector_eligibility" for node in trace["selected_decision_nodes"])


def test_visible_regime_and_candidate_nodes_are_deterministic(tmp_path: Path):
    board = _board(tmp_path)
    regime = infer_visible_regime(board, {"inputs_stale": True, "factor_trend_summary": {"deteriorating": 2}})
    assert regime["state"] in regime["probabilities"]
    assert any("stale" in driver for driver in regime["drivers"])

    blocked_nodes = candidate_decision_nodes(board.iloc[1])
    assert any(node["node"] == "turnover" and node["state"] == "BLOCK" for node in blocked_nodes)
    score = score_breakdown(board.iloc[0])
    assert score["formula"].startswith("expected_alpha")


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_meta_trace_exposes_score_tree_and_weights(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_visible_regime_and_candidate_nodes_are_deterministic(Path(tmp))
    print("AGENT META TRACE TESTS PASSED")
