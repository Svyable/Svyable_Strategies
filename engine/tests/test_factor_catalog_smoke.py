"""Catalog-wide factor smoke tests.

Family-specific tests validate selected extensions, but side-effect-registered
factor families can otherwise bypass those curated lists. This test catches
all-NaN registered factors before they fail later during strategy selection.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import factor_library as flib
from svyable.config import nasdaq_lo_config
from svyable.providers import SyntheticProvider

CATALOG_SMOKE_DAYS = 900


def _last_valid_summary(frame):
    valid_rows = frame.notna().any(axis=1)
    if not valid_rows.any():
        return {"ever_valid": False, "valid_rows": 0, "last_valid_date": None}
    last = valid_rows[valid_rows].index[-1]
    return {
        "ever_valid": True,
        "valid_rows": int(valid_rows.sum()),
        "last_valid_date": str(last.date() if hasattr(last, "date") else last),
    }


def test_every_registered_factor_has_latest_smoke_signal():
    cfg = nasdaq_lo_config()
    panel = SyntheticProvider(n_assets=40, n_days=CATALOG_SMOKE_DAYS, seed=7).get_panel()
    names = list(flib.factor_metadata().index)
    scores = flib.compute_all(panel, cfg, names=names)

    failures = {
        name: _last_valid_summary(frame)
        for name, frame in scores.items()
        if not bool(frame.notna().any(axis=1).iloc[-1])
    }
    assert not failures, failures


if __name__ == "__main__":
    test_every_registered_factor_has_latest_smoke_signal()
    print("FACTOR CATALOG SMOKE TESTS PASSED")
