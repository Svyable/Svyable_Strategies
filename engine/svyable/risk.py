"""Risk budget stack (strategy.md §12.4): vol targeting x drawdown throttle,
then an independent overlay, plus the kill-switch series and cash yield.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from svyable.panel import EPS
from svyable.config import SvyableConfig
from svyable.sleeves import market_drawdown

ANN = 252.0


@dataclass
class RiskResult:
    final_weights: pd.DataFrame
    budget: pd.Series
    overlay: pd.Series
    throttle: pd.Series
    realized_vol: pd.Series
    kill_switch: pd.Series      # 1.0 on days the kill rule is tripped
    regime: pd.DataFrame | None = None   # turbulence/absorption diagnostics


def ewma_vol(port_ret: pd.Series, lam: float) -> pd.Series:
    var = (port_ret.fillna(0.0) ** 2).ewm(alpha=1.0 - lam, adjust=False).mean()
    return np.sqrt(var * ANN)


def apply_risk_budget(unit_weights: pd.DataFrame, returns: pd.DataFrame,
                      mkt_ret: pd.Series, stress: pd.Series,
                      cfg: SvyableConfig) -> RiskResult:
    # portfolio returns of the unit book (weights known at t-1 earn t's return)
    port_ret = (unit_weights.shift(1) * returns).sum(axis=1)

    vol = ewma_vol(port_ret, cfg.ewma_vol_lambda)
    tv = cfg.target_vol + (cfg.target_vol_stressed - cfg.target_vol) * stress
    lev = (tv / (vol + 1e-8)).clip(cfg.lev_min, cfg.lev_cap)

    # drawdown throttle on the market curve
    dd = market_drawdown(mkt_ret, cfg.dd_win)
    throttle = (1.0 - cfg.risk_off_stretch * dd).clip(cfg.risk_off_floor, 1.0)

    budget = (lev * throttle).clip(cfg.lev_min, cfg.lev_cap)

    # independent overlay (gtp51max lesson): realized-vol scaler x dd throttle
    real63 = port_ret.rolling(cfg.overlay_vol_win, min_periods=10).std() * np.sqrt(ANN)
    vol_ov = (cfg.target_vol / (real63 + EPS)).clip(*cfg.overlay_clip)
    vol_ov = vol_ov.where(real63 <= cfg.overlay_max_vol,
                          other=cfg.target_vol / (cfg.overlay_max_vol + EPS))
    overlay = (vol_ov * throttle).clip(*cfg.overlay_clip).fillna(1.0)

    budget = (budget * overlay).clip(cfg.lev_min, cfg.lev_cap)

    # turbulence throttle: Mahalanobis distance + absorption ratio react to
    # correlation breaks and systemic coupling before realized vol can
    regime = None
    if cfg.turbulence_enabled:
        from svyable.turbulence import regime_frame

        regime = regime_frame(returns, cfg)
        budget = (budget * regime["throttle"]).clip(cfg.lev_min, cfg.lev_cap)

    # kill switch: own-book drawdown breaches mult x sanctioned backtest MaxDD
    scaled_ret = port_ret * budget.shift(1).fillna(cfg.lev_min)
    own_dd = market_drawdown(scaled_ret, cfg.dd_win)
    kill = (own_dd > cfg.kill_dd_mult * cfg.backtest_max_dd).astype(float)
    budget = budget.where(kill == 0.0, other=cfg.lev_min)

    final = unit_weights.mul(budget, axis=0).clip(upper=cfg.max_pos * cfg.lev_cap)

    return RiskResult(
        final_weights=final.fillna(0.0),
        budget=budget.fillna(cfg.lev_min),
        overlay=overlay,
        throttle=throttle,
        realized_vol=vol,
        kill_switch=kill,
        regime=regime,
    )


def backtest_pnl(final_weights: pd.DataFrame, returns: pd.DataFrame,
                 cfg: SvyableConfig) -> pd.DataFrame:
    """Daily P&L attribution net of costs, with cash yield on undeployed budget."""
    gross_ret = (final_weights.shift(1) * returns).sum(axis=1)
    turnover = final_weights.diff().abs().sum(axis=1).fillna(0.0)
    tc = turnover * cfg.tc_bps * 1e-4
    deployed = final_weights.abs().sum(axis=1).shift(1).fillna(0.0)
    cash = (1.0 - deployed).clip(lower=0.0) * (cfg.cash_yield_annual / ANN)
    net = gross_ret - tc + cash
    return pd.DataFrame({
        "gross_ret": gross_ret, "tc": tc, "cash_yield": cash,
        "net_ret": net, "turnover": turnover, "gross_exposure": deployed,
    })
