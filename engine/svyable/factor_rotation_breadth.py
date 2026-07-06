"""Cross-sectional rotation and breadth factors.

This family targets a missing board role: early leadership rotation. It looks for
names whose relative rank, sponsorship, and reclaim behavior are improving before
they become obvious absolute-momentum leaders. All factors are causal daily OHLCV
transforms and oriented so higher values are more attractive to own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.factor_ohlcv_tools import atr, close_location, register_factor, rel_dollar_volume
from svyable.panel import EPS, Panel


def _rank_pct(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True).sub(0.5).mul(2.0)


def _breadth(panel: Panel, window: int = 5) -> pd.Series:
    return (panel.ret > 0).mean(axis=1).rolling(window, min_periods=max(2, window // 2)).mean()


def relative_momentum_spread(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Medium-horizon asset momentum relative to the daily cross-section."""
    ret21 = panel.close / (panel.close.shift(21) + EPS) - 1.0
    ret63 = panel.close / (panel.close.shift(63) + EPS) - 1.0
    vol = panel.ret.rolling(42, min_periods=21).std() * np.sqrt(21.0)
    score = (0.70 * ret21 + 0.30 * ret63 / np.sqrt(3.0)) / (vol + EPS)
    return _rank_pct(score).clip(-2.0, 2.0)


def rank_improvement_velocity(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Acceleration in cross-sectional rank over the last month."""
    ret21 = panel.close / (panel.close.shift(21) + EPS) - 1.0
    rank_now = panel.close.div(panel.close.shift(21) + EPS).rank(axis=1, pct=True)
    rank_prior = ret21.shift(21).rank(axis=1, pct=True)
    return ((rank_now - rank_prior) * 2.0).clip(-2.0, 2.0)


def relative_volume_sponsorship(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Improving dollar-volume sponsorship versus the cross-section."""
    rel = rel_dollar_volume(panel, 8, 84)
    rank = _rank_pct(rel)
    up_confirm = panel.ret.rolling(5, min_periods=3).sum().clip(lower=0.0)
    vol = panel.ret.rolling(42, min_periods=21).std() * np.sqrt(5.0)
    return (rank * (1.0 + (up_confirm / (vol + EPS)).clip(0.0, 3.0))).clip(-4.0, 4.0)


def breadth_thrust_participation(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Participation when broad single-name breadth is expanding."""
    breadth = _breadth(panel, 5)
    breadth_delta = breadth.diff(5).clip(lower=0.0)
    own_thrust = panel.ret.rolling(5, min_periods=3).sum() / (panel.ret.rolling(42, min_periods=21).std() * np.sqrt(5.0) + EPS)
    loc = 1.0 + close_location(panel).clip(lower=0.0)
    return (own_thrust.clip(lower=0.0).mul(1.0 + 3.0 * breadth_delta, axis=0) * loc).clip(-5.0, 5.0)


def leader_pullback_accumulation(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """High relative-strength leader pulling back quietly with constructive closes."""
    ret63 = panel.close / (panel.close.shift(63) + EPS) - 1.0
    leadership = _rank_pct(ret63).clip(lower=0.0)
    pullback = (-(panel.close / (panel.close.shift(5) + EPS) - 1.0)).clip(lower=0.0)
    atr_pct = atr(panel, 21) / (panel.close + EPS)
    pullback_z = (pullback / (np.sqrt(5.0) * (atr_pct + EPS))).clip(0.0, 4.0)
    calm_range = (atr(panel, 10) / (atr(panel, 63) + EPS)).clip(0.25, 4.0)
    calm = (1.0 / calm_range).clip(0.25, 4.0)
    loc = 1.0 + close_location(panel).clip(lower=0.0)
    return (leadership * pullback_z * calm * loc).clip(-5.0, 5.0)


def weak_breadth_relative_reclaim(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    """Single-name reclaim behavior when broad breadth is weak."""
    breadth = _breadth(panel, 5)
    weak_breadth = (0.50 - breadth).clip(lower=0.0)
    intraday = panel.close / (panel.open + EPS) - 1.0
    atr_pct = atr(panel, 21) / (panel.close + EPS)
    reclaim = (intraday / (atr_pct + EPS)).clip(-5.0, 5.0).clip(lower=0.0)
    relative_day = panel.ret.sub(panel.ret.median(axis=1), axis=0)
    rel_strength = (relative_day / (panel.ret.rolling(42, min_periods=21).std() + EPS)).clip(-5.0, 5.0).clip(lower=0.0)
    return (reclaim * rel_strength).mul(1.0 + 4.0 * weak_breadth, axis=0).clip(-5.0, 5.0)


def register_rotation_breadth() -> None:
    register_factor("relative_momentum_spread", "momentum", relative_momentum_spread, proven=False, lineage="cross-sectional relative momentum", description="Medium-horizon momentum ranked versus the current cross-section.")
    register_factor("rank_improvement_velocity", "momentum", rank_improvement_velocity, proven=False, lineage="cross-sectional rank improvement", description="Acceleration in relative rank over the last month.")
    register_factor("relative_volume_sponsorship", "liquidity", relative_volume_sponsorship, proven=False, lineage="relative volume sponsorship", description="Improving dollar-volume sponsorship versus the cross-section.")
    register_factor("breadth_thrust_participation", "momentum", breadth_thrust_participation, proven=False, lineage="breadth thrust participation", description="Own-name participation when broad single-name breadth is expanding.")
    register_factor("leader_pullback_accumulation", "momentum", leader_pullback_accumulation, proven=False, lineage="leader pullback accumulation", description="Relative-strength leader pulling back quietly with constructive closes.")
    register_factor("weak_breadth_relative_reclaim", "resilience", weak_breadth_relative_reclaim, proven=False, lineage="weak breadth relative reclaim", description="Single-name reclaim behavior during weak breadth.")


register_rotation_breadth()
from svyable import strategy_rotation_breadth as _strategy_rotation_breadth  # noqa: F401,E402
