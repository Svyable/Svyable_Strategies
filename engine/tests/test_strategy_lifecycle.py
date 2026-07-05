"""Tests for strategy day-in-life runbooks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.strategy_lifecycle import (
    render_strategy_day_markdown,
    strategy_day_in_life,
    write_strategy_day_runbook,
)


def test_strategy_day_in_life_has_expected_contract_and_stages():
    runbook = strategy_day_in_life("svyable_alpha_catalyst", as_of="2026-01-02")

    assert runbook["strategy_id"] == "svyable_alpha_catalyst"
    assert runbook["as_of"] == "2026-01-02"
    assert runbook["factor_count"] > 0
    assert len(runbook["stages"]) >= 10
    assert runbook["contract"].startswith("Read-only lifecycle narrative")
    assert any("Candidate board" in stage["phase"] for stage in runbook["stages"])


def test_strategy_day_markdown_mentions_review_chain_and_canonical_handoff():
    markdown = render_strategy_day_markdown(strategy_day_in_life("svyable_alpha_catalyst", as_of="2026-01-02"))

    assert markdown.startswith("# A day in the life of Svyable Alpha Catalyst")
    assert "Guard / receipt / audit" in markdown
    assert "Canonical artifact handoff" in markdown
    assert "Read-only lifecycle narrative" in markdown


def test_strategy_day_writer_persists_json_and_markdown(tmp_path):
    written = write_strategy_day_runbook(tmp_path, strategy_id="svyable_alpha_catalyst", as_of="2026-01-02")

    json_path = Path(written["json_path"])
    md_path = Path(written["markdown_path"])
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["strategy_id"] == "svyable_alpha_catalyst"
    assert md_path.read_text().startswith("# A day in the life")


if __name__ == "__main__":
    test_strategy_day_in_life_has_expected_contract_and_stages()
    test_strategy_day_markdown_mentions_review_chain_and_canonical_handoff()
    test_strategy_day_writer_persists_json_and_markdown(Path("/tmp/svyable_strategy_lifecycle_test"))
    print("STRATEGY LIFECYCLE TESTS PASSED")
