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

from svyable.agent_review_chain import run_review_chain
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


def _write_agent_review_context(root: Path, board: pd.DataFrame, candidate_id: str) -> None:
    """Materialize a synthetic PASS review context for blend activation tests.

    Agent activation now requires a guard/chain/receipt/audit PASS for every
    candidate, including chimera blends. The regression should exercise that
    same review rail instead of bypassing it for blends.
    """
    selection = root / "strategy_selection"
    selection.mkdir(parents=True, exist_ok=True)
    first = board.iloc[0]
    candidates = [
        {"candidate_id": str(value)}
        for value in board["candidate_id"].astype(str).tolist()
    ]
    context = {
        "as_of": str(first["as_of"]),
        "candidate_set_hash": str(first["candidate_set_hash"]),
        "rails": {
            "allowed_candidate_ids": [item["candidate_id"] for item in candidates],
            "hard_rules": ["Choose exactly one allowed candidate_id."],
        },
        "decision_readiness": {"status": "PASS", "issues": []},
        "focus_candidate_artifact_health": {
            "status": "ok",
            "inputs_stale": False,
            "missing_execution_columns": [],
        },
        "candidates": candidates,
        "summary": {
            "candidate_count": int(len(candidates)),
            "eligible_count": int(board["eligible"].astype(bool).sum()),
            "top_eligible_candidate": candidate_id,
            "planned_candidate": candidate_id,
            "mode": "agent",
        },
        "meta_decision_trace": {
            "visible_regime": {},
            "selected_score_breakdown": {},
            "selected_decision_nodes": [],
        },
        "selection_explanation": {
            "summary": "Synthetic chimera blend activation review fixture."
        },
    }
    (selection / "latest_agent_context.json").write_text(json.dumps(context))
    (selection / "latest_agent_pm_memo.md").write_text("# Synthetic blend review memo\n")


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
            component_min_weight=0.10,
            component_max_weight=0.50,
        )
        weights = resolve_component_weights(spec, selection.candidate_results)
        again = resolve_component_weights(spec, selection.candidate_results)
        assert abs(float(weights.sum()) - 1.0) < 1e-9
        assert (weights >= spec.component_min_weight - 1e-9).all()
        assert (weights <= spec.component_max_weight + 1e-9).all()
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
        try:
            activate_latest_selection(root)
            raise AssertionError("unreviewed chimera decision activated")
        except RuntimeError as exc:
            assert "review" in str(exc).lower() or "guard" in str(exc).lower()

        _write_agent_review_context(root, selection.board, "chimera_agent_mix")
        chain = run_review_chain(root)
        assert chain["status"] == "PASS"

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


def test_service_custom_blend_lifecycle_and_pending_proposal():
    from svyable.strategy_selection_service import StrategySelectionService

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        service = StrategySelectionService(root)

        # invalid definitions must be rejected before touching the policy
        try:
            service.add_custom_blend({
                "blend_id": "chimera_bad",
                "components": {"q23_hybrid_alpha": 0.9, "q23_low_turnover": 0.2},
            })
            raise AssertionError("accepted weights that do not sum to 1")
        except ValueError:
            pass

        service.add_custom_blend({
            "blend_id": "chimera_svc_mix",
            "display_name": "Service Mix",
            "components": {"q23_hybrid_alpha": 0.5, "q23_low_turnover": 0.5},
        })
        assert any(
            item["blend_id"] == "chimera_svc_mix"
            for item in service.policy().custom_blends
        )
        # saving again replaces, not duplicates
        service.add_custom_blend({
            "blend_id": "chimera_svc_mix",
            "display_name": "Service Mix v2",
            "components": {"q23_hybrid_alpha": 0.6, "q23_low_turnover": 0.4},
        })
        entries = [
            item for item in service.policy().custom_blends
            if item["blend_id"] == "chimera_svc_mix"
        ]
        assert len(entries) == 1 and entries[0]["components"]["q23_hybrid_alpha"] == 0.6
        service.remove_custom_blend("chimera_svc_mix")
        assert not service.policy().custom_blends

        # pending proposal surfaces only while unactivated and board-fresh
        assert service.pending_agent_decision() == {}
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
            _panel(), root, policy=policy, tag="svc_pending", activate=False
        )
        board = selection.board.set_index("candidate_id")
        agent_decision_path(root).write_text(json.dumps({
            "as_of": str(board.iloc[0]["as_of"]),
            "candidate_set_hash": str(board.iloc[0]["candidate_set_hash"]),
            "candidate_id": "chimera_agent_mix",
            "confidence": 0.7,
            "reason": "Diversified blend beats each component after costs.",
        }))
        pending = service.pending_agent_decision()
        assert pending["candidate_id"] == "chimera_agent_mix"
        assert pending["eligible"] is True
        assert json.loads(pending["components"]) == {
            "q23_hybrid_alpha": 0.5,
            "q23_low_turnover": 0.5,
        }

        # regime diagnostics exist because candidate runs write them
        regime = service.latest_regime()
        assert not regime.empty and "throttle" in regime.columns

        _write_agent_review_context(root, selection.board, "chimera_agent_mix")
        chain = run_review_chain(root)
        assert chain["status"] == "PASS"
        activate_latest_selection(root)
        assert service.pending_agent_decision() == {}, (
            "an activated proposal must no longer show as pending"
        )


if __name__ == "__main__":
    test_preset_blends_are_valid_and_complete()
    test_blend_spec_validation_rejects_bad_definitions()
    test_blend_rows_on_board_are_linear_combinations_with_artifacts()
    test_inverse_vol_weights_are_clamped_and_deterministic()
    test_active_blend_enforces_its_hold_lock()
    test_agent_selects_blend_and_activation_is_canonical()
    test_service_custom_blend_lifecycle_and_pending_proposal()
    print("STRATEGY BLEND TESTS PASSED")
