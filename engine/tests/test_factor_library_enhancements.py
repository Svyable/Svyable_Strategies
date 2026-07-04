"""Coverage for the high-evidence OHLCV factor extensions.

These are additions to the production catalog layered on the legacy registry
(see svyable/factor_library.py). Each new factor must: register under the
correct sleeve, compute a finite cross-sectional score on a burned-in panel,
carry the intended maturity stage, and survive the robust research harness.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

# Later cookbook extensions (technical, volatility, OU/reversal/range, quality).
# All enter as shadow research: they get no guaranteed weight floor and must earn
# promotion through the research harness.
EXTENSION_SHADOW = (
    "ma_cloud", "vol_breakout", "calm_flow", "vol_surprise", "idio_tail_risk",
    "ou_zscore_short", "ou_halflife_signal", "lrev", "hloc_close_position",
    "momentum_divergence",
)
EXTENSION_SLEEVE = {
    "ma_cloud": "momentum",
    "vol_breakout": "momentum",
    "calm_flow": "defensive",
    "vol_surprise": "defensive",
    "idio_tail_risk": "defensive",
    "ou_zscore_short": "meanrev",
    "ou_halflife_signal": "meanrev",
    "lrev": "meanrev",
    "hloc_close_position": "momentum",
    "momentum_divergence": "momentum",
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


def test_extension_factors_are_shadow_with_expected_sleeves():
    """Every later extension factor registers under the intended sleeve with a
    lineage and enters as shadow — no guaranteed floor until IC evidence."""
    for name in EXTENSION_SHADOW:
        assert name in flib.legacy.REGISTRY, f"{name} not registered"
        assert flib.legacy.REGISTRY[name]["sleeve"] == EXTENSION_SLEEVE[name]
        assert flib.legacy.REGISTRY[name].get("lineage"), f"{name} missing lineage"
        assert flib.is_proven(name) is False, f"{name} must be shadow"

    metadata = flib.factor_metadata(list(EXTENSION_SHADOW))
    assert set(metadata["stage"]) == {"shadow"}
    assert not metadata["guaranteed_floor"].any()


def test_extension_factors_compute_and_flow_through_harness():
    """Extension factors compute finite cross-sectional scores and land in a
    defined promotion state; being shadow, they can never reach 'validated'."""
    cfg = nasdaq_lo_config()
    panel = _panel()

    scores = flib.compute_all(panel, cfg, names=list(EXTENSION_SHADOW))
    for name in EXTENSION_SHADOW:
        tail = scores[name].iloc[-63:]
        assert np.isfinite(tail.to_numpy()).any(), f"{name} all-NaN in tail"
        assert (tail.std(axis=1).dropna() > 1e-9).any(), f"{name} has no spread"

    report = factor_report(panel, cfg, names=list(EXTENSION_SHADOW))
    assert set(EXTENSION_SHADOW).issubset(set(report.index))
    assert report.loc[list(EXTENSION_SHADOW), "promotion_state"].notna().all()
    assert "validated" not in set(report.loc[list(EXTENSION_SHADOW), "promotion_state"])


if __name__ == "__main__":
    test_new_factors_registered_with_expected_sleeves()
    test_maturity_staging_matches_intent()
    test_factors_compute_finite_cross_sectional_scores()
    test_new_factors_flow_through_research_harness()
    test_extension_factors_are_shadow_with_expected_sleeves()
    test_extension_factors_compute_and_flow_through_harness()
    print("ok")
