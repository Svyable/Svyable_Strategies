"""Regression test for dashboard ADV participation controls."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.calendar import expected_last_close
from svyable.dashboard_service import DashboardService


class FakeBroker:
    environment = "sandbox"
    account_number = "TEST123"

    def get_account(self):
        return {"equity": 100000.0, "cash": 100000.0, "buying_power": 100000.0}

    def get_positions(self):
        return {}

    def execution_prices(self, symbols):
        return {symbol: 100.0 for symbol in symbols}


def test_dashboard_plan_applies_adv_cap():
    with TemporaryDirectory() as tmp:
        output_root = Path(tmp) / "outputs"
        run_dir = output_root / "svyable_nasdaq_lo" / "latest"
        run_dir.mkdir(parents=True)
        pd.Series({"AAPL": 0.50}, name="weight").to_csv(run_dir / "weights_today.csv")
        pd.DataFrame(
            {"price": [100.0], "adv_dollars": [10000.0], "is_liquid": [True]},
            index=["AAPL"],
        ).to_csv(run_dir / "execution_inputs.csv")
        artifact_date = str(expected_last_close(date.today()))
        (run_dir / "meta.json").write_text(json.dumps({
            "data": {"last_date": artifact_date},
            "execution_inputs": {
                "date": artifact_date,
                "adv_window": 21,
                "adv_participation_cap": 0.05,
            },
        }))
        settings = TastySettings(
            client_secret="x",
            refresh_token="y",
            account_number="TEST123",
            is_test=True,
            audit_path=output_root / "audit.jsonl",
        )
        service = DashboardService(
            output_root=output_root, settings=settings, broker=FakeBroker()
        )
        plan = service.build_rebalance_plan(min_order_notional=0.0)
        assert plan["safety_complete"] is True
        assert plan["adv_capped_orders"] == 1
        assert plan["orders"][0]["reason"] == "adv_capped"
        assert plan["orders"][0]["qty"] == 5


if __name__ == "__main__":
    test_dashboard_plan_applies_adv_cap()
    print("DASHBOARD ADV TEST PASSED")
