"""Broker adapter safety regressions."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.brokers import LocalPaperBroker


def test_local_paper_rejects_oversell_in_long_only_mode():
    with TemporaryDirectory() as tmp:
        broker = LocalPaperBroker(Path(tmp) / "paper.json", starting_cash=1_000.0)
        broker.set_prices({"AAA": 10.0})
        result = broker.submit_order("AAA", 5, "sell")
        assert result["status"] == "rejected"
        assert broker.get_positions() == {}
        assert broker.get_account()["cash"] == 1_000.0


def test_local_paper_allows_closing_existing_long_position():
    with TemporaryDirectory() as tmp:
        broker = LocalPaperBroker(Path(tmp) / "paper.json", starting_cash=1_000.0)
        broker.set_prices({"AAA": 10.0})
        assert broker.submit_order("AAA", 5, "buy")["status"] == "filled"
        assert broker.submit_order("AAA", 5, "sell")["status"] == "filled"
        assert broker.get_positions() == {}
        assert broker.get_account()["cash"] == 1_000.0


if __name__ == "__main__":
    test_local_paper_rejects_oversell_in_long_only_mode()
    test_local_paper_allows_closing_existing_long_position()
    print("BROKER SAFETY TESTS PASSED")
