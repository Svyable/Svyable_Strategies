"""Flat factor registry (strategy.md §4, §8.3, §13).

Every factor is a pure function f(panel, cfg) -> DataFrame(time x asset),
cross-sectionally robust-z-scored, oriented so HIGHER = more attractive to own.
Registered with a sleeve tag; strategies are just (config, sleeve membership).

Causality rule: the value at row t may use data up to and including t, never after.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from svyable.panel import (
    EPS, Panel, cs_zscore, residual_returns, rolling_beta,
)
from svyable.config import SvyableConfig

FactorFn = Callable[[Panel, SvyableConfig], pd.DataFrame]

REGISTRY: dict[str, dict] = {}   # name -> {"fn": fn, "sleeve": sleeve}


def factor(name: str, sleeve: str):
    def deco(fn: FactorFn) -> FactorFn:
        REGISTRY[name] = {"fn": fn, "sleeve": sleeve}
        return fn
    return deco


def sleeve_members(sleeve: str) -> list[str]:
    return sorted(n for n, m in REGISTRY.items() if m["sleeve"] == sleeve)


def compute_all(panel: Panel, cfg: SvyableConfig,
                names: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Compute factors; z-score; NaN -> 0 (neutral) after scoring."""
    names = names or sorted(REGISTRY)
    out: dict[str, pd.DataFrame] = {}
    for n in names:
        raw = REGISTRY[n]["fn"](panel, cfg)
        out[n] = cs_zscore(raw).fillna(0.0)
    return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sma(df, w): return df.rolling(w, min_periods=max(2, w // 2)).mean()
def _std(df, w): return df.rolling(w, min_periods=max(2, w // 2)).std()
def _ema(df, span): return df.ewm(span=span, adjust=False, min_periods=span // 2).mean()


def _signed_volume(p: Panel) -> pd.DataFrame:
    sign = np.sign(p.close.diff())
    return sign * p.volume


def _ofi(p: Panel, win: int) -> pd.DataFrame:
    sv = _signed_volume(p)
    num = sv.rolling(win, min_periods=max(2, win // 2)).sum()
    den = p.volume.rolling(win, min_periods=max(2, win // 2)).sum()
    return (num / (den + EPS)).clip(-1, 1)


def _vpin(p: Panel, win: int) -> pd.DataFrame:
    sv = _signed_volume(p)
    buy = sv.clip(lower=0).rolling(win, min_periods=win // 2).sum()
    sell = (-sv.clip(upper=0)).rolling(win, min_periods=win // 2).sum()
    return (buy - sell).abs() / (buy + sell + EPS)


def _ou_params(p: Panel, win: int, cfg: SvyableConfig) -> dict[str, pd.DataFrame]:
    """Rolling AR(1) on log price -> OU (theta, mu, sigma, half_life, zscore)."""
    X = np.log(p.close.where(p.close > 0))
    Xl = X.shift(1)
    mp = max(5, win // 2)
    mX, mXl = X.rolling(win, min_periods=mp).mean(), Xl.rolling(win, min_periods=mp).mean()
    var = Xl.rolling(win, min_periods=mp).var()
    cov = (X * Xl).rolling(win, min_periods=mp).mean() - mX * mXl
    b = (cov / (var + EPS)).clip(-0.9999, 0.9999)
    a = mX - b * mXl
    theta = (-np.log(b.abs() + EPS)).clip(lower=EPS)
    mu = a / (1 - b + EPS)
    resid = X - (a + b * Xl)
    sigma = resid.rolling(win, min_periods=mp).std()
    hl = (np.log(2) / theta).clip(cfg.ou_halflife_min, cfg.ou_halflife_max)
    z = ((X - mu) / (sigma + EPS)).clip(-3, 3)
    return {"theta": theta, "mu": mu, "sigma": sigma, "half_life": hl, "zscore": z, "logp": X}


# ---------------------------------------------------------------------------
# DEFENSIVE sleeve
# ---------------------------------------------------------------------------

@factor("inv_vol", "defensive")
def inv_vol(p, cfg):
    return 1.0 / (_std(p.ret, cfg.idio_win) + EPS)


@factor("inv_downside", "defensive")
def inv_downside(p, cfg):
    d = p.ret.clip(upper=0.0)
    semi = np.sqrt((d ** 2).rolling(cfg.down_win, min_periods=cfg.down_win // 2).mean())
    return 1.0 / (semi + EPS)


@factor("low_beta", "defensive")
def low_beta(p, cfg):
    return -rolling_beta(p.ret, p.market_ret, cfg.beta_win)


@factor("beta_stability", "defensive")
def beta_stability(p, cfg):
    beta = rolling_beta(p.ret, p.market_ret, cfg.idio_win)
    return -_std(beta, cfg.idio_win)


@factor("amihud_inv", "defensive")
def amihud_inv(p, cfg):
    illiq = p.ret.abs() / (p.dollar_volume + EPS)
    return -_sma(illiq, cfg.impact_win)


@factor("vol_of_vol_inv", "defensive")
def vol_of_vol_inv(p, cfg):
    vol = _std(p.ret, cfg.vov_win)
    return -_std(vol, cfg.idio_win)


@factor("skew_pref", "defensive")
def skew_pref(p, cfg):
    return p.ret.rolling(cfg.skew_win, min_periods=21).skew()


@factor("kurtosis_inv", "defensive")
def kurtosis_inv(p, cfg):
    return -p.ret.rolling(cfg.kurt_win, min_periods=21).kurt().clip(-10, 20)


# ---------------------------------------------------------------------------
# MOMENTUM sleeve
# ---------------------------------------------------------------------------

@factor("mom_12_1", "momentum")
def mom_12_1(p, cfg):
    """Classic 12-1: past year skipping the most recent month."""
    return p.close.pct_change(252, fill_method=None).shift(21)


@factor("resid_mom", "momentum")
def resid_mom(p, cfg):
    return _sma(residual_returns(p.ret, p.market_ret, cfg.beta_win), cfg.mom_win)


@factor("resid_mom_short", "momentum")
def resid_mom_short(p, cfg):
    return _sma(residual_returns(p.ret, p.market_ret, cfg.beta_win), cfg.mom_short)


@factor("trend_consistency", "momentum")
def trend_consistency(p, cfg):
    return (p.ret > 0).rolling(cfg.mom_win, min_periods=cfg.mom_win // 2).mean()


@factor("prox_52w_high", "momentum")
def prox_52w_high(p, cfg):
    hi = p.high.rolling(252, min_periods=126).max()
    return p.close / (hi + EPS)


@factor("slope_ema", "momentum")
def slope_ema(p, cfg):
    return (_ema(p.close, cfg.ema_fast) - _ema(p.close, cfg.ema_slow)) / (p.close + EPS)


@factor("breakout", "momentum")
def breakout(p, cfg):
    hi = p.high.rolling(63, min_periods=42).max().shift(1)
    return (p.close - hi) / (p.close.rolling(63, min_periods=42).std() * np.sqrt(63) + EPS)


@factor("mom_accel", "momentum")
def mom_accel(p, cfg):
    m1 = p.close.pct_change(cfg.mom_short, fill_method=None)
    m2 = p.close.pct_change(cfg.mom_win, fill_method=None) - m1
    return m1 - m2 / max(1, (cfg.mom_win - cfg.mom_short) / cfg.mom_short)


@factor("momentum_quality", "momentum")
def momentum_quality(p, cfg):
    """Sharpe of the asset's own returns (Israel et al. quality momentum)."""
    return (_sma(p.ret, cfg.mom_win) / (_std(p.ret, cfg.mom_win) + EPS)).clip(-5, 5)


@factor("momentum_persistence", "momentum")
def momentum_persistence(p, cfg):
    r, rl = p.ret, p.ret.shift(1)
    w, mp = cfg.persistence_win, cfg.persistence_win // 2
    mr, ml = r.rolling(w, min_periods=mp).mean(), rl.rolling(w, min_periods=mp).mean()
    cov = (r * rl).rolling(w, min_periods=mp).mean() - mr * ml
    return (cov / (_std(r, w) * _std(rl, w) + EPS)).clip(-1, 1)


@factor("overnight_bias", "momentum")
def overnight_bias(p, cfg):
    """SOTA §13: overnight (close->open) return momentum — Lou/Polk/Skouras 'tug of war'."""
    overnight = p.open / (p.close.shift(1) + EPS) - 1.0
    return _sma(overnight, cfg.mom_short)


# ---------------------------------------------------------------------------
# MEAN-REVERSION sleeve
# ---------------------------------------------------------------------------

@factor("srev", "meanrev")
def srev(p, cfg):
    return -p.close.pct_change(cfg.rev_win, fill_method=None)


@factor("ou_zscore", "meanrev")
def ou_zscore(p, cfg):
    return -_ou_params(p, cfg.ou_med_win, cfg)["zscore"]


@factor("ou_predicted_return", "meanrev")
def ou_predicted_return(p, cfg):
    o = _ou_params(p, cfg.ou_med_win, cfg)
    return o["theta"] * (o["mu"] - o["logp"])


@factor("ou_mom_blend", "meanrev")
def ou_mom_blend(p, cfg):
    """Half-life-adaptive momentum/reversal blend — the ou_v1 standout."""
    o = _ou_params(p, cfg.ou_med_win, cfg)
    w = ((o["half_life"] - cfg.ou_halflife_min)
         / (cfg.ou_halflife_max - cfg.ou_halflife_min)).clip(0, 1)
    mom = cs_zscore(p.ret.rolling(cfg.mom_short, min_periods=10).sum())
    rev = cs_zscore(-p.ret.rolling(cfg.rev_win, min_periods=3).sum())
    return w * mom + (1 - w) * rev


@factor("mean_reversion_speed", "meanrev")
def mean_reversion_speed(p, cfg):
    trend = _ema(p.close, cfg.ema_slow)
    dev = (p.close - trend) / (trend + EPS)
    dl = dev.shift(1)
    w, mp = 63, 21
    md, ml = dev.rolling(w, min_periods=mp).mean(), dl.rolling(w, min_periods=mp).mean()
    cov = (dev * dl).rolling(w, min_periods=mp).mean() - md * ml
    ac = cov / (_std(dev, w) * _std(dl, w) + EPS)
    return (-ac).clip(-1, 1)


# ---------------------------------------------------------------------------
# MICROSTRUCTURE sleeve (daily-bar proxies for order-flow quantities)
# ---------------------------------------------------------------------------

@factor("ofi_med", "micro")
def ofi_med(p, cfg):
    return _ofi(p, cfg.ofi_med_win)


@factor("mtf_ofi_alignment", "micro")
def mtf_ofi_alignment(p, cfg):
    s, m, l = _ofi(p, cfg.ofi_short_win), _ofi(p, cfg.ofi_med_win), _ofi(p, cfg.ofi_long_win)
    align = np.sign(s) + np.sign(m) + np.sign(l)
    mag = (s.abs() + m.abs() + l.abs()) / 3.0
    return align * mag


@factor("vpin_inv", "micro")
def vpin_inv(p, cfg):
    return -_vpin(p, cfg.vpin_win)


@factor("kyle_lambda_inv", "micro")
def kyle_lambda_inv(p, cfg):
    r, sv = p.ret, _signed_volume(p)
    w, mp = cfg.impact_win, cfg.impact_win // 2
    mr, ms = r.rolling(w, min_periods=mp).mean(), sv.rolling(w, min_periods=mp).mean()
    cov = (r * sv).rolling(w, min_periods=mp).mean() - mr * ms
    var = sv.rolling(w, min_periods=mp).var()
    return -(cov / (var + EPS))


@factor("bvc_imbalance", "micro")
def bvc_imbalance(p, cfg):
    bvc = (p.close - p.low) / (p.high - p.low + EPS)
    buy, sell = bvc * p.volume, (1 - bvc) * p.volume
    w = 10
    b = buy.rolling(w, min_periods=5).sum()
    s = sell.rolling(w, min_periods=5).sum()
    return (b - s) / (b + s + EPS)


@factor("exec_quality", "micro")
def exec_quality(p, cfg):
    spread = np.log(p.high / (p.low + EPS) + EPS)
    impact = p.ret.abs() / (p.dollar_volume + EPS)
    vol_rel = p.dollar_volume / (_sma(p.dollar_volume, 63) + EPS)
    return (cs_zscore(-_sma(spread, cfg.efficiency_win))
            + cs_zscore(-_sma(impact, cfg.efficiency_win))
            + cs_zscore(vol_rel)
            + cs_zscore(-_vpin(p, cfg.vpin_win))) / 4.0


@factor("flow_persistence", "micro")
def flow_persistence(p, cfg):
    ofi = _ofi(p, cfg.ofi_short_win)
    ol = ofi.shift(1)
    w, mp = 10, 5
    mo, ml = ofi.rolling(w, min_periods=mp).mean(), ol.rolling(w, min_periods=mp).mean()
    cov = (ofi * ol).rolling(w, min_periods=mp).mean() - mo * ml
    ac = cov / (_std(ofi, w) * _std(ol, w) + EPS)
    return ac.clip(-1, 1) * ofi


# ---------------------------------------------------------------------------
# BEHAVIORAL / signal-quality (feeds momentum + defensive sleeves)
# ---------------------------------------------------------------------------

@factor("attention_momentum", "momentum")
def attention_momentum(p, cfg):
    vol_ratio = (p.volume / (_sma(p.volume, 63) + EPS)).clip(0.1, 10.0)
    rz = (p.ret / (_std(p.ret, cfg.mom_short) + EPS)).clip(-3, 3)
    return _sma(np.sign(p.ret) * (vol_ratio - 1.0) * rz.abs(), cfg.attention_win)


@factor("disposition_alpha", "meanrev")
def disposition_alpha(p, cfg):
    hi = p.high.rolling(252, min_periods=126).max()
    lo = p.low.rolling(252, min_periods=126).min()
    anchor = (hi + lo) / 2.0
    paper_pnl = (p.close - anchor) / (anchor + EPS)
    recovering = (_sma(p.ret, cfg.mom_short) > 0).astype(float)
    return _sma(-paper_pnl * (0.5 + 0.5 * recovering), cfg.disposition_win)


@factor("anchoring_bias", "momentum")
def anchoring_bias(p, cfg):
    hi = p.high.rolling(252, min_periods=126).max()
    lo = p.low.rolling(252, min_periods=126).min()
    return 0.6 * (p.close / (hi + EPS)) + 0.4 * ((p.close - lo) / (hi - lo + EPS))


@factor("efficiency_ratio", "momentum")
def efficiency_ratio(p, cfg):
    w = cfg.efficiency_win
    direction = (p.close - p.close.shift(w)).abs()
    path = p.close.diff().abs().rolling(w, min_periods=w).sum()
    er = direction / (path + EPS)
    return (er * np.sign(p.close - p.close.shift(w))).clip(-1, 1)


@factor("cross_sectional_dispersion", "defensive")
def cross_sectional_dispersion(p, cfg):
    cs_std = p.ret.std(axis=1)
    rel = p.ret.sub(p.ret.mean(axis=1), axis=0)
    disp_norm = _sma(cs_std.to_frame("d"), cfg.mom_short)["d"]
    disp_norm = disp_norm / (disp_norm.expanding(min_periods=63).mean() + EPS)
    return _sma(rel.mul(disp_norm, axis=0), cfg.mom_short)


# ---------------------------------------------------------------------------
# RESEARCH-BACKED ADDITIONS (strategy.md §13 lineage)
# ---------------------------------------------------------------------------

@factor("max_lottery", "defensive")
def max_lottery(p, cfg):
    """MAX effect (Bali, Cakici & Whitelaw 2011): lottery-like stocks — those
    with extreme recent best days — underperform. Short the lottery demand."""
    best = p.ret.rolling(21, min_periods=15).max()
    return -best


@factor("resid_srev", "meanrev")
def resid_srev(p, cfg):
    """Residual short-term reversal (Blitz et al. 2011): reversal on
    beta-stripped returns is stronger and cheaper than raw reversal."""
    resid = residual_returns(p.ret, p.market_ret, cfg.beta_win)
    return -resid.rolling(cfg.rev_win, min_periods=3).sum()


@factor("turnover_vol_inv", "defensive")
def turnover_vol_inv(p, cfg):
    """Chordia, Subrahmanyam & Anshuman (2001): volatility of share turnover
    is negatively priced — unstable trading interest is a risk."""
    turn = p.volume / (_sma(p.volume, 126) + EPS)
    return -_std(turn, cfg.impact_win)


@factor("obv_trend", "micro")
def obv_trend(p, cfg):
    """On-balance-volume trend: EMA slope of cumulative signed volume,
    normalized by average volume — accumulation/distribution pressure."""
    obv = _signed_volume(p).fillna(0.0).cumsum()
    slope = _ema(obv, cfg.ema_fast) - _ema(obv, cfg.ema_slow)
    return slope / (_sma(p.volume, 63) * cfg.ema_slow + EPS)


@factor("capm_alpha", "momentum")
def capm_alpha(p, cfg):
    """Jensen-alpha momentum: rolling CAPM intercept — return not explained
    by beta. A cleaner past-winner signal than raw momentum."""
    mkt = p.market_ret
    w, mp = cfg.mom_win, cfg.mom_win // 2
    beta = rolling_beta(p.ret, mkt, w)
    a = _sma(p.ret, w) - beta.mul(mkt.rolling(w, min_periods=mp).mean(), axis=0)
    return a
