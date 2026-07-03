"""Risk-budget stack with volatility management and structural regime control."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.panel import EPS
from svyable.sleeves import market_drawdown

ANN = 252.0


@dataclass
class RiskResult:
    final_weights: pd.DataFrame
    budget: pd.Series
    overlay: pd.Series
    throttle: pd.Series
    realized_vol: pd.Series
    kill_switch: pd.Series
    regime: pd.DataFrame | None = None


def ewma_vol(port_ret: pd.Series, lam: float) -> pd.Series:
    variance = (port_ret.fillna(0.0) ** 2).ewm(
        alpha=1.0 - lam,
        adjust=False,
    ).mean()
    return np.sqrt(variance * ANN)


def _latched_kill_switch(
    own_dd: pd.Series,
    trip_level: float,
    rearm_level: float,
) -> pd.Series:
    """Convert a drawdown series into a latched circuit-breaker state.

    Trips when drawdown exceeds ``trip_level`` and stays engaged until it heals
    below ``rearm_level`` (``rearm_level <= trip_level``). The hysteresis band
    stops the breaker from flickering on a jagged recovery. A non-finite reading
    holds the current state rather than releasing.
    """
    values = own_dd.to_numpy(dtype=np.float64)
    engaged = np.zeros(len(values), dtype=np.float64)
    state = False
    for i, dd in enumerate(values):
        if np.isfinite(dd):
            if state:
                if dd < rearm_level:
                    state = False
            elif dd > trip_level:
                state = True
        engaged[i] = 1.0 if state else 0.0
    return pd.Series(engaged, index=own_dd.index, name="kill_switch")


def apply_risk_budget(
    unit_weights: pd.DataFrame,
    returns: pd.DataFrame,
    mkt_ret: pd.Series,
    stress: pd.Series,
    cfg: SvyableConfig,
) -> RiskResult:
    """Scale a unit book using vol, drawdown, regime, and kill-switch controls."""
    port_ret = (unit_weights.shift(1) * returns).sum(axis=1)

    realized_vol = ewma_vol(port_ret, cfg.ewma_vol_lambda)
    target_vol = cfg.target_vol + (
        cfg.target_vol_stressed - cfg.target_vol
    ) * stress
    leverage = (target_vol / (realized_vol + EPS)).clip(
        cfg.lev_min,
        cfg.lev_cap,
    )

    market_dd = market_drawdown(mkt_ret, cfg.dd_win)
    drawdown_throttle = (
        1.0 - cfg.risk_off_stretch * market_dd
    ).clip(cfg.risk_off_floor, 1.0)
    budget = (leverage * drawdown_throttle).clip(
        cfg.lev_min,
        cfg.lev_cap,
    )

    trailing_vol = port_ret.rolling(
        cfg.overlay_vol_win,
        min_periods=10,
    ).std() * np.sqrt(ANN)
    # realized-vol overlay: cut exposure when book vol runs hot, but stop
    # tightening past overlay_max_vol and hand off to the drawdown and regime
    # controls — inverse-vol targeting is noisy and mean-reverting at the
    # extremes. Neutral (1.0) while the trailing window is still filling.
    capped_vol = trailing_vol.clip(upper=cfg.overlay_max_vol)
    vol_overlay = (cfg.target_vol / (capped_vol + EPS)).clip(*cfg.overlay_clip)
    overlay = (vol_overlay * drawdown_throttle).clip(
        *cfg.overlay_clip
    ).fillna(1.0)
    budget = (budget * overlay).clip(cfg.lev_min, cfg.lev_cap)

    regime = None
    if cfg.turbulence_enabled:
        from svyable.turbulence import regime_frame

        regime = regime_frame(returns, cfg)
        multiplier = regime.get("multiplier", regime["throttle"])
        budget = (budget * multiplier).clip(cfg.lev_min, cfg.lev_cap)

    scaled_ret = port_ret * budget.shift(1).fillna(cfg.lev_min)
    own_dd = market_drawdown(scaled_ret, cfg.dd_win)
    trip_level = cfg.kill_dd_mult * cfg.backtest_max_dd
    rearm_level = min(cfg.kill_rearm_mult * cfg.backtest_max_dd, trip_level)
    kill_switch = _latched_kill_switch(own_dd, trip_level, rearm_level)
    # a genuine breaker: cut to kill_lev (below every other floor) and latch
    budget = budget.where(kill_switch == 0.0, other=cfg.kill_lev)

    final_weights = unit_weights.mul(budget, axis=0).clip(
        upper=cfg.max_pos * cfg.lev_cap
    )

    return RiskResult(
        final_weights=final_weights.fillna(0.0),
        budget=budget.fillna(cfg.lev_min),
        overlay=overlay,
        throttle=drawdown_throttle,
        realized_vol=realized_vol,
        kill_switch=kill_switch,
        regime=regime,
    )


def backtest_pnl(
    final_weights: pd.DataFrame,
    returns: pd.DataFrame,
    cfg: SvyableConfig,
) -> pd.DataFrame:
    """Daily P&L attribution net of costs and inclusive of cash yield."""
    gross_ret = (final_weights.shift(1) * returns).sum(axis=1)
    turnover = final_weights.diff().abs().sum(axis=1).fillna(0.0)
    transaction_cost = turnover * cfg.tc_bps * 1e-4
    deployed = final_weights.abs().sum(axis=1).shift(1).fillna(0.0)
    cash_yield = (
        (1.0 - deployed).clip(lower=0.0)
        * (cfg.cash_yield_annual / ANN)
    )
    net_ret = gross_ret - transaction_cost + cash_yield
    return pd.DataFrame(
        {
            "gross_ret": gross_ret,
            "tc": transaction_cost,
            "cash_yield": cash_yield,
            "net_ret": net_ret,
            "turnover": turnover,
            "gross_exposure": deployed,
        }
    )
