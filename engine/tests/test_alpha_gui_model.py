"""Tests for Alpha Catalyst GUI view models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.alpha_gui_model import alpha_dashboard_metrics, alpha_factor_table, alpha_strategy_cards
from svyable.factor_library import factor_metadata
from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_leadership_quality import LEADERSHIP_QUALITY
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


def test_alpha_factor_table_includes_new_alpha_families():
    table = alpha_factor_table(factor_metadata())

    assert set(ALPHA_CATALYST).issubset(set(table["factor"]))
    assert set(TAPE_ACCELERATION).issubset(set(table["factor"]))
    assert set(LEADERSHIP_QUALITY).issubset(set(table["factor"]))
    assert {"Alpha Catalyst", "Tape Acceleration", "Leadership Quality"}.issubset(set(table["family"]))


def test_alpha_strategy_cards_surface_config_and_shadow_mix():
    cards = alpha_strategy_cards(factor_metadata())
    by_id = {row["strategy_id"]: row for row in cards.to_dict(orient="records")}

    assert "svyable_alpha_catalyst" in by_id
    assert "svyable_tape_acceleration" in by_id
    assert "svyable_leadership_quality" in by_id
    assert by_id["svyable_alpha_catalyst"]["alpha_family_factors"] >= len(ALPHA_CATALYST)
    assert by_id["svyable_leadership_quality"]["alpha_family_factors"] >= len(LEADERSHIP_QUALITY)
    assert by_id["svyable_alpha_catalyst"]["max_pos"] <= 0.09
    assert by_id["svyable_leadership_quality"]["minimum_hold_days"] >= 4
    assert by_id["svyable_alpha_catalyst"]["shadow_ratio"] >= 0.0


def test_alpha_dashboard_metrics_are_nonzero():
    metrics = alpha_dashboard_metrics(factor_metadata())

    assert metrics["alpha_factor_count"] == len(ALPHA_CATALYST) + len(TAPE_ACCELERATION) + len(LEADERSHIP_QUALITY)
    assert metrics["alpha_strategy_count"] == 3
    assert metrics["shadow_factors"] >= len(ALPHA_CATALYST) + len(LEADERSHIP_QUALITY)


if __name__ == "__main__":
    test_alpha_factor_table_includes_new_alpha_families()
    test_alpha_strategy_cards_surface_config_and_shadow_mix()
    test_alpha_dashboard_metrics_are_nonzero()
    print("ALPHA GUI MODEL TESTS PASSED")
