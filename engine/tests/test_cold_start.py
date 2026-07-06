from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.cold_start import cold_start_adjustment, latest_diagnostics  # noqa: E402
from svyable.config import nasdaq_lo_config  # noqa: E402
from svyable.construct import build_unit_weights  # noqa: E402
from svyable.panel import Panel  # noqa: E402
from svyable.weighting import composite_score  # noqa: E402


def _panel_with_new_symbol() -> Panel:
    idx = pd.bdate_range("2026-01-01", periods=80)
    cols = ["MATURE1", "MATURE2", "SPCX"]
    base = pd.DataFrame(
        {
            "MATURE1": np.linspace(100, 120, len(idx)),
            "MATURE2": np.linspace(80, 88, len(idx)),
            "SPCX": np.nan,
        },
        index=idx,
    )
    base.loc[idx[-12]:, "SPCX"] = np.linspace(50, 62, 12)
    open_ = base.shift(1).fillna(base) * 0.995
    high = base * 1.02
    low = base * 0.98
    volume = (base * 0 + 1_000_000.0).where(base.notna())
    return Panel(open=open_, high=high, low=low, close=base, volume=volume)


def test_composite_score_renormalizes_available_signal_weight():
    idx = pd.bdate_range("2026-01-01", periods=1)
    factors = {
        "short_signal": pd.DataFrame([[10.0, 0.0]], index=idx, columns=["SPCX", "OLD"]),
        "long_signal": pd.DataFrame([[np.nan, 0.0]], index=idx, columns=["SPCX", "OLD"]),
    }
    weights = pd.DataFrame([[0.5, 0.5]], index=idx, columns=["short_signal", "long_signal"])

    score = composite_score(factors, weights)

    assert float(score.loc[idx[0], "SPCX"]) == 10.0
    assert float(score.loc[idx[0], "OLD"]) == 0.0


def test_cold_start_keeps_new_symbol_eligible_but_shrunk():
    panel = _panel_with_new_symbol()
    idx, cols = panel.close.index, panel.close.columns
    factors = {
        "short_signal": pd.DataFrame(1.0, index=idx, columns=cols),
        "long_signal": pd.DataFrame(1.0, index=idx, columns=cols),
    }
    factors["long_signal"].loc[:, "SPCX"] = np.nan
    cfg = nasdaq_lo_config(
        cold_start_min_trading_days=10,
        cold_start_full_trading_days=63,
        cold_start_min_factor_coverage=0.10,
    )

    result = cold_start_adjustment(panel, factors, cfg)
    last = idx[-1]

    assert result.trading_age.loc[last, "SPCX"] == 12.0
    assert 0.0 < result.score_multiplier.loc[last, "SPCX"] < 1.0
    assert 0.0 < result.max_pos_multiplier.loc[last, "SPCX"] < 1.0
    assert result.max_pos_multiplier.loc[last, "MATURE1"] == 1.0

    diag = latest_diagnostics(result, last)
    assert bool(diag.loc["SPCX", "is_cold_start"])
    assert bool(diag.loc["SPCX", "eligible_by_cold_start"])


def test_construction_respects_cold_start_position_cap():
    idx = pd.bdate_range("2026-01-01", periods=5)
    cols = ["SPCX", "A", "B", "C"]
    score = pd.DataFrame(
        [[10.0, 4.0, 3.0, 2.0]] * len(idx),
        index=idx,
        columns=cols,
    )
    returns = pd.DataFrame(0.0, index=idx, columns=cols)
    liquidity = pd.DataFrame(1.0, index=idx, columns=cols)
    cap_mult = pd.DataFrame(1.0, index=idx, columns=cols)
    cap_mult["SPCX"] = 0.25
    cfg = nasdaq_lo_config(
        seats_base=3,
        seats_min=3,
        seats_max=3,
        seats_adaptive=False,
        max_pos=0.50,
        min_pos=0.0,
        softmax_tilt_alpha=1.0,
        weight_smooth_alpha=1.0,
        no_trade_band=0.0,
    )

    result = build_unit_weights(score, returns, liquidity, cfg, max_pos_mult=cap_mult)
    last_weight = float(result.unit_weights.iloc[-1]["SPCX"])

    assert last_weight <= cfg.max_pos * 0.25 + 1e-9
