"""Tests for alpha-family GUI view models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.alpha_gui_model import alpha_dashboard_metrics, alpha_factor_table, alpha_strategy_cards
from svyable.factor_library import factor_metadata
from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_downside_resilience import DOWNSIDE_RESILIENCE
from svyable.strategy_leadership_quality import LEADERSHIP_QUALITY
from svyable.strategy_rotation_breadth import ROTATION_BREADTH
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


ALL_NEW_FACTORS = ALPHA_CATALYST + TAPE_ACCELERATION + LEADERSHIP_QUALITY + DOWNSIDE_RESILIENCE + ROTATION_BREADTH


def test_alpha_factor_table_includes_expanded_alpha_families():
    table = alpha_factor_table(factor_metadata())

    assert set(ALL_NEW_FACTORS).issubset(set(table["factor"]))
    assert {"Alpha Catalyst", "Tape Acceleration", "Leadership Quality", "Downside Resilience", "Rotation Breadth"}.issubset(set(table["family"]))


def test_alpha_strategy_cards_surface_config_and_shadow_mix():
    cards = alpha_strategy_cards(factor_metadata())
    by_id = {row["strategy_id"]: row for row in cards.to_dict(orient="records")}

    for strategy_id in [
        "svyable_alpha_catalyst",
        "svyable_tape_acceleration",
        "svyable_leadership_quality",
        "svyable_downside_resilience",
        "svyable_rotation_breadth",
    ]:
        assert strategy_id in by_id
    assert by_id["svyable_alpha_catalyst"]["max_pos"] <= 0.09
    assert by_id["svyable_leadership_quality"]["minimum_hold_days"] >= 4
    assert by_id["svyable_downside_resilience"]["minimum_hold_days"] >= 5
    assert by_id["svyable_rotation_breadth"]["minimum_hold_days"] >= 3
    assert by_id["svyable_rotation_breadth"]["alpha_family_factors"] >= len(ROTATION_BREADTH)


def test_alpha_dashboard_metrics_are_nonzero():
    metrics = alpha_dashboard_metrics(factor_metadata())

    assert metrics["alpha_factor_count"] == len(ALL_NEW_FACTORS)
    assert metrics["alpha_strategy_count"] == 5
    assert metrics["shadow_factors"] >= len(ALPHA_CATALYST) + len(LEADERSHIP_QUALITY) + len(DOWNSIDE_RESILIENCE) + len(ROTATION_BREADTH)


if __name__ == "__main__":
    test_alpha_factor_table_includes_expanded_alpha_families()
    test_alpha_strategy_cards_surface_config_and_shadow_mix()
    test_alpha_dashboard_metrics_are_nonzero()
    print("ALPHA GUI MODEL TESTS PASSED")
