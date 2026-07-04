"""Tests for the Svyable agent PM context pack."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.agent_pm_harness import build_agent_context, write_agent_pm_pack
from svyable.calendar import expected_last_close


def _make_board(root: Path) -> Path:
    board_dir = root / "strategy_selection" / "20260102_093000"
    artifact_dir = root / "candidate_q23_hybrid" / "20260102_093000"
    artifact_dir.mkdir(parents=True)
    board_dir.mkdir(parents=True)
    as_of = "2026-01-02"
    candidate_hash = "abc123candidatehash"
    board = pd.DataFrame(
        [
            {
                "candidate_id": "q23_hybrid_alpha",
                "strategy_id": "q23_hybrid_alpha",
                "action": "rebalance",
                "eligible": True,
                "utility_bps": 4.2,
                "expected_alpha_bps": 8.1,
                "net_expected_alpha_bps": 7.8,
                "one_way_turnover": 0.08,
                "estimated_cost_bps": 0.3,
                "risk_penalty_bps": 0.0,
                "current_overlap": 0.7,
                "rebalance_required": True,
                "cadence_due": True,
                "hold_lock": False,
                "kill_switch": False,
                "family": "core",
                "maturity": "production_candidate",
                "output_dir": str(artifact_dir),
                "as_of": as_of,
                "candidate_set_hash": candidate_hash,
            },
            {
                "candidate_id": "blocked_alpha",
                "strategy_id": "blocked_alpha",
                "action": "rebalance",
                "eligible": False,
                "utility_bps": 9.0,
                "expected_alpha_bps": 12.0,
                "net_expected_alpha_bps": 11.0,
                "one_way_turnover": 0.55,
                "estimated_cost_bps": 1.0,
                "risk_penalty_bps": 0.0,
                "current_overlap": 0.1,
                "rebalance_required": True,
                "cadence_due": True,
                "hold_lock": False,
                "kill_switch": False,
                "family": "test",
                "maturity": "experimental",
                "output_dir": "",
                "as_of": as_of,
                "candidate_set_hash": candidate_hash,
            },
            {
                "candidate_id": "hold_current",
                "strategy_id": "cash",
                "action": "hold",
                "eligible": True,
                "utility_bps": 0.0,
                "expected_alpha_bps": 0.0,
                "net_expected_alpha_bps": 0.0,
                "one_way_turnover": 0.0,
                "estimated_cost_bps": 0.0,
                "risk_penalty_bps": 0.0,
                "current_overlap": 0.0,
                "rebalance_required": False,
                "cadence_due": False,
                "hold_lock": False,
                "kill_switch": False,
                "family": "baseline",
                "maturity": "baseline",
                "output_dir": "",
                "as_of": as_of,
                "candidate_set_hash": candidate_hash,
            },
        ]
    )
    board.to_csv(board_dir / "candidate_board.csv", index=False)
    (board_dir / "selection.json").write_text(json.dumps({
        "as_of": as_of,
        "candidate_set_hash": candidate_hash,
        "candidate_id": "q23_hybrid_alpha",
        "strategy_id": "q23_hybrid_alpha",
        "source": "deterministic_recommendation",
        "reason": "test selection",
    }))
    (root / "strategy_selection" / "current_positions.json").write_text(json.dumps({
        "as_of": as_of,
        "candidate_set_hash": candidate_hash,
        "source": "unit_test",
        "weights": {"AAA": 0.5},
    }))
    expected = str(expected_last_close(pd.Timestamp.today().date()))
    (artifact_dir / "meta.json").write_text(json.dumps({
        "data": {"last_date": expected},
        "execution_inputs": {"date": expected},
    }))
    pd.DataFrame(
        {"price": [100.0], "adv_dollars": [1_000_000.0], "is_liquid": [True]},
        index=["AAA"],
    ).to_csv(artifact_dir / "execution_inputs.csv")
    idx = pd.bdate_range("2025-01-01", periods=160)
    pd.DataFrame({"fading_factor": np.linspace(0.08, -0.03, len(idx))}, index=idx).to_csv(
        artifact_dir / "ic_health.csv"
    )
    return board_dir


def test_agent_pm_pack_writes_context_memo_and_template(tmp_path: Path):
    board_dir = _make_board(tmp_path)

    pack = write_agent_pm_pack(tmp_path, board_dir=board_dir, max_candidates=3)
    context = json.loads(pack.context_path.read_text())

    assert pack.memo_path.exists()
    assert pack.template_path.exists()
    assert "q23_hybrid_alpha" in context["rails"]["allowed_candidate_ids"]
    assert context["summary"]["top_eligible_candidate"] == "q23_hybrid_alpha"
    assert context["focus_candidate_artifact_health"]["status"] == "ok"
    assert context["focus_candidate_artifact_health"]["factor_trend_summary"]["deteriorating"] == 1
    assert (tmp_path / "strategy_selection" / "latest_agent_context.json").exists()


def test_build_context_blocks_ineligible_candidates(tmp_path: Path):
    board_dir = _make_board(tmp_path)

    context = build_agent_context(tmp_path, board_dir=board_dir)
    blocked = {item["candidate_id"]: item["reasons"] for item in context["rails"]["blocked_candidates"]}

    assert "blocked_alpha" in blocked
    assert any("turnover" in reason for reason in blocked["blocked_alpha"])
    assert context["agent_contract"]["agent_to_repo"].startswith("A hash-matched")


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_agent_pm_pack_writes_context_memo_and_template(Path(tmp))
    with TemporaryDirectory() as tmp:
        test_build_context_blocks_ineligible_candidates(Path(tmp))
    print("AGENT PM HARNESS TESTS PASSED")
