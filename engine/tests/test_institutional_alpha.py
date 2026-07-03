"""Regression tests for institutional factors, regimes, and causal chimeras."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import factor_library as flib
from svyable.config import nasdaq_lo_config
from svyable.providers import SyntheticProvider
from svyable.strategy_blend import BlendSpec, resolve_component_weight_history
from svyable.strategy_registry import get_strategy, registry_frame
from svyable.turbulence import regime_frame


NEW_FACTORS = {
    "downside_beta_resilience",
    "beta_asymmetry",
    "drawdown_resilience",
    "gap_resilience",
    "multi_horizon_trend",
    "residual_trend_tstat",
    "volume_confirmed_breakout",
    "correlation_shock_resilience",
}


def test_institutional_factor_catalog_and_outputs():
    panel = SyntheticProvider(n_assets=24, n_days=620).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False)
    catalog = flib.factor_metadata()
    assert NEW_FACTORS <= set(catalog.index)
    assert catalog.loc["multi_horizon_trend", "stage"] == "proven"
    assert catalog.loc["beta_asymmetry", "stage"] == "shadow"

    factors = flib.compute_all(panel, cfg, names=sorted(NEW_FACTORS))
    for name, frame in factors.items():
        assert frame.shape == panel.close.shape
        assert frame.iloc[-63:].notna().sum().sum() > 0, name
        assert np.isfinite(frame.iloc[-63:].to_numpy()[np.isfinite(frame.iloc[-63:].to_numpy())]).all()


def test_institutional_strategy_mandates_are_distinct():
    registry = registry_frame()
    expected = {
        "q23_alpha_beta",
        "q23_crash_resilient_momentum",
        "q23_residual_alpha",
        "q23_dispersion_alpha",
    }
    assert expected <= set(registry.index)
    assert get_strategy("q23_alpha_beta").build_config().regime_boost_cap > 1.0
    assert get_strategy("q23_defensive_alpha").build_config().regime_boost_cap == 1.0
    assert (
        get_strategy("q23_crash_resilient_momentum").build_config().turb_floor
        < get_strategy("q23_alpha_beta").build_config().turb_floor
    )
    assert set(get_strategy("q23_residual_alpha").factor_names) != set(
        get_strategy("q23_alpha_beta").factor_names
    )


def test_regime_stack_is_bounded_and_observable():
    panel = SyntheticProvider(n_assets=24, n_days=700).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False)
    regime = regime_frame(panel.ret, cfg)
    required = {
        "turbulence",
        "turb_pct",
        "absorption",
        "breadth",
        "panic_signal",
        "regime_risk",
        "throttle",
        "risk_on_signal",
        "boost",
        "multiplier",
    }
    assert required <= set(regime.columns)
    valid = regime["multiplier"].dropna()
    assert len(valid) > 0
    assert valid.between(cfg.turb_floor, cfg.regime_boost_cap).all()
    assert regime["breadth"].dropna().between(0.0, 1.0).all()
    assert regime["panic_signal"].dropna().between(0.0, 1.0).all()


def _dummy_results(returns: pd.DataFrame):
    return {
        name: SimpleNamespace(pnl=pd.DataFrame({"net_ret": returns[name]}))
        for name in returns.columns
    }


def test_dynamic_chimera_history_is_causal_and_bounded():
    index = pd.date_range("2022-01-03", periods=260, freq="B")
    rng = np.random.default_rng(11)
    returns = pd.DataFrame(
        {
            "q23_hybrid_alpha": rng.normal(0.0005, 0.010, len(index)),
            "q23_defensive_alpha": rng.normal(0.0003, 0.006, len(index)),
            "q23_low_turnover": rng.normal(0.0004, 0.008, len(index)),
        },
        index=index,
    )
    spec = BlendSpec(
        blend_id="chimera_test_causal",
        display_name="Test causal chimera",
        description="test",
        components=(
            ("q23_hybrid_alpha", 1 / 3),
            ("q23_defensive_alpha", 1 / 3),
            ("q23_low_turnover", 1 / 3),
        ),
        method="alpha_risk",
        allocation_window=63,
        allocation_min_history=21,
        component_min_weight=0.10,
        component_max_weight=0.60,
    )
    history = resolve_component_weight_history(spec, _dummy_results(returns))
    assert np.allclose(history.sum(axis=1), 1.0)
    assert history.min().min() >= spec.component_min_weight - 1e-9
    assert history.max().max() <= spec.component_max_weight + 1e-9

    cutoff = 170
    shocked = returns.copy()
    shocked.iloc[cutoff + 1 :, 0] += 0.05
    history_shocked = resolve_component_weight_history(spec, _dummy_results(shocked))
    pd.testing.assert_frame_equal(
        history.iloc[: cutoff + 1],
        history_shocked.iloc[: cutoff + 1],
    )
    assert not np.allclose(
        history.iloc[-1].to_numpy(),
        history_shocked.iloc[-1].to_numpy(),
    )


if __name__ == "__main__":
    test_institutional_factor_catalog_and_outputs()
    test_institutional_strategy_mandates_are_distinct()
    test_regime_stack_is_bounded_and_observable()
    test_dynamic_chimera_history_is_causal_and_bounded()
    print("INSTITUTIONAL ALPHA TESTS PASSED")
