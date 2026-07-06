"""Data providers behind one protocol (plan.md §B.1). Every vendor is a class
with the same two methods emitting the same Panel + parquet cache format:

  YFinanceProvider  — EOD OHLCV, auto_adjust=True => ADJ_TOTAL_RETURN (deep,
                      free, dividend-adjusted). The backfill + validation oracle.
  TastytradeProvider — DXLink daily candles => ADJ_SPLIT_ONLY (same vendor auth
                      family as execution, but data-only and NOT dividend-adjusted;
                      live/tail feed).
  SyntheticProvider  — deterministic, offline.

Adjustment regime (Panel.meta["adjustment"]): the two real feeds are NOT
interchangeable — total-return and split-only closes diverge on every
dividend-paying name. That is a return bias, not noise, so a swap must clear
panel_parity() first. Yahoo stays as the deep adjusted reference; Tasty is
canonical for live/incremental once parity holds. Never concatenate the two
caches blind — detect_restatement() will (correctly) fire on the seam.

PIT caveat (documented, not hidden): the seed universe file is a *current*
liquid-NASDAQ list, so deep backtests carry survivorship bias. Fine for
engineering validation; before capital-grade backtests, replace with a
point-in-time universe per roadmap.md research agenda #1.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from svyable.panel import Panel

FIELDS = ["open", "high", "low", "close", "volume"]

# Price-adjustment regime declared in Panel.meta["adjustment"]. Backtests must
# never silently mix regimes: total-return series (dividend reinvested) and
# split-only series diverge on every dividend-paying name, and that divergence
# is a return bias, not noise. panel_parity() is the gate that proves two feeds
# agree before one is swapped for the other.
ADJ_TOTAL_RETURN = "total_return"  # split + dividend adjusted (yfinance auto_adjust)
ADJ_SPLIT_ONLY = "split_only"      # split adjusted, raw close (DXLink daily candles)
ADJ_SYNTHETIC = "synthetic"        # generated, not a market feed


class DataProvider(Protocol):
    def get_universe(self) -> list[str]: ...
    def get_panel(self, start: str, end: str | None = None) -> Panel: ...


class YFinanceProvider:
    """EOD OHLCV via yfinance (auto-adjusted), incremental parquet cache."""

    def __init__(self, cache_dir: str | Path, universe_file: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.universe_file = Path(universe_file)

    def get_universe(self) -> list[str]:
        syms = [ln.strip().upper() for ln in self.universe_file.read_text().splitlines()
                if ln.strip() and not ln.startswith("#")]
        return sorted(set(syms))

    # ---- cache -----------------------------------------------------------

    def _cache_path(self, field: str) -> Path:
        return self.cache_dir / f"{field}.parquet"

    def _load_cache(self) -> dict[str, pd.DataFrame] | None:
        if not all(self._cache_path(f).exists() for f in FIELDS):
            return None
        return {f: pd.read_parquet(self._cache_path(f)) for f in FIELDS}

    def _save_cache(self, frames: dict[str, pd.DataFrame]) -> None:
        for f in FIELDS:
            frames[f].to_parquet(self._cache_path(f))
        (self.cache_dir / "cache_meta.json").write_text(json.dumps({
            "updated": datetime.now().isoformat(),
            "last_date": str(frames["close"].index[-1].date()),
            "assets": int(frames["close"].shape[1]),
        }, indent=2))

    # ---- fetch -----------------------------------------------------------

    def _fetch(self, symbols: list[str], start: str, end: str | None) -> dict[str, pd.DataFrame]:
        import yfinance as yf
        raw = yf.download(symbols, start=start, end=end, interval="1d",
                          auto_adjust=True, group_by="column",
                          progress=False, threads=True)
        out: dict[str, pd.DataFrame] = {}
        colmap = {"open": "Open", "high": "High", "low": "Low",
                  "close": "Close", "volume": "Volume"}
        for field, yc in colmap.items():
            df = raw[yc] if isinstance(raw.columns, pd.MultiIndex) else raw[[yc]]
            if not isinstance(df, pd.DataFrame):
                df = df.to_frame()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            out[field] = df.sort_index()
        # align columns across fields
        cols = sorted(set.intersection(*(set(out[f].columns) for f in FIELDS)))
        for f in FIELDS:
            out[f] = out[f][cols]
        return out

    def refresh(self, start: str = "2018-01-01", tail_days: int = 30) -> dict:
        """Incremental update: full fetch if no cache, else re-fetch the tail
        (gap-fill principle: never restate deep history from the live call)."""
        symbols = self.get_universe()
        cached = self._load_cache()

        if cached is None or set(symbols) - set(cached["close"].columns):
            frames = self._fetch(symbols, start, None)
            self._save_cache(frames)
            return {"mode": "full", "last_date": str(frames["close"].index[-1].date())}

        tail_start = (cached["close"].index[-1] - timedelta(days=tail_days)).date()
        fresh = self._fetch(symbols, str(tail_start), None)

        restated = detect_restatement(cached["close"], fresh["close"])
        if restated:
            frames = self._fetch(symbols, start, None)
            self._save_cache(frames)
            return {"mode": "full_restatement", "restated": restated,
                    "last_date": str(frames["close"].index[-1].date())}

        frames = {}
        for f in FIELDS:
            old = cached[f].loc[cached[f].index < fresh[f].index[0]]
            frames[f] = pd.concat([old, fresh[f]]).sort_index()
            frames[f] = frames[f][~frames[f].index.duplicated(keep="last")]
        self._save_cache(frames)
        return {"mode": "incremental", "last_date": str(frames["close"].index[-1].date())}

    def get_panel(self, start: str = "2018-01-01", end: str | None = None) -> Panel:
        cached = self._load_cache()
        if cached is None:
            self.refresh(start=start)
            cached = self._load_cache()
        assert cached is not None
        s = slice(pd.Timestamp(start), pd.Timestamp(end) if end else None)
        frames = {f: cached[f].loc[s] for f in FIELDS}
        return Panel(**frames, meta={"provider": "yfinance",
                                     "adjustment": ADJ_TOTAL_RETURN,
                                     "universe_file": str(self.universe_file)})


def detect_restatement(old_close: pd.DataFrame, fresh_close: pd.DataFrame,
                       tol: float = 0.002) -> list[str]:
    """Symbols whose overlapping history changed by > tol — a split/dividend
    re-adjustment or vendor correction. Triggers a full refetch upstream so the
    cache never holds a corrupted seam."""
    common_idx = old_close.index.intersection(fresh_close.index)
    common_cols = old_close.columns.intersection(fresh_close.columns)
    if len(common_idx) < 2:
        return []
    a = old_close.loc[common_idx, common_cols]
    b = fresh_close.loc[common_idx, common_cols]
    rel = ((a - b).abs() / (a.abs() + 1e-9))
    bad = rel.max() > tol
    return sorted(common_cols[bad.fillna(False)])


def panel_parity(a: Panel, b: Panel, tol: float = 0.002) -> dict:
    """Reconcile two providers' close panels — the gate before one feed is
    swapped for another (roadmap: make Tasty canonical only when it agrees with
    the adjusted reference within tolerance).

    Compares close on the overlapping (date, symbol) rectangle. Because the
    inputs may be different adjustment regimes, a divergence here is *expected*
    on dividend-paying names and is exactly the signal a swap would change.

    Returns a structured report; ``status`` is one of ``ok`` (within tol),
    ``divergent`` (some symbol exceeds tol), or ``no_overlap``.
    """
    a_close, b_close = a.close, b.close
    common_cols = sorted(a_close.columns.intersection(b_close.columns))
    common_idx = a_close.index.intersection(b_close.index)
    report = {
        "n_common_symbols": len(common_cols),
        "n_common_dates": len(common_idx),
        "only_in_a": sorted(set(a_close.columns) - set(b_close.columns)),
        "only_in_b": sorted(set(b_close.columns) - set(a_close.columns)),
        "adjustment_a": a.meta.get("adjustment"),
        "adjustment_b": b.meta.get("adjustment"),
        "adjustment_mismatch": a.meta.get("adjustment") != b.meta.get("adjustment"),
        "tol": tol,
    }
    if len(common_idx) == 0 or len(common_cols) == 0:
        report.update(status="no_overlap", divergent_symbols=[], max_rel_diff=None)
        return report

    x = a_close.loc[common_idx, common_cols]
    y = b_close.loc[common_idx, common_cols]
    rel = (x - y).abs() / (x.abs() + 1e-9)
    per_symbol = rel.max().fillna(0.0)
    divergent = sorted(per_symbol[per_symbol > tol].index)
    report.update(
        status="divergent" if divergent else "ok",
        divergent_symbols=divergent,
        max_rel_diff=float(per_symbol.max()),
        median_rel_diff=float(per_symbol.median()),
    )
    return report


class TastytradeProvider:
    """Daily OHLCV via tastytrade's DXLink candle feed.

    This is a data provider only. It shares the same credential family as the
    Tastytrade SDK execution adapter, but it does not route, manage, cancel, or
    reconcile orders. Same parquet cache format as YFinanceProvider, separate
    cache dir.

    Auth: the tastytrade env vars (see svyable.tastytrade). Streaming quote
    tokens require a full tastytrade customer account.
    """

    def __init__(self, cache_dir: str | Path, universe_file: str | Path,
                 tt_client=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.universe_file = Path(universe_file)
        self._tt = tt_client            # lazily constructed so tests can inject
        self.events: list[str] = []     # restatement / fetch anomalies this session

    @property
    def tt(self):
        if self._tt is None:
            from svyable.tastytrade import TastytradeClient
            self._tt = TastytradeClient()
        return self._tt

    def get_universe(self) -> list[str]:
        syms = [ln.strip().upper() for ln in self.universe_file.read_text().splitlines()
                if ln.strip() and not ln.startswith("#")]
        return sorted(set(syms))

    def _fetch(self, symbols: list[str], start: str, end: str | None) -> dict[str, pd.DataFrame]:
        from svyable.dxlink import DXLinkCandles
        dxl = DXLinkCandles(self.tt, token_cache=self.cache_dir / "quote_token.json")
        frames_by_sym = dxl.fetch_daily(symbols, start)
        missing = sorted(set(symbols) - set(frames_by_sym))
        if missing:
            self.events.append(f"no candles for: {', '.join(missing[:10])}"
                               + ("..." if len(missing) > 10 else ""))
        per_field: dict[str, dict[str, pd.Series]] = {f: {} for f in FIELDS}
        for sym, bars in frames_by_sym.items():
            if end:
                bars = bars.loc[:pd.Timestamp(end)]
            for f in FIELDS:
                per_field[f][sym] = bars[f]
        return {f: pd.DataFrame(per_field[f]).sort_index() for f in FIELDS}

    # ---- cache lifecycle (mirrors YFinanceProvider) --------------------------

    def _cache_path(self, field: str) -> Path:
        return self.cache_dir / f"{field}.parquet"

    def _load_cache(self) -> dict[str, pd.DataFrame] | None:
        if not all(self._cache_path(f).exists() for f in FIELDS):
            return None
        return {f: pd.read_parquet(self._cache_path(f)) for f in FIELDS}

    def _save_cache(self, frames: dict[str, pd.DataFrame]) -> None:
        for f in FIELDS:
            frames[f].to_parquet(self._cache_path(f))
        (self.cache_dir / "cache_meta.json").write_text(json.dumps({
            "updated": datetime.now().isoformat(),
            "last_date": str(frames["close"].index[-1].date()),
            "assets": int(frames["close"].shape[1]),
            "events": self.events[-20:],
        }, indent=2))

    def refresh(self, start: str = "2018-01-01", tail_days: int = 30) -> dict:
        symbols = self.get_universe()
        cached = self._load_cache()

        if cached is None or set(symbols) - set(cached["close"].columns):
            frames = self._fetch(symbols, start, None)
            self._save_cache(frames)
            return {"mode": "full", "last_date": str(frames["close"].index[-1].date()),
                    "events": self.events}

        tail_start = (cached["close"].index[-1] - timedelta(days=tail_days)).date()
        fresh = self._fetch(symbols, str(tail_start), None)

        restated = detect_restatement(cached["close"], fresh["close"])
        if restated:
            self.events.append(f"restatement detected ({len(restated)}): "
                               f"{', '.join(restated[:8])} — full refetch")
            frames = self._fetch(symbols, start, None)
            self._save_cache(frames)
            return {"mode": "full_restatement", "restated": restated,
                    "last_date": str(frames["close"].index[-1].date()),
                    "events": self.events}

        frames = {}
        for f in FIELDS:
            old = cached[f].loc[cached[f].index < fresh[f].index[0]]
            frames[f] = pd.concat([old, fresh[f]]).sort_index()
            frames[f] = frames[f][~frames[f].index.duplicated(keep="last")]
        self._save_cache(frames)
        return {"mode": "incremental", "last_date": str(frames["close"].index[-1].date()),
                "events": self.events}

    def get_panel(self, start: str = "2018-01-01", end: str | None = None) -> Panel:
        cached = self._load_cache()
        if cached is None:
            self.refresh(start=start)
            cached = self._load_cache()
        assert cached is not None
        s = slice(pd.Timestamp(start), pd.Timestamp(end) if end else None)
        frames = {f: cached[f].loc[s] for f in FIELDS}
        return Panel(**frames, meta={"provider": "tastytrade",
                                     "adjustment": ADJ_SPLIT_ONLY,
                                     "universe_file": str(self.universe_file)})


class SyntheticProvider:
    """Deterministic random-walk panel for tests and offline development."""

    def __init__(self, n_assets: int = 60, n_days: int = 900, seed: int = 7):
        self.n_assets, self.n_days, self.seed = n_assets, n_days, seed

    def get_universe(self) -> list[str]:
        return [f"SYN{i:03d}" for i in range(self.n_assets)]

    def get_panel(self, start: str = "2018-01-01", end: str | None = None) -> Panel:
        rng = np.random.default_rng(self.seed)
        idx = pd.bdate_range(start, periods=self.n_days)
        cols = self.get_universe()
        mkt = rng.normal(0.0004, 0.011, size=(self.n_days, 1))
        beta = rng.uniform(0.6, 1.6, size=(1, self.n_assets))
        idio = rng.normal(0, 0.018, size=(self.n_days, self.n_assets))
        drift = rng.normal(0.0003, 0.0004, size=(1, self.n_assets))
        rets = drift + mkt @ beta + idio
        close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=cols)
        gap = np.exp(rng.normal(0, 0.004, close.shape))
        op = close.shift(1).fillna(close.iloc[0]) * gap
        hi = pd.DataFrame(np.maximum(op.values, close.values) * np.exp(np.abs(rng.normal(0, 0.005, close.shape))), index=idx, columns=cols)
        lo = pd.DataFrame(np.minimum(op.values, close.values) * np.exp(-np.abs(rng.normal(0, 0.005, close.shape))), index=idx, columns=cols)
        vol = pd.DataFrame(rng.lognormal(15.5, 0.6, close.shape), index=idx, columns=cols)
        return Panel(open=op, high=hi, low=lo, close=close, volume=vol,
                     meta={"provider": "synthetic", "adjustment": ADJ_SYNTHETIC})
