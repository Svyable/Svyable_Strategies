"""Provider contract + golden-parity tests (offline).

These are the gate that must pass before TastytradeProvider can be declared
canonical: the two real providers must expose explicit *adjustment* semantics,
and their price panels must reconcile within tolerance on overlapping history.
`panel_parity` is the reusable oracle used both here and as a CLI diagnostic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.panel import Panel
from svyable.providers import (
    ADJ_SPLIT_ONLY,
    ADJ_SYNTHETIC,
    ADJ_TOTAL_RETURN,
    SyntheticProvider,
    TastytradeProvider,
    YFinanceProvider,
    panel_parity,
)


def _panel(close: pd.DataFrame, *, adjustment: str, provider: str) -> Panel:
    return Panel(
        open=close, high=close, low=close, close=close,
        volume=close * 0 + 1e6,
        meta={"provider": provider, "adjustment": adjustment},
    )


def _synthetic_close(seed: int = 0, shift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=120)
    cols = [f"S{i}" for i in range(8)]
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (120, 8)), axis=0))
    return pd.DataFrame(base * (1.0 + shift), index=idx, columns=cols)


# ---- adjustment metadata contract ------------------------------------------


def test_providers_declare_adjustment_constants():
    """The three adjustment regimes are distinct, explicit strings."""
    assert ADJ_TOTAL_RETURN != ADJ_SPLIT_ONLY != ADJ_SYNTHETIC
    assert len({ADJ_TOTAL_RETURN, ADJ_SPLIT_ONLY, ADJ_SYNTHETIC}) == 3


def test_synthetic_panel_declares_adjustment():
    panel = SyntheticProvider(n_assets=5, n_days=320).get_panel()
    assert panel.meta["provider"] == "synthetic"
    assert panel.meta["adjustment"] == ADJ_SYNTHETIC


def test_yfinance_panel_meta_declares_total_return(tmp_path):
    """YFinance uses auto_adjust=True -> dividend+split adjusted (total return)."""
    prov = YFinanceProvider(cache_dir=tmp_path, universe_file=tmp_path / "u.txt")
    close = _synthetic_close()
    frames = {f: close for f in ["open", "high", "low", "close", "volume"]}
    prov._save_cache(frames)
    panel = prov.get_panel(start="2022-01-03")
    assert panel.meta["provider"] == "yfinance"
    assert panel.meta["adjustment"] == ADJ_TOTAL_RETURN


def test_tastytrade_panel_meta_declares_split_only(tmp_path):
    """DXLink daily candles are split-adjusted but NOT dividend-adjusted."""
    (tmp_path / "u.txt").write_text("AAPL\n")
    prov = TastytradeProvider(cache_dir=tmp_path, universe_file=tmp_path / "u.txt")
    close = _synthetic_close()
    frames = {f: close for f in ["open", "high", "low", "close", "volume"]}
    prov._save_cache(frames)
    panel = prov.get_panel(start="2022-01-03")
    assert panel.meta["provider"] == "tastytrade"
    assert panel.meta["adjustment"] == ADJ_SPLIT_ONLY


# ---- panel_parity oracle ----------------------------------------------------


def test_parity_identical_panels_clean():
    close = _synthetic_close()
    a = _panel(close, adjustment=ADJ_TOTAL_RETURN, provider="yfinance")
    b = _panel(close, adjustment=ADJ_SPLIT_ONLY, provider="tastytrade")
    rep = panel_parity(a, b, tol=0.002)
    assert rep["status"] == "ok"
    assert rep["divergent_symbols"] == []
    assert rep["n_common_symbols"] == 8
    assert rep["adjustment_mismatch"] is True  # metadata mismatch is surfaced


def test_parity_flags_divergent_symbol():
    close_a = _synthetic_close()
    close_b = close_a.copy()
    close_b["S3"] = close_b["S3"] * 1.05  # 5% drift on one name (e.g. dividend gap)
    a = _panel(close_a, adjustment=ADJ_TOTAL_RETURN, provider="yfinance")
    b = _panel(close_b, adjustment=ADJ_SPLIT_ONLY, provider="tastytrade")
    rep = panel_parity(a, b, tol=0.002)
    assert rep["status"] == "divergent"
    assert "S3" in rep["divergent_symbols"]
    assert rep["max_rel_diff"] > 0.002


def test_parity_reports_disjoint_history():
    a = _panel(_synthetic_close(), adjustment=ADJ_TOTAL_RETURN, provider="yfinance")
    other = _synthetic_close()
    other.index = other.index + pd.Timedelta(days=400)  # no calendar overlap
    b = _panel(other, adjustment=ADJ_SPLIT_ONLY, provider="tastytrade")
    rep = panel_parity(a, b, tol=0.002)
    assert rep["status"] == "no_overlap"
    assert rep["n_common_dates"] == 0


def test_parity_respects_symbol_intersection():
    close_a = _synthetic_close()
    close_b = _synthetic_close()[["S0", "S1", "S2"]]  # tasty covers fewer names
    a = _panel(close_a, adjustment=ADJ_TOTAL_RETURN, provider="yfinance")
    b = _panel(close_b, adjustment=ADJ_SPLIT_ONLY, provider="tastytrade")
    rep = panel_parity(a, b, tol=0.002)
    assert rep["n_common_symbols"] == 3
    assert set(rep["only_in_a"]) == {"S3", "S4", "S5", "S6", "S7"}
    assert rep["only_in_b"] == []
