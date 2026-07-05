"""Tests for alpha-family governance reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.alpha_family_governance import (
    ALPHA_FAMILIES,
    alpha_family_factor_rows,
    alpha_family_governance_report,
    alpha_family_strategy_rows,
    render_alpha_family_markdown,
    write_alpha_family_governance,
)


def test_alpha_family_factor_rows_include_all_families():
    rows = alpha_family_factor_rows()
    families = {row["family"] for row in rows}

    assert set(ALPHA_FAMILIES) == families
    assert len(rows) == sum(len(factors) for factors in ALPHA_FAMILIES.values())
    assert all(row["stage"] in {"proven", "shadow", "unknown"} for row in rows)


def test_alpha_family_strategy_rows_include_new_books():
    rows = alpha_family_strategy_rows()
    by_id = {row["strategy_id"]: row for row in rows}

    assert "svyable_alpha_catalyst" in by_id
    assert "svyable_tape_acceleration" in by_id
    assert "svyable_leadership_quality" in by_id
    assert by_id["svyable_leadership_quality"]["minimum_hold_days"] >= 4


def test_alpha_family_report_markdown_and_writer(tmp_path):
    report = alpha_family_governance_report()
    markdown = render_alpha_family_markdown(report)
    written = write_alpha_family_governance(tmp_path)

    assert report["status"] in {"PASS", "BLOCK"}
    assert report["strategy_count"] == 3
    assert markdown.startswith("# Alpha-Family Governance Report")
    assert Path(written["json_path"]).exists()
    assert Path(written["markdown_path"]).exists()
    payload = json.loads(Path(written["json_path"]).read_text())
    assert payload["factor_count"] == written["factor_count"]


if __name__ == "__main__":
    test_alpha_family_factor_rows_include_all_families()
    test_alpha_family_strategy_rows_include_new_books()
    test_alpha_family_report_markdown_and_writer(Path("/tmp/svyable_alpha_family_test"))
    print("ALPHA FAMILY GOVERNANCE TESTS PASSED")
