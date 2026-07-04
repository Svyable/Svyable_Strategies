"""Tests for factor health helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.factor_health_tools import exposure_concentration, factor_review_summary, factor_trend_alerts


def test_factor_trend_alerts_classify_series():
    idx = pd.bdate_range("2025-01-01", periods=160)
    ic = pd.DataFrame(
        {
            "down_series": np.linspace(0.08, -0.03, len(idx)),
            "up_series": np.linspace(-0.01, 0.08, len(idx)),
            "flat_series": np.full(len(idx), 0.02),
        },
        index=idx,
    )

    alerts = factor_trend_alerts(ic)
    states = alerts.set_index("factor")["state"].to_dict()

    assert states["down_series"] == "deteriorating"
    assert states["up_series"] == "improving"
    assert states["flat_series"] == "stable"
    summary = factor_review_summary(alerts, pd.DataFrame())
    assert summary["deteriorating"] == 1
    assert summary["improving"] == 1


def test_exposure_concentration_flags_large_share():
    exposures = pd.DataFrame(
        [
            {"factor": "alpha_a", "exposure": 0.70},
            {"factor": "alpha_b", "exposure": 0.20},
            {"factor": "alpha_c", "exposure": -0.10},
        ]
    )

    result = exposure_concentration(exposures)

    assert result.iloc[0]["factor"] == "alpha_a"
    assert result.iloc[0]["state"] == "dominant"
    assert result["share_of_abs_exposure"].sum() <= 1.0 + 1e-9


if __name__ == "__main__":
    test_factor_trend_alerts_classify_series()
    test_exposure_concentration_flags_large_share()
    print("FACTOR HEALTH TOOLS TESTS PASSED")
