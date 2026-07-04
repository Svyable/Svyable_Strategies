"""Daily OHLCV price-action factor extensions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable import factors as legacy
from svyable.config import SvyableConfig
from svyable.panel import EPS, Panel


def _register(name: str, sleeve: str, fn, *, proven: bool, lineage: str, description: str) -> None:
    legacy.REGISTRY.setdefault(name, {"fn": fn, "sleeve": sleeve, "proven": proven, "lineage": lineage, "description": description})


def _true_range(panel: Panel) -> pd.DataFrame:
    prev_close = panel.close.shift(1)
    return np.maximum(panel.high - panel.low, np.maximum((panel.high - prev_close).abs(), (panel.low - prev_close).abs()))


def _atr(panel: Panel, window: int = 14) -> pd.DataFrame:
    return _true_range(panel).rolling(window, min_periods=max(5, window // 2)).mean()


def channel_pressure(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    window = 63
    atr = _atr(panel, 14) + EPS
    hi = panel.high.rolling(window, min_periods=32).max().shift(1)
    lo = panel.low.rolling(window, min_periods=32).min().shift(1)
    width = hi - lo + EPS
    location = ((panel.close - lo) / width - 0.5).clip(-1.5, 1.5)
    upper = ((panel.close - hi) / atr).clip(-5.0, 5.0)
    lower = ((panel.close - lo) / atr).clip(-5.0, 5.0)
    return (1.5 * location + 0.7 * upper + 0.3 * lower).clip(-6.0, 6.0)


def compression_thrust(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    atr = _atr(panel, 14)
    short = atr.rolling(20, min_periods=10).mean()
    long = atr.rolling(126, min_periods=63).median()
    compression = (long / (short + EPS)).clip(0.25, 4.0)
    thrust = panel.close / (panel.close.shift(5) + EPS) - 1.0
    vol_unit = atr / (panel.close + EPS)
    return (compression * thrust / (vol_unit + EPS)).clip(-6.0, 6.0)


def gap_continuation(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    prev_close = panel.close.shift(1)
    overnight = panel.open / (prev_close + EPS) - 1.0
    intraday = panel.close / (panel.open + EPS) - 1.0
    atr_pct = _atr(panel, 14) / (prev_close + EPS)
    gap_strength = (overnight.abs() / (atr_pct + EPS)).clip(0.0, 4.0)
    continuation = np.sign(overnight) * intraday
    return (continuation * np.sqrt(1.0 + gap_strength)).rolling(10, min_periods=5).sum().clip(-5.0, 5.0)


def range_participation(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    tr = _true_range(panel)
    expansion = (tr / (tr.rolling(21, min_periods=10).median() + EPS)).clip(0.25, 4.0)
    location = ((panel.close - panel.low) / (panel.high - panel.low + EPS) - 0.5).clip(-0.5, 0.5)
    rel_volume = (panel.dollar_volume / (panel.dollar_volume.rolling(63, min_periods=32).median() + EPS)).clip(0.25, 4.0)
    return (location * expansion * np.sqrt(rel_volume)).clip(-5.0, 5.0)


def range_rejection(panel: Panel, cfg: SvyableConfig) -> pd.DataFrame:
    window = 21
    atr = _atr(panel, 14) + EPS
    hi = panel.high.rolling(window, min_periods=10).max().shift(1)
    lo = panel.low.rolling(window, min_periods=10).min().shift(1)
    location = ((panel.close - panel.low) / (panel.high - panel.low + EPS) - 0.5).clip(-0.5, 0.5)
    lower_reject = ((lo - panel.low) / atr).clip(lower=0.0, upper=4.0) * location.clip(lower=0.0)
    upper_reject = ((panel.high - hi) / atr).clip(lower=0.0, upper=4.0) * (-location).clip(lower=0.0)
    return (lower_reject - upper_reject).clip(-4.0, 4.0)


def register_price_action_frontier() -> None:
    _register("channel_pressure", "momentum", channel_pressure, proven=False, lineage="daily OHLCV channel pressure", description="ATR-normalized pressure versus the prior 63-day range.")
    _register("compression_thrust", "momentum", compression_thrust, proven=False, lineage="daily OHLCV compression-thrust", description="Five-day thrust amplified by compressed ATR.")
    _register("gap_continuation", "momentum", gap_continuation, proven=False, lineage="daily OHLCV gap continuation", description="Intraday continuation in the direction of the overnight gap.")
    _register("range_participation", "momentum", range_participation, proven=False, lineage="daily OHLCV range participation", description="Close-location strength on expanding range and elevated dollar volume.")
    _register("range_rejection", "meanrev", range_rejection, proven=False, lineage="daily OHLCV range rejection", description="Failed short-range extension with close-location reversal evidence.")


register_price_action_frontier()
from svyable import strategy_price_action_frontier as _strategy_price_action_frontier  # noqa: F401,E402
