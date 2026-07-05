"""Residual alpha-catalyst factors for higher-conviction stock selection.

These factors are designed to add alpha pressure that is less beta-dependent than
plain trend: residual acceleration, residual breakout, absorption/reclaim after
failed downside moves, idiosyncratic trend quality, and volatility-transition
participation. All factors are causal daily OHLCV transforms and oriented so
higher values are more attractive to own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.factor_ohlcv_tools import atr, close_location, register_factor, rel_dollar_volume, true_range
from svyable.panel import EPS, Panel, residual_returns, rolling_beta


def _residual(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    return residual_returns(panel.ret, panel.market_ret, cfg.beta_win)


def residual_momentum_acceleration(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Acceleration of beta-stripped returns over 5 days versus the 21-day pace."""
    resid = _residual(panel, cfg)
    fast = resid.rolling(5, min_periods=3).sum()
    slow = resid.rolling(21, min_periods=10).sum() / np.sqrt(21.0 / 5.0)
    vol = resid.rolling(42, min_periods=21).std() * np.sqrt(5.0)
    return ((fast - slow / 4.0) / (vol + EPS)).clip(-6.0, 6.0)


def residual_breakout_confirmation(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Residual-price breakout confirmed by dollar-volume participation."""
    resid = _residual(panel, cfg).fillna(0.0)
    residual_index = (1.0 + resid).cumprod()
    prior_high = residual_index.rolling(63, min_periods=32).max().shift(1)
    resid_vol = resid.rolling(42, min_periods=21).std()
    breakout = ((residual_index / (prior_high + EPS) - 1.0) / (resid_vol + EPS)).clip(-6.0, 6.0)
    participation = np.sqrt(rel_dollar_volume(panel, 5, 63))
    return (breakout * participation).clip(-6.0, 6.0)


def downside_absorption_reversal(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Positive signal when recent downside is absorbed by strong closes and volume."""
    ret3 = panel.close / (panel.close.shift(3) + EPS) - 1.0
    atr_pct = atr(panel, 14) / (panel.close + EPS)
    downside = (-ret3 / (np.sqrt(3.0) * (atr_pct + EPS))).clip(0.0, 6.0)
    close_strength = close_location(panel).clip(lower=0.0)
    volume = np.sqrt(rel_dollar_volume(panel, 3, 63))
    follow = (panel.close / (panel.open + EPS) - 1.0).clip(lower=0.0) / (atr_pct + EPS)
    return (downside * (1.0 + close_strength) * volume * follow.clip(0.0, 4.0)).clip(-5.0, 5.0)


def failed_breakdown_reclaim(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Reclaim signal after probing below the prior monthly low and closing back strong."""
    prior_low = panel.low.rolling(21, min_periods=10).min().shift(1)
    average_range = atr(panel, 14) + EPS
    breakdown_probe = ((prior_low - panel.low) / average_range).clip(0.0, 5.0)
    reclaim = ((panel.close - prior_low) / average_range).clip(-5.0, 5.0).clip(lower=0.0)
    loc = close_location(panel).clip(lower=0.0)
    return (breakdown_probe * reclaim * (1.0 + loc)).clip(-5.0, 5.0)


def idiosyncratic_trend_quality(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Residual trend quality penalized for high market beta and unstable direction."""
    resid = _residual(panel, cfg)
    resid_mom = resid.rolling(63, min_periods=32).sum()
    resid_vol = resid.rolling(63, min_periods=32).std() * np.sqrt(63.0)
    resid_ir = resid_mom / (resid_vol + EPS)
    persistence = np.sign(resid).rolling(21, min_periods=10).mean().clip(-1.0, 1.0)
    beta = rolling_beta(panel.ret, panel.market_ret, cfg.beta_win).abs()
    beta_penalty = (1.0 / (1.0 + beta)).clip(0.25, 1.0)
    return (resid_ir * (1.0 + persistence) * beta_penalty).clip(-6.0, 6.0)


def volatility_transition_alpha(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Positive residual thrust as volatility exits compression into expansion."""
    tr = true_range(panel)
    short_range = tr.rolling(8, min_periods=4).mean()
    mid_range = tr.rolling(21, min_periods=10).median()
    long_range = tr.rolling(84, min_periods=42).median()
    prior_compression = (long_range.shift(3) / (mid_range.shift(3) + EPS)).clip(0.25, 5.0)
    fresh_expansion = (short_range / (mid_range + EPS)).clip(0.25, 5.0)
    resid = _residual(panel, cfg)
    thrust = resid.rolling(3, min_periods=2).sum() / (resid.rolling(21, min_periods=10).std() * np.sqrt(3.0) + EPS)
    return (prior_compression * np.sqrt(fresh_expansion) * thrust).clip(-6.0, 6.0)


def register_alpha_catalyst() -> None:
    register_factor("residual_momentum_acceleration", "momentum", residual_momentum_acceleration, proven=False, lineage="beta-stripped residual acceleration", description="Five-day residual return acceleration versus the recent 21-day pace.")
    register_factor("residual_breakout_confirmation", "momentum", residual_breakout_confirmation, proven=False, lineage="residual-price breakout confirmation", description="Residual cumulative-return breakout confirmed by dollar-volume participation.")
    register_factor("downside_absorption_reversal", "meanrev", downside_absorption_reversal, proven=False, lineage="downside absorption reversal", description="Recent downside absorbed by strong closes, intraday follow-through, and volume.")
    register_factor("failed_breakdown_reclaim", "meanrev", failed_breakdown_reclaim, proven=False, lineage="failed breakdown reclaim", description="Probe below prior monthly low followed by a strong reclaim close.")
    register_factor("idiosyncratic_trend_quality", "momentum", idiosyncratic_trend_quality, proven=False, lineage="idiosyncratic trend quality", description="Residual trend IR with directional persistence and beta-dependence penalty.")
    register_factor("volatility_transition_alpha", "momentum", volatility_transition_alpha, proven=False, lineage="volatility transition residual thrust", description="Positive residual thrust as range exits compression into expansion.")


register_alpha_catalyst()
from svyable import strategy_alpha_catalyst as _strategy_alpha_catalyst  # noqa: F401,E402
