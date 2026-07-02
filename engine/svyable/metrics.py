"""Performance metrics incl. deflated Sharpe (strategy.md §13)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANN = 252.0


def perf_summary(net_ret: pd.Series, benchmark: pd.Series | None = None) -> dict:
    r = net_ret.dropna()
    if len(r) < 20:
        return {"error": "insufficient history"}
    mean, std = r.mean(), r.std()
    downside = r[r < 0].std()
    eq = (1 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0)
    ann_ret = (1 + mean) ** ANN - 1
    sharpe = float(mean / (std + 1e-12) * math.sqrt(ANN))
    out = {
        "days": int(len(r)),
        "ann_return": round(float(ann_ret), 4),
        "ann_vol": round(float(std * math.sqrt(ANN)), 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(float(mean / (downside + 1e-12) * math.sqrt(ANN)), 3),
        "max_dd": round(float(dd.min()), 4),
        "calmar": round(float(ann_ret / (abs(dd.min()) + 1e-12)), 3),
        "win_rate": round(float((r > 0).mean()), 4),
        "worst_day": round(float(r.min()), 4),
        "skew": round(float(r.skew()), 3),
        "kurtosis": round(float(r.kurt()), 3),
    }
    if benchmark is not None:
        b = benchmark.reindex(r.index).fillna(0.0)
        active = r - b
        out["ann_active_return"] = round(float((1 + active.mean()) ** ANN - 1), 4)
        out["info_ratio"] = round(float(active.mean() / (active.std() + 1e-12) * math.sqrt(ANN)), 3)
        out["benchmark_ann_return"] = round(float((1 + b.mean()) ** ANN - 1), 4)
    return out


def deflated_sharpe(net_ret: pd.Series, n_trials: int = 10) -> dict:
    """Bailey & López de Prado (2014). Probability the observed Sharpe beats the
    expected-max Sharpe of `n_trials` unskilled configurations."""
    r = net_ret.dropna()
    n = len(r)
    if n < 60:
        return {"error": "insufficient history"}
    sr = float(r.mean() / (r.std() + 1e-12))          # per-period Sharpe
    g3, g4 = float(r.skew()), float(r.kurt())         # kurt is excess
    # expected max SR of n_trials iid trials (Euler-Mascheroni approximation)
    e = 0.5772156649
    var_sr = 1.0 / n
    z1 = _norm_ppf(1 - 1.0 / n_trials)
    z2 = _norm_ppf(1 - 1.0 / (n_trials * math.e))
    sr0 = math.sqrt(var_sr) * ((1 - e) * z1 + e * z2)
    denom = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 + 2) / 4.0 * sr ** 2))
    psr = _norm_cdf((sr - sr0) * math.sqrt(n - 1) / denom)
    return {
        "sharpe_ann": round(sr * math.sqrt(ANN), 3),
        "expected_max_unskilled_sharpe_ann": round(sr0 * math.sqrt(ANN), 3),
        "deflated_sharpe_prob": round(float(psr), 4),
        "n_trials_assumed": n_trials,
        "verdict": "PASS" if psr > 0.95 else "INCONCLUSIVE" if psr > 0.5 else "FAIL",
    }


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(q: float) -> float:
    """Acklam-style inverse normal CDF (sufficient precision for DSR)."""
    if not 0 < q < 1:
        raise ValueError("q in (0,1)")
    # coefficients
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if q < plow:
        u = math.sqrt(-2 * math.log(q))
        return (((((c[0]*u+c[1])*u+c[2])*u+c[3])*u+c[4])*u+c[5]) / \
               ((((d[0]*u+d[1])*u+d[2])*u+d[3])*u+1)
    if q > phigh:
        u = math.sqrt(-2 * math.log(1 - q))
        return -(((((c[0]*u+c[1])*u+c[2])*u+c[3])*u+c[4])*u+c[5]) / \
               ((((d[0]*u+d[1])*u+d[2])*u+d[3])*u+1)
    u = q - 0.5
    v = u * u
    return (((((a[0]*v+a[1])*v+a[2])*v+a[3])*v+a[4])*v+a[5])*u / \
           (((((b[0]*v+b[1])*v+b[2])*v+b[3])*v+b[4])*v+1)
