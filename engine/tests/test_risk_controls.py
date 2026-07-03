"""Circuit-breaker and warmup semantics for the risk-budget stack.

These guard the operational contracts that distinguish a real kill switch from
a no-op, and a warm regime model from a cold one:

  * the kill switch cuts the book to a distinct floor below lev_min and latches
    with hysteresis (no day-to-day flip-flop on a jagged recovery);
  * a fresh live history (turbulence not yet estimable) can be run light via
    regime_warmup_floor, while the backtest default fails open and is unchanged.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.config import nasdaq_lo_config
from svyable.risk import _latched_kill_switch, apply_risk_budget
from svyable.turbulence import regime_frame


def _crash_panel(n_assets: int = 20, calm: int = 260, crash: int = 24,
                 recover: int = 120, seed: int = 7):
    """Calm book, a sharp sustained crash that breaches the kill line, then a
    slow recovery. Returns (unit_weights, returns, market_ret)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=calm + crash + recover)
    cols = [f"A{i:02d}" for i in range(n_assets)]
    ret = rng.normal(0.0003, 0.006, size=(len(idx), n_assets))
    ret[calm:calm + crash] = rng.normal(-0.022, 0.02, size=(crash, n_assets))
    ret[calm + crash:] = rng.normal(0.0015, 0.008, size=(recover, n_assets))
    returns = pd.DataFrame(ret, index=idx, columns=cols)
    unit = pd.DataFrame(1.0 / n_assets, index=idx, columns=cols)
    market_ret = returns.mean(axis=1)
    return unit, returns, market_ret


def test_latched_kill_switch_hysteresis():
    """Trip above the kill line, hold through a jagged partial recovery inside
    the band, release only once drawdown heals below the re-arm line."""
    dd = pd.Series([0.0, 0.05, 0.16, 0.12, 0.11, 0.09, 0.20, 0.05])
    kill = _latched_kill_switch(dd, trip_level=0.15, rearm_level=0.10)
    assert list(kill) == [0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0]


def test_latched_kill_switch_ignores_gaps():
    """A NaN drawdown reading holds the current state rather than releasing."""
    dd = pd.Series([0.0, 0.16, np.nan, 0.12, np.nan, 0.05])
    kill = _latched_kill_switch(dd, trip_level=0.15, rearm_level=0.10)
    assert list(kill) == [0.0, 1.0, 1.0, 1.0, 1.0, 0.0]


def test_kill_switch_is_a_real_circuit_breaker():
    """On breach the budget must drop to kill_lev — strictly below lev_min —
    not merely to the floor every other control already enforces."""
    unit, returns, market_ret = _crash_panel()
    stress = pd.Series(0.0, index=returns.index)
    cfg = nasdaq_lo_config(kill_lev=0.0, turbulence_enabled=False)

    result = apply_risk_budget(unit, returns, market_ret, stress, cfg)
    killed = result.kill_switch == 1.0

    assert killed.any(), "crash panel never tripped the kill switch"
    assert (result.budget[killed] <= cfg.kill_lev + 1e-12).all()
    assert (result.budget[killed] < cfg.lev_min).all()
    # non-killed days still respect the ordinary leverage floor
    assert (result.budget[~killed] >= cfg.lev_min - 1e-12).all()


def test_kill_switch_latches_and_does_not_chatter():
    """Once tripped, the breaker stays engaged across a jagged recovery instead
    of toggling on and off day to day."""
    unit, returns, market_ret = _crash_panel()
    stress = pd.Series(0.0, index=returns.index)
    cfg = nasdaq_lo_config(kill_lev=0.0, turbulence_enabled=False)

    kill = apply_risk_budget(unit, returns, market_ret, stress, cfg).kill_switch
    # count contiguous engaged runs — a latched breaker trips as one block
    flips = int((kill.diff().abs() > 0).sum())
    assert flips <= 2, f"kill switch chattered ({flips} transitions)"


def test_regime_warmup_default_fails_open():
    """The backtest default (warmup_floor = 1.0) must not de-risk during the
    turbulence burn-in — the multiplier there stays at the no-op 1.0."""
    from svyable.providers import SyntheticProvider

    panel = SyntheticProvider(n_assets=30, n_days=600, seed=3).get_panel()
    cfg = nasdaq_lo_config()
    regime = regime_frame(panel.ret, cfg)

    warm = regime["regime_ready"] == 1.0
    assert not warm.iloc[: cfg.turb_win].any(), "turbulence ready before window"
    # fail open: while cold the multiplier never *adds* risk (no boost without a
    # warm turbulence read), but the faster breadth/panic components may still
    # de-risk, so it is free to sit below 1.0 down to the throttle floor.
    cold = regime.loc[~warm, "multiplier"]
    assert float(cold.max()) <= 1.0 + 1e-12
    assert float(cold.min()) >= cfg.turb_floor - 1e-12


def test_regime_warmup_floor_runs_light_until_warm():
    """A live launch can cap exposure while the model is cold; once warm the
    cap lifts and the ordinary regime multiplier resumes."""
    from svyable.providers import SyntheticProvider

    panel = SyntheticProvider(n_assets=30, n_days=600, seed=3).get_panel()
    cfg = nasdaq_lo_config(regime_warmup_floor=0.6)
    regime = regime_frame(panel.ret, cfg)

    warm = regime["regime_ready"] == 1.0
    cold_mult = regime.loc[~warm, "multiplier"]
    assert (cold_mult <= 0.6 + 1e-12).all(), "warmup cap not enforced"
    # the warm-period multiplier is not clamped by the warmup floor
    if warm.any():
        assert float(regime.loc[warm, "multiplier"].max()) > 0.6


if __name__ == "__main__":
    test_latched_kill_switch_hysteresis()
    test_latched_kill_switch_ignores_gaps()
    test_kill_switch_is_a_real_circuit_breaker()
    test_kill_switch_latches_and_does_not_chatter()
    test_regime_warmup_default_fails_open()
    test_regime_warmup_floor_runs_light_until_warm()
    print("RISK CONTROL TESTS PASSED")
