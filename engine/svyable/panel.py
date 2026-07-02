"""Canonical data panel: wide (time x asset) daily OHLCV frames.

Every provider adapter produces exactly this shape; everything downstream
consumes only this. All frames share the same DatetimeIndex and columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

EPS = 1e-12


@dataclass
class Panel:
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    meta: dict = field(default_factory=dict)

    # ---- derived (cached) ----
    _ret: Optional[pd.DataFrame] = None
    _liq: Optional[pd.DataFrame] = None

    def __post_init__(self) -> None:
        frames = [self.open, self.high, self.low, self.close, self.volume]
        idx, cols = self.close.index, self.close.columns
        for f in frames:
            if not f.index.equals(idx) or not f.columns.equals(cols):
                raise ValueError("Panel frames must share index and columns")
        if not idx.is_monotonic_increasing:
            raise ValueError("Panel index must be sorted ascending")

    # -- core derived fields ------------------------------------------------

    @property
    def ret(self) -> pd.DataFrame:
        if self._ret is None:
            self._ret = self.close.pct_change(fill_method=None)
        return self._ret

    @property
    def dollar_volume(self) -> pd.DataFrame:
        return self.close * self.volume

    def adv(self, win: int = 21) -> pd.DataFrame:
        return self.dollar_volume.rolling(win, min_periods=max(3, win // 2)).mean()

    def liquidity_mask(self, min_adv: float = 25e6, min_price: float = 5.0,
                       adv_win: int = 21) -> pd.DataFrame:
        """Computed tradability mask (1.0/0.0). Replaces any vendor is_liquid flag."""
        if self._liq is None:
            ok = (self.adv(adv_win) >= min_adv) & (self.close >= min_price)
            ok &= self.volume.notna() & (self.volume > 0)
            self._liq = ok.astype(float)
        return self._liq

    @property
    def market_ret(self) -> pd.Series:
        """Equal-weight universe return — the internal market proxy."""
        return self.ret.mean(axis=1).fillna(0.0)

    # -- validation ----------------------------------------------------------

    def validate(self, max_gap_days: int = 5) -> dict:
        """Data-quality report. Callers refuse to trade when status != 'ok'."""
        issues: list[str] = []
        idx = self.close.index
        if len(idx) < 300:
            issues.append(f"short history: {len(idx)} rows")
        gaps = pd.Series(idx).diff().dt.days.dropna()
        if len(gaps) and gaps.max() > max_gap_days:
            issues.append(f"calendar gap of {int(gaps.max())} days")
        nan_frac = float(self.close.isna().mean().mean())
        if nan_frac > 0.35:
            issues.append(f"close NaN fraction {nan_frac:.0%}")
        bad_rows = self.close.iloc[-1].isna().mean()
        if bad_rows > 0.25:
            issues.append(f"last row {bad_rows:.0%} NaN — stale feed?")
        neg = ((self.close <= 0) | (self.high < self.low)).sum().sum()
        if neg:
            issues.append(f"{int(neg)} impossible bars (close<=0 or high<low)")
        return {
            "status": "ok" if not issues else "degraded",
            "issues": issues,
            "rows": len(idx),
            "assets": self.close.shape[1],
            "last_date": str(idx[-1].date()) if len(idx) else None,
            "close_nan_frac": round(nan_frac, 4),
        }

    def slice(self, start: Optional[str] = None, end: Optional[str] = None) -> "Panel":
        s = slice(start, end)
        return Panel(
            open=self.open.loc[s], high=self.high.loc[s], low=self.low.loc[s],
            close=self.close.loc[s], volume=self.volume.loc[s], meta=dict(self.meta),
        )


# ---- shared cross-sectional helpers (used by every factor) ------------------

def cs_zscore(df: pd.DataFrame, clip: float = 5.0) -> pd.DataFrame:
    """Robust cross-sectional z-score: (x - median) / (1.4826 * MAD), clipped."""
    med = df.median(axis=1)
    mad = df.sub(med, axis=0).abs().median(axis=1)
    z = df.sub(med, axis=0).div(1.4826 * mad + EPS, axis=0)
    return z.clip(-clip, clip)


def rolling_beta(ret: pd.DataFrame, mkt: pd.Series, win: int) -> pd.DataFrame:
    """Rolling OLS beta of each column vs the market series."""
    cov = ret.rolling(win, min_periods=max(10, win // 2)).cov(mkt)
    var = mkt.rolling(win, min_periods=max(10, win // 2)).var()
    return cov.div(var + EPS, axis=0)


def residual_returns(ret: pd.DataFrame, mkt: pd.Series, beta_win: int) -> pd.DataFrame:
    """Beta-stripped returns using *lagged* beta (causal)."""
    beta = rolling_beta(ret, mkt, beta_win).shift(1)
    return ret.sub(beta.mul(mkt, axis=0), fill_value=np.nan)


def forward_returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Return from t to t+h, indexed at t. Only for IC estimation — never a factor."""
    return close.pct_change(horizon, fill_method=None).shift(-horizon)
