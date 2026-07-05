"""Tests for strategy registry quality diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.strategy_registry_quality import registry_quality_audit, registry_quality_frames


def test_registry_quality_audit_has_expected_shape():
    report = registry_quality_audit()

    assert report["strategy_count"] > 0
    assert report["known_factor_count"] > 0
    assert report["status"] in {"PASS", "BLOCK"}
    assert report["contract"].startswith("Read-only registry audit")
    assert isinstance(report["strategies"], list)
    assert "missing_references" in report
    assert "high_overlap_pairs" in report


def test_registry_quality_frames_return_tables():
    frames = registry_quality_frames()

    assert set(frames) == {
        "strategies",
        "missing_references",
        "internal_duplicates",
        "exact_duplicate_packs",
        "high_overlap_pairs",
    }
    assert not frames["strategies"].empty
    assert "strategy_id" in frames["strategies"].columns


if __name__ == "__main__":
    test_registry_quality_audit_has_expected_shape()
    test_registry_quality_frames_return_tables()
    print("STRATEGY REGISTRY QUALITY TESTS PASSED")
