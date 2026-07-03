"""Coverage for the high-evidence OHLCV factor extensions.

These are additions to the production catalog layered on the legacy registry
(see svyable/factor_library.py). Each new factor must: register under the
correct sleeve, compute a finite cross-sectional score on a burned-in panel,
carry the intended maturity stage, and survive the robust research harness.
"""

import numpy as np

from svyable import factor_library as flib
from svyable.analysis_robust import factor_report
from svyable.config import nasdaq_lo_config
from svyable.providers import SyntheticProvider

NEW_PROVEN = ("gk_inv_vol", "intermediate_momentum")
NEW_SHADOW = ("return_seasonality",)
NEW_FACTORS = NEW_PROVEN + NEW_SHADOW

EXPECTED_SLEEVE = {
    "gk_inv_vol": "defensive",
    "intermediate_momentum": "momentum",
    "return_seasonality": "momentum",
}


def _panel():
    return SyntheticProvider(n_assets=40, n_days=900, seed=7).get_panel()


def test_new_factors_registered_with_expected_sleeves():
    for name in NEW_FACTORS:
        assert name in flib.legacy.REGISTRY, f"{name} not registered"
        assert flib.legacy.REGISTRY[name]["sleeve"] == EXPECTED_SLEEVE[name]
        assert flib.legacy.REGISTRY[name].get("lineage"), f"{name} missing lineage"


def test_maturity_staging_matches_intent():
    # proven factors earn a guaranteed floor; shadow research does not
    for name in NEW_PROVEN:
        assert flib.is_proven(name) is True
    for name in NEW_SHADOW:
        assert flib.is_proven(name) is False

    metadata = flib.factor_metadata(list(NEW_FACTORS))
    assert set(metadata.loc[list(NEW_PROVEN), "stage"]) == {"proven"}
    assert set(metadata.loc[list(NEW_SHADOW), "stage"]) == {"shadow"}


def test_factors_compute_finite_cross_sectional_scores():
    cfg = nasdaq_lo_config()
    panel = _panel()
    scores = flib.compute_all(panel, cfg, names=list(NEW_FACTORS))

    for name in NEW_FACTORS:
        frame = scores[name]
        assert frame.shape == panel.close.shape
        # after burn-in the factor must have real cross-sectional variation
        tail = frame.iloc[-63:]
        assert np.isfinite(tail.to_numpy()).any(), f"{name} all-NaN in tail"
        row_std = tail.std(axis=1).dropna()
        assert (row_std > 1e-9).any(), f"{name} has no cross-sectional spread"


def test_new_factors_flow_through_research_harness():
    cfg = nasdaq_lo_config()
    panel = _panel()
    report = factor_report(panel, cfg, names=list(NEW_FACTORS))

    assert set(NEW_FACTORS).issubset(set(report.index))
    # every factor lands in a defined promotion state, never NaN
    assert report.loc[list(NEW_FACTORS), "promotion_state"].notna().all()
    # shadow factors can only ever reach promotion_candidate, never validated
    shadow_states = set(report.loc[list(NEW_SHADOW), "promotion_state"])
    assert "validated" not in shadow_states


if __name__ == "__main__":
    test_new_factors_registered_with_expected_sleeves()
    test_maturity_staging_matches_intent()
    test_factors_compute_finite_cross_sectional_scores()
    test_new_factors_flow_through_research_harness()
    print("ok")
