"""Tests for alpha-family dashboard frame adapters."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.alpha_family_frames import alpha_family_governance_frames, alpha_family_summary_rows


def test_alpha_family_governance_frames_have_expected_tables():
    frames = alpha_family_governance_frames()

    assert set(frames) == {"strategies", "factors", "stage_counts", "stage_matrix"}
    assert not frames["strategies"].empty
    assert not frames["factors"].empty
    assert "strategy_id" in frames["strategies"].columns
    assert "family" in frames["factors"].columns


def test_alpha_family_summary_rows_are_compact_metrics():
    rows = alpha_family_summary_rows()
    by_metric = {row["metric"]: row["value"] for row in rows}

    assert by_metric["families"] == 3
    assert by_metric["strategies"] == 3
    assert by_metric["factors"] > 0
    assert by_metric["status"] in {"PASS", "BLOCK"}


if __name__ == "__main__":
    test_alpha_family_governance_frames_have_expected_tables()
    test_alpha_family_summary_rows_are_compact_metrics()
    print("ALPHA FAMILY FRAMES TESTS PASSED")
