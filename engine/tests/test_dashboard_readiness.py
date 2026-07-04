"""Tests for agent/human PM readiness gates."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.dashboard_readiness import build_readiness_snapshot


class _ReadyService:
    def strategy_snapshot(self):
        return {"run_dir": Path("/tmp/svyable_run")}

    def execution_inputs(self):
        return {"artifact_date": "2026-07-03", "expected_date": "2026-07-03", "stale": False, "meta": {}}

    def ledger_snapshot(self):
        return {"health": {"warnings_7d": 0, "critical_7d": 0}}


class _ReadyStrategyService:
    def frontier_status(self):
        return {
            "is_incomplete_latest_board": False,
            "board_candidate_count": 12,
            "expected_candidate_count": 12,
        }


class _StaleService(_ReadyService):
    def execution_inputs(self):
        return {"artifact_date": "2026-07-01", "expected_date": "2026-07-03", "stale": True, "meta": {}}


def _settings() -> TastySettings:
    return TastySettings(client_secret="secret", refresh_token="refresh", account_number="123456", is_test=True)


def test_readiness_passes_when_artifacts_quotes_and_frontier_are_clean():
    market = pd.DataFrame(
        [
            {"symbol": "AAPL", "quote_ok": True, "spread_bps": 8.0},
            {"symbol": "MSFT", "quote_ok": True, "spread_bps": 12.0},
        ]
    )

    result = build_readiness_snapshot(
        _ReadyService(),
        _ReadyStrategyService(),
        _settings(),
        broker_snapshot={"session_valid": True},
        market_frame=market,
        ledger_snapshot={"health": {"warnings_7d": 0, "critical_7d": 0}},
    )

    assert result["status"] == "PASS"
    assert result["blocked"] == 0
    assert result["warned"] == 0


def test_readiness_blocks_stale_inputs_and_missing_quotes():
    market = pd.DataFrame(
        [
            {"symbol": "AAPL", "quote_ok": True, "spread_bps": 8.0},
            {"symbol": "TSLA", "quote_ok": False, "spread_bps": None},
        ]
    )

    result = build_readiness_snapshot(
        _StaleService(),
        _ReadyStrategyService(),
        _settings(),
        broker_snapshot={"session_valid": True},
        market_frame=market,
        ledger_snapshot={"health": {"warnings_7d": 0, "critical_7d": 0}},
    )

    assert result["status"] == "BLOCK"
    details = {row["gate"]: row["detail"] for row in result["gates"]}
    assert "stale artifact" in details["Execution inputs"]
    assert "missing live quotes" in details["Live quotes"]


if __name__ == "__main__":
    test_readiness_passes_when_artifacts_quotes_and_frontier_are_clean()
    test_readiness_blocks_stale_inputs_and_missing_quotes()
    print("DASHBOARD READINESS TESTS PASSED")
