"""Turbulence/absorption regime model: causality, crisis damping, bounds,
and clean integration with the risk-budget stack.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.config import nasdaq_lo_config
from svyable.providers import SyntheticProvider
from svyable.risk import apply_risk_budget
from svyable.turbulence import absorption_ratio, regime_frame, turbulence_index


def _calm_then_crisis(n_assets: int = 30, n_days: int = 800, crisis_start: int = 650,
                      seed: int = 5) -> pd.DataFrame:
    """Low-correlation calm regime, then a high-vol, high-correlation crisis."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    idio = rng.normal(0.0, 0.010, size=(n_days, n_assets))
    common = rng.normal(0.0, 0.004, size=(n_days, 1))
    returns = idio + common
    # crisis: idio vol jumps ~1.5x and a large common factor takes over, so
    # correlations spike toward ~0.8 — both signatures of a real crash
    crisis_common = rng.normal(-0.004, 0.030, size=(n_days - crisis_start, 1))
    returns[crisis_start:] = (
        1.5 * idio[crisis_start:] + np.repeat(crisis_common, n_assets, axis=1)
    )
    return pd.DataFrame(returns, index=idx,
                        columns=[f"A{i:02d}" for i in range(n_assets)])


def test_turbulence_spikes_and_stays_elevated_in_crisis():
    """The winsorized long-window model must keep flagging a sustained crisis,
    not normalize it away after a few covariance refreshes."""
    returns = _calm_then_crisis()
    turb = turbulence_index(returns)
    calm = turb.iloc[550:650].mean()
    onset = turb.iloc[652:662].mean()
    late = turb.iloc[720:780].mean()
    assert onset > 3.0 * calm, f"no onset spike: {calm:.2f} -> {onset:.2f}"
    assert late > 2.0 * calm, f"crisis normalized away: {calm:.2f} -> {late:.2f}"


def test_absorption_rises_when_market_couples():
    returns = _calm_then_crisis()
    absorb = absorption_ratio(returns)
    calm = absorb.iloc[550:650].mean()
    crisis = absorb.iloc[720:].mean()   # allow the rolling window to fill with crisis
    assert crisis > calm + 0.10, f"absorption did not rise: {calm:.2f} -> {crisis:.2f}"


def test_throttle_derisks_in_crisis_and_respects_bounds():
    returns = _calm_then_crisis()
    cfg = nasdaq_lo_config()
    regime = regime_frame(returns, cfg)
    throttle = regime["throttle"]

    assert float(throttle.min()) >= cfg.turb_floor - 1e-12
    assert float(throttle.max()) <= 1.0 + 1e-12
    # early history (model not yet estimable) must not de-risk
    assert (throttle.iloc[: cfg.turb_win] == 1.0).all()
    # crisis days must be meaningfully throttled vs calm days
    calm = throttle.iloc[580:650].mean()
    crisis = throttle.iloc[660:750].mean()
    assert calm > 0.95, f"calm regime throttled at {calm:.3f}"
    assert crisis < calm - 0.10, f"no crisis de-risking: {calm:.3f} -> {crisis:.3f}"


def test_regime_is_causal():
    """Truncating the future must not change any past regime value."""
    returns = _calm_then_crisis()
    cfg = nasdaq_lo_config()
    full = regime_frame(returns, cfg)
    trunc = regime_frame(returns.iloc[:700], cfg)
    common = trunc.index
    diff = (full.loc[common] - trunc).abs()
    assert float(diff.max().max()) < 1e-12, "regime model saw the future"


def test_risk_budget_integration_and_disable_flag():
    panel = SyntheticProvider(n_assets=30, n_days=600, seed=3).get_panel()
    unit = panel.close.notna().astype(float)
    unit = unit.div(unit.sum(axis=1), axis=0)
    stress = pd.Series(0.0, index=panel.close.index)

    cfg_on = nasdaq_lo_config(turbulence_enabled=True)
    cfg_off = nasdaq_lo_config(turbulence_enabled=False)
    on = apply_risk_budget(unit, panel.ret, panel.market_ret, stress, cfg_on)
    off = apply_risk_budget(unit, panel.ret, panel.market_ret, stress, cfg_off)

    assert on.regime is not None and off.regime is None
    # throttle only ever removes budget, never adds
    assert (on.budget <= off.budget + 1e-12).all()
    # both stay inside the leverage rails
    for result in (on, off):
        assert float(result.budget.min()) >= cfg_on.lev_min - 1e-12
        assert float(result.budget.max()) <= cfg_on.lev_cap + 1e-12


if __name__ == "__main__":
    test_turbulence_spikes_in_crisis()
    test_absorption_rises_when_market_couples()
    test_throttle_derisks_in_crisis_and_respects_bounds()
    test_regime_is_causal()
    test_risk_budget_integration_and_disable_flag()
    print("TURBULENCE TESTS PASSED")
