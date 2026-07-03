"""Chimera blends: registry hygiene, board integration, honest netting,
dynamic weights, hold-lock with a blend active, and end-to-end agent
selection + activation of a blended candidate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.providers import SyntheticProvider
from svyable.strategy_activation import activate_latest_selection
from svyable.strategy_blend import (
    BlendSpec,
    blend_spec_from_dict,
    default_blend_ids,
    get_blend,
    list_blends,
    resolve_component_weights,
)
from svyable.strategy_registry import get_strategy
from svyable.strategy_selector import (
    SelectionPolicy,
    agent_decision_path,
    run_strategy_selection,
    save_policy,
)


def _panel(n_assets: int = 20, n_days: int = 360):
    return SyntheticProvider(n_assets=n_assets, n_days=n_days).get_panel()


def _permissive(**overrides) -> SelectionPolicy:
    defaults = dict(
        mode="deterministic",
        enabled_strategy_ids=("q23_hybrid_alpha", "q23_low_turnover"),
        enabled_blend_ids=(),
        max_one_way_turnover=1.0,
        min_expected_net_alpha_bps=-100.0,
    )
    defaults.update(overrides)
    return SelectionPolicy(**defaults)


def test_preset_blends_are_valid_and_complete():
    assert len(list_blends()) >= 4
    assert set(default_blend_ids()) >= {
        "chimera_flagship_shield",
        "chimera_trend_reversion",
        "chimera_all_weather",
        "chimera_adaptive",
    }
    for spec in list_blends():
        spec.validate()
        for strategy_id in spec.component_ids():
            get_strategy(strategy_id)   # must reference registered strategies
    shield = get_blend("chimera_flagship_shield")
    assert dict(shield.components)["q23_concentrated"] == 0.70
    assert get_blend("chimera_adaptive").method == "inverse_vol"


def test_blend_spec_validation_rejects_bad_definitions():
    for bad in (
        {"blend_id": "not_prefixed", "components": {"q23_hybrid_alpha": 0.5, "q23_low_turnover": 0.5}},
        {"blend_id": "chimera_one", "components": {"q23_hybrid_alpha": 1.0}},
        {"blend_id": "chimera_sum", "components": {"q23_hybrid_alpha": 0.5, "q23_low_turnover": 0.4}},
        {"blend_id": "chimera_ghost", "components": {"q23_hybrid_alpha": 0.5, "no_such_strategy": 0.5}},
    ):
        try:
            blend_spec_from_dict(bad)
            raise AssertionError(f"accepted invalid blend: {bad}")
        except (ValueError, KeyError):
            pass


def test_blend_rows_on_board_are_linear_combinations_with_artifacts():
    with TemporaryDirectory() as tmp:
        custom = {
            "blend_id": "chimera_test_mix",
            "display_name": "Test Mix",
            "components": {"q23_hybrid_alpha": 0.6, "q23_low_turnover": 0.4},
        }
        result = run_strategy_selection(
            _panel(),
            tmp,
            policy=_permissive(custom_blends=(custom,)),
            tag="blend_board",
            activate=False,
        )
        board = result.board.set_index("candidate_id")
        assert "chimera_test_mix" in board.index
        row = board.loc["chimera_test_mix"]
        assert row["family"] == "chimera blend"
        assert json.loads(row["components"]) == {
            "q23_hybrid_alpha": 0.6,
            "q23_low_turnover": 0.4,
        }

        blend_dir = Path(str(row["output_dir"]))
        assert (blend_dir / "weights_today.csv").exists()
        assert (blend_dir / "execution_inputs.csv").exists()
        meta = json.loads((blend_dir / "meta.json").read_text())
        assert meta["kind"] == "chimera_blend"
        assert meta["components"] == {"q23_hybrid_alpha": 0.6, "q23_low_turnover": 0.4}

        def _weights(candidate_id: str) -> pd.Series:
            directory = Path(str(board.loc[candidate_id, "output_dir"]))
            frame = pd.read_csv(directory / "weights_today.csv", index_col=0)
            return frame["weight"].astype(float)

        blend_weights = _weights("chimera_test_mix")
        expected = (
            0.6 * _weights("q23_hybrid_alpha")
        ).add(0.4 * _weights("q23_low_turnover"), fill_value=0.0)
        expected = expected[expected > 1e-12]
        aligned = blend_weights.reindex(expected.index).fillna(0.0)
        assert float((aligned - expected).abs().max()) < 1e-9

        # netting: blended turnover can never exceed the weighted component sum
        weighted = (
            0.6 * float(board.loc["q23_hybrid_alpha", "one_way_turnover"])
            + 0.4 * float(board.loc["q23_low_turnover", "one_way_turnover"])
        )
        # board values are rounded to 5dp, so allow rounding noise
        assert float(row["one_way_turnover"]) <= weighted + 1e-4


def test_inverse_vol_weights_are_clamped_and_deterministic():
    with TemporaryDirectory() as tmp:
        selection = run_strategy_selection(
            _panel(),
            tmp,
            policy=_permissive(),
            tag="ivol",
            activate=False,
        )
        spec = BlendSpec(
            blend_id="chimera_ivol_test",
            display_name="IVol Test",
            description="test",
            components=(("q23_hybrid_alpha", 0.5), ("q23_low_turnover", 0.5)),
            method="inverse_vol",
        )
        weights = resolve_component_weights(spec, selection.candidate_results)
        again = resolve_component_weights(spec, selection.candidate_results)
        assert abs(float(weights.sum()) - 1.0) < 1e-9
        assert (weights >= 0.10 - 1e-9).all() and (weights <= 0.50 + 1e-9).all()
        assert (weights == again).all()


def test_active_blend_enforces_its_hold_lock():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        panel = _panel()
        state_dir = root / "strategy_selection"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text(json.dumps({
            "selected_strategy_id": "chimera_flagship_shield",   # min hold 5
            "selected_action": "rebalance",
            "selected_at": str(panel.close.index[-1].date()),
        }))
        result = run_strategy_selection(
            panel,
            root,
            policy=_permissive(),
            tag="holdlock",
            activate=False,
        )
        candidates = result.board[result.board["action"] == "rebalance"]
        assert bool(candidates["hold_lock"].all()), (
            "an active chimera's minimum hold must lock out switching"
        )


def test_agent_selects_blend_and_activation_is_canonical():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        # register-by-policy: a custom blend keeps the test self-contained
        policy = _permissive(
            mode="agent",
            custom_blends=(
                {
                    "blend_id": "chimera_agent_mix",
                    "display_name": "Agent Mix",
                    "components": {"q23_hybrid_alpha": 0.5, "q23_low_turnover": 0.5},
                },
            ),
        )
        save_policy(root, policy)
        selection = run_strategy_selection(
            _panel(),
            root,
            policy=policy,
            tag="agent_blend",
            activate=False,
        )
        board = selection.board.set_index("candidate_id")
        assert bool(board.loc["chimera_agent_mix", "eligible"])

        agent_decision_path(root).write_text(json.dumps({
            "as_of": str(board.iloc[0]["as_of"]),
            "candidate_set_hash": str(board.iloc[0]["candidate_set_hash"]),
            "candidate_id": "chimera_agent_mix",
            "confidence": 0.7,
            "reason": "Blend diversifies while netting opposing trades.",
        }))
        activation = activate_latest_selection(root)
        assert activation["strategy_id"] == "chimera_agent_mix"

        canonical = Path(activation["canonical_output_dir"])
        weights = pd.read_csv(canonical / "weights_today.csv", index_col=0)["weight"]
        blend_weights = pd.read_csv(
            Path(str(board.loc["chimera_agent_mix", "output_dir"])) / "weights_today.csv",
            index_col=0,
        )["weight"]
        assert (weights == blend_weights).all()

        state = json.loads((root / "strategy_selection" / "state.json").read_text())
        assert state["selected_strategy_id"] == "chimera_agent_mix"


if __name__ == "__main__":
    test_preset_blends_are_valid_and_complete()
    test_blend_spec_validation_rejects_bad_definitions()
    test_blend_rows_on_board_are_linear_combinations_with_artifacts()
    test_inverse_vol_weights_are_clamped_and_deterministic()
    test_active_blend_enforces_its_hold_lock()
    test_agent_selects_blend_and_activation_is_canonical()
    print("STRATEGY BLEND TESTS PASSED")
