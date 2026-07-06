"""Tests for daily strategy playbook cards and configurable golden contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.golden_contract import (
    base_contract,
    config_from_contract,
    registered_strategy_contract,
)
from svyable.strategy_playbook import render_candidate_playbook, write_playbook_bundle


def _artifact_dir(root: Path) -> Path:
    out = root / "candidate_q23_hybrid_alpha" / "20260705_063000"
    out.mkdir(parents=True)
    pd.DataFrame({"weight": [0.12, 0.08]}, index=["AAPL", "MSFT"]).to_csv(out / "weights_today.csv")
    pd.DataFrame({"momentum": [0.7], "defensive": [0.3]}, index=["2026-07-05"]).to_csv(out / "sleeve_weights.csv")
    pd.DataFrame({"mom_12_1": [0.11], "trend_consistency": [0.07]}, index=["2026-07-05"]).to_csv(out / "factor_weights_momentum.csv")
    pd.DataFrame(
        {
            "stage": ["proven", "proven"],
            "sleeve": ["momentum", "momentum"],
            "description": ["classic momentum", "trend agreement"],
        },
        index=["mom_12_1", "trend_consistency"],
    ).to_csv(out / "factor_catalog.csv")
    (out / "meta.json").write_text(json.dumps({
        "config_hash": "abc123",
        "config": {
            "target_vol": 0.16,
            "seats_base": 20,
            "seats_min": 15,
            "seats_max": 25,
            "max_pos": 0.12,
            "no_trade_band": 0.04,
            "tc_bps": 3.0,
            "adv_participation_cap": 0.05,
        },
        "data": {"status": "ok"},
        "regime": {"multiplier": 1.0, "turb_pct": 0.2, "breadth": 0.8, "absorption": 0.4},
        "perf_1y_net": {"sharpe": 1.2},
    }))
    return out


def test_render_candidate_playbook_from_artifacts(tmp_path: Path):
    out = _artifact_dir(tmp_path)
    board = pd.DataFrame([
        {
            "candidate_id": "q23_hybrid_alpha",
            "strategy_id": "q23_hybrid_alpha",
            "name": "Q23 Hybrid Alpha",
            "family": "multi-sleeve ensemble",
            "action": "rebalance",
            "eligible": True,
            "utility_bps": 4.2,
            "net_expected_alpha_bps": 5.1,
            "estimated_cost_bps": 0.4,
            "one_way_turnover": 0.05,
            "current_overlap": 0.8,
            "positions": 2,
            "gross": 0.2,
            "recent_vol": 0.12,
            "sharpe_252d": 1.1,
            "return_63d": 0.04,
            "return_252d": 0.12,
            "recent_max_drawdown": 0.03,
            "kill_switch": False,
            "output_dir": str(out),
        },
        {"candidate_id": "hold_current", "utility_bps": 0.0, "eligible": True, "action": "hold", "output_dir": ""},
    ])

    md = render_candidate_playbook(board.iloc[0], board=board, board_dir=tmp_path / "strategy_selection" / "run")
    assert "Playbook card — Q23 Hybrid Alpha" in md
    assert "AAPL" in md
    assert "mom_12_1" in md
    assert "Edge vs hold" in md


def test_write_playbook_bundle(tmp_path: Path):
    out = _artifact_dir(tmp_path)
    board = pd.DataFrame([
        {"candidate_id": "q23_hybrid_alpha", "name": "Q23 Hybrid Alpha", "eligible": True, "utility_bps": 4.2, "output_dir": str(out)},
        {"candidate_id": "hold_current", "name": "Hold current", "eligible": True, "utility_bps": 0.0, "output_dir": ""},
    ])
    board_dir = tmp_path / "strategy_selection" / "20260705_063000"
    result = write_playbook_bundle(board, board_dir)
    assert result["count"] == 2
    assert Path(result["index_path"]).exists()
    assert (board_dir / "playbooks" / "q23_hybrid_alpha.md").exists()


def test_registered_golden_contract_preserves_strategy_ml_setting():
    contract = registered_strategy_contract("q23_neural_alpha")
    cfg, factors = config_from_contract(contract)
    assert cfg.ml_enabled is True
    assert cfg.min_adv == 0.0
    assert factors


def test_base_golden_contract_is_stable_fixture():
    cfg, factors = config_from_contract(base_contract())
    assert cfg.strategy_id == "svyable_nasdaq_lo"
    assert cfg.ml_enabled is False
    assert cfg.seats_base == 15
    assert factors is None
