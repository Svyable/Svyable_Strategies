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
from svyable.risk import apply_risk_budget, backtest_pnl
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


def _calm(n_assets: int = 30, n_days: int = 800, seed: int = 5) -> pd.DataFrame:
    """A benign, mildly-drifting regime with no crisis anywhere."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    idio = rng.normal(0.0, 0.010, size=(n_days, n_assets))
    common = rng.normal(0.0003, 0.004, size=(n_days, 1))
    return pd.DataFrame(idio + common, index=idx,
                        columns=[f"A{i:02d}" for i in range(n_assets)])


def _equal_weight(returns: pd.DataFrame) -> pd.DataFrame:
    unit = returns.notna().astype(float)
    return unit.div(unit.sum(axis=1), axis=0).fillna(0.0)


def _overlay_net_returns(returns: pd.DataFrame, cfg) -> pd.Series:
    unit = _equal_weight(returns)
    market = returns.mean(axis=1, skipna=True)
    stress = pd.Series(0.0, index=returns.index)
    result = apply_risk_budget(unit, returns, market, stress, cfg)
    return backtest_pnl(result.final_weights, returns, cfg)["net_ret"]


def _max_drawdown(net: pd.Series) -> float:
    equity = (1.0 + net.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())   # <= 0


def _total_return(net: pd.Series) -> float:
    return float((1.0 + net.fillna(0.0)).prod() - 1.0)


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
    # before any component window can fill (breadth is the earliest at
    # ~breadth_win/2 days) no signal is estimable, so no de-risking
    assert (throttle.iloc[:60] == 1.0).all()
    # the turbulence component itself must stay silent until its model window
    # plus the percentile-rank burn-in are both available
    turb_signal = regime["turb_signal"].iloc[: cfg.turb_win + 63].fillna(0.0)
    assert (turb_signal == 0.0).all(), "turbulence de-risked before estimable"
    # crisis days must be meaningfully throttled vs calm days
    calm = throttle.iloc[580:650].mean()
    crisis = throttle.iloc[660:750].mean()
    assert calm > 0.90, f"calm regime throttled at {calm:.3f}"
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
    # the regime multiplier may add at most the bounded risk-on boost
    assert (on.budget <= off.budget * cfg_on.regime_boost_cap + 1e-9).all()
    # with the boost disabled the regime stack only ever removes budget
    cfg_no_boost = nasdaq_lo_config(regime_boost_cap=1.0)
    no_boost = apply_risk_budget(
        unit, panel.ret, panel.market_ret, stress, cfg_no_boost
    )
    assert (no_boost.budget <= off.budget + 1e-12).all()
    assert (no_boost.regime["multiplier"] <= 1.0 + 1e-12).all()
    # everything stays inside the leverage rails
    for result in (on, off, no_boost):
        assert float(result.budget.min()) >= cfg_on.lev_min - 1e-12
        assert float(result.budget.max()) <= cfg_on.lev_cap + 1e-12


def test_missing_assets_do_not_dilute_crisis_turbulence():
    """Halted names on a crisis day must not average the reading back down:
    the distance is normalized by assets actually observed, not model width."""
    returns = _calm_then_crisis()
    full = turbulence_index(returns)

    gapped = returns.copy()
    crisis_days = gapped.index[660:700]
    gapped.loc[crisis_days, gapped.columns[:12]] = np.nan  # 40% of names halt
    diluted = turbulence_index(gapped)

    full_crisis = full.loc[crisis_days].mean()
    gapped_crisis = diluted.loc[crisis_days].mean()
    assert gapped_crisis > 0.60 * full_crisis, (
        f"missing data diluted crisis turbulence: "
        f"{full_crisis:.2f} -> {gapped_crisis:.2f}"
    )


def test_panic_baseline_is_robust_to_long_crises():
    """A months-long high-vol regime must not normalize its own baseline away.
    With a median/MAD baseline the vol z-score stays elevated late in a crisis
    that still occupies less than half of the trailing baseline window."""
    from svyable.turbulence import panic_state

    rng = np.random.default_rng(11)
    n_assets, n_days = 25, 600
    calm_vol, crisis_vol = 0.006, 0.030
    crisis_start, crisis_len = 350, 120  # < half of the 252-day baseline window
    idx = pd.bdate_range("2021-01-04", periods=n_days)
    ret = rng.normal(0.0004, calm_vol, size=(n_days, n_assets))
    ret[crisis_start : crisis_start + crisis_len] = rng.normal(
        -0.004, crisis_vol, size=(crisis_len, n_assets)
    )
    returns = pd.DataFrame(
        ret, index=idx, columns=[f"A{i:02d}" for i in range(n_assets)]
    )

    cfg = nasdaq_lo_config()
    panic = panic_state(returns, cfg)
    vol_z = panic["market_vol_z"]

    onset = vol_z.iloc[crisis_start + 5 : crisis_start + 25].mean()
    late = vol_z.iloc[crisis_start + crisis_len - 25 : crisis_start + crisis_len].mean()
    assert onset > 3.0, f"crisis not detected at onset: {onset:.2f}"
    # a mean/std baseline would have decayed the late reading toward zero; the
    # robust baseline must still flag it strongly
    assert late > 2.0, f"crisis normalized its own baseline away: {late:.2f}"


def test_defensive_boost_cap_disables_risk_on_multiplier():
    """A regime_boost_cap of 1.0 (the defensive profile) must make the
    multiplier a pure de-risking throttle."""
    returns = _calm_then_crisis()
    cfg = nasdaq_lo_config(regime_boost_cap=1.0)
    regime = regime_frame(returns, cfg)
    assert (regime["multiplier"] <= 1.0 + 1e-12).all()
    assert (regime["multiplier"] >= cfg.turb_floor - 1e-12).all()
    pd.testing.assert_series_equal(
        regime["multiplier"], regime["throttle"], check_names=False
    )


def test_smoothing_cuts_multiplier_turnover_without_losing_protection():
    """The composite EMA must materially reduce whole-book multiplier turnover
    (a direct trading cost) while still de-risking through the crisis."""
    returns = _calm_then_crisis()
    raw = regime_frame(returns, nasdaq_lo_config(regime_smooth_span=1))
    smooth = regime_frame(returns, nasdaq_lo_config(regime_smooth_span=5))

    raw_turnover = float(raw["multiplier"].diff().abs().sum())
    smooth_turnover = float(smooth["multiplier"].diff().abs().sum())
    assert smooth_turnover < 0.75 * raw_turnover, (
        f"smoothing did not cut multiplier turnover: "
        f"{raw_turnover:.2f} -> {smooth_turnover:.2f}"
    )
    # protection is retained: the crisis is still de-risked hard
    assert smooth["throttle"].iloc[660:750].mean() < 0.90


def test_overlay_protects_drawdown_without_sacrificing_return():
    """On a calm->crisis path the overlay must cut the crash drawdown while
    keeping at least as much total return — earning its keep, not just cutting
    exposure and leaving return on the table."""
    returns = _calm_then_crisis()
    on = _overlay_net_returns(returns, nasdaq_lo_config(turbulence_enabled=True))
    off = _overlay_net_returns(returns, nasdaq_lo_config(turbulence_enabled=False))

    assert _max_drawdown(on) > _max_drawdown(off) + 0.01, (
        f"overlay did not shield the crash: "
        f"{_max_drawdown(off):.3f} -> {_max_drawdown(on):.3f}"
    )
    assert _total_return(on) >= _total_return(off) - 1e-9, (
        "overlay gave up return relative to running flat-out"
    )


def test_overlay_is_near_neutral_in_a_calm_regime():
    """No crisis anywhere: the overlay must stay close to fully invested and
    must not quietly bleed return through false de-risking."""
    returns = _calm(n_days=800)
    regime = regime_frame(returns, nasdaq_lo_config())
    assert float(regime["multiplier"].mean()) > 0.95, "false de-risking in calm"

    on = _overlay_net_returns(returns, nasdaq_lo_config(turbulence_enabled=True))
    off = _overlay_net_returns(returns, nasdaq_lo_config(turbulence_enabled=False))
    # over an ~3y calm path the overlay should cost almost nothing
    assert _total_return(on) > _total_return(off) - 0.01, (
        f"overlay leaked return in calm: {_total_return(off):.3f} vs {_total_return(on):.3f}"
    )


if __name__ == "__main__":
    test_turbulence_spikes_and_stays_elevated_in_crisis()
    test_absorption_rises_when_market_couples()
    test_throttle_derisks_in_crisis_and_respects_bounds()
    test_regime_is_causal()
    test_risk_budget_integration_and_disable_flag()
    test_missing_assets_do_not_dilute_crisis_turbulence()
    test_panic_baseline_is_robust_to_long_crises()
    test_defensive_boost_cap_disables_risk_on_multiplier()
    test_smoothing_cuts_multiplier_turnover_without_losing_protection()
    test_overlay_protects_drawdown_without_sacrificing_return()
    test_overlay_is_near_neutral_in_a_calm_regime()
    print("TURBULENCE TESTS PASSED")
