"""Import-boundary regression for the low-level tastytrade REST module."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import svyable.tastytrade as tastytrade


def test_tastytrade_rest_module_exports_only_transport_client():
    assert tastytrade.__all__ == ["TastytradeClient"]
    assert hasattr(tastytrade, "TastytradeClient")
    assert not hasattr(tastytrade, "TastytradeBroker")
    assert "Broker" not in tastytrade.__all__


if __name__ == "__main__":
    test_tastytrade_rest_module_exports_only_transport_client()
    print("TASTY REST BOUNDARY TESTS PASSED")
