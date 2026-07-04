"""Portfolio Arcana: idiosyncratic alpha and factor exposure lens.

The module is intentionally data-source agnostic. It can score the current
Svyable book from artifacts, or any user supplied stock-weight vector when a
canonical Panel and factor cache are available.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from svyable.config import SvyableConfig
from svyable.factor_library import compute_all
from svyable.panel import EPS, Panel, residual_returns

ANN = 252.0


@dataclass(frozen=True)
class ArcanaSnapshot:
    summary: dict[str, float | str | int | None]
    factor_exposures: pd.DataFrame
    idio_contributors: pd.DataFrame
    residual_series: pd.Series


def _clean_returns(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    out.index = pd.to_datetime(out.index, errors="coerce")
    return out[~out.index.isna()].sort_index()


def _normalize_weights(weights: pd.Series) -> pd.Series:
    clean = pd.to_numeric(weights, errors="coerce").dropna()
    clean.index = clean.index.astype(str).str.upper()
    gross = float(clean.abs().sum())
    if gross <= 0:
        return clean.astype(float)
    return (clean / gross).astype(float)


def market_model(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> tuple[dict, pd.Series]:
    """Estimate beta, annualized residual alpha, idio vol, R2, and idio share."""
    portfolio = _clean_returns(portfolio_returns).rename("portfolio")
    benchmark = _clean_returns(benchmark_returns).rename("benchmark")
    frame = pd.concat([portfolio, benchmark], axis=1).dropna()
    if len(frame) < 20:
        return {"status": "insufficient_history", "days": len(frame)}, pd.Series(dtype=float)

    beta = float(frame["portfolio"].cov(frame["benchmark"]) / (frame["benchmark"].var() + EPS))
    residual = frame["portfolio"] - beta * frame["benchmark"]
    ann_alpha = float(residual.mean() * ANN)
    ann_idio_vol = float(residual.std() * np.sqrt(ANN))
    ann_total_vol = float(frame["portfolio"].std() * np.sqrt(ANN))
    r2 = float(1.0 - residual.var() / (frame["portfolio"].var() + EPS))
    idio_share = float(1.0 - max(min(r2, 1.0), 0.0))
    info = ann_alpha / (ann_idio_vol + EPS)
    hit_rate = float((residual > 0).mean())
    summary = {
        "status": "ok",
        "days": len(frame),
        "beta": beta,
        "ann_residual_alpha": ann_alpha,
        "ann_idio_vol": ann_idio_vol,
        "ann_total_vol": ann_total_vol,
        "idio_information_ratio": float(info),
        "r2_market": r2,
        "idio_share": idio_share,
        "residual_hit_rate": hit_rate,
    }
    return summary, residual.rename("residual_return")


def current_factor_exposures(
    weights: pd.Series,
    factors: dict[str, pd.DataFrame],
    *,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Weighted latest cross-sectional exposure to each factor score."""
    w = _normalize_weights(weights)
    if w.empty:
        return pd.DataFrame(columns=["factor", "exposure", "long_exposure", "short_exposure", "coverage"])
    rows: list[dict] = []
    for name, frame in factors.items():
        if frame.empty:
            continue
        scores = frame.loc[:as_of].iloc[-1] if as_of is not None else frame.iloc[-1]
        scores.index = scores.index.astype(str).str.upper()
        aligned = pd.concat([w.rename("weight"), scores.rename("score")], axis=1).dropna()
        if aligned.empty:
            continue
        long = aligned[aligned["weight"] > 0]
        short = aligned[aligned["weight"] < 0]
        rows.append({
            "factor": name,
            "exposure": float((aligned["weight"] * aligned["score"]).sum()),
            "long_exposure": float((long["weight"] * long["score"]).sum()) if not long.empty else 0.0,
            "short_exposure": float((short["weight"] * short["score"]).sum()) if not short.empty else 0.0,
            "coverage": float(aligned["weight"].abs().sum()),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("exposure", ascending=False).reset_index(drop=True)


def idiosyncratic_contributors(
    weights: pd.Series,
    panel: Panel,
    cfg: SvyableConfig,
    *,
    window: int = 63,
) -> pd.DataFrame:
    """Trailing annualized residual-return contribution by symbol."""
    w = _normalize_weights(weights)
    residual = residual_returns(panel.ret, panel.market_ret, cfg.beta_win)
    trailing_mean = residual.tail(window).mean() * ANN
    trailing_vol = residual.tail(window).std() * np.sqrt(ANN)
    frame = pd.concat([
        w.rename("weight"),
        trailing_mean.rename("ann_residual_return"),
        trailing_vol.rename("ann_residual_vol"),
    ], axis=1).dropna()
    if frame.empty:
        return frame
    frame["ann_residual_contribution"] = frame["weight"] * frame["ann_residual_return"]
    frame["idio_ir"] = frame["ann_residual_return"] / (frame["ann_residual_vol"] + EPS)
    return frame.sort_values("ann_residual_contribution", ascending=False)


def arcana_from_panel(
    weights: pd.Series,
    panel: Panel,
    cfg: SvyableConfig,
    *,
    factor_names: list[str] | None = None,
    precomputed_factors: dict[str, pd.DataFrame] | None = None,
) -> ArcanaSnapshot:
    """Build a full Arcana snapshot for any stock portfolio weights."""
    w = _normalize_weights(weights)
    returns = panel.ret.mul(w, axis=1).sum(axis=1).rename("portfolio")
    summary, residual = market_model(returns, panel.market_ret)
    factors = precomputed_factors or compute_all(panel, cfg, names=factor_names)
    exposures = current_factor_exposures(w, factors)
    contributors = idiosyncratic_contributors(w, panel, cfg)
    summary = dict(summary) | {
        "gross_exposure": float(weights.abs().sum()) if len(weights) else 0.0,
        "net_exposure": float(weights.sum()) if len(weights) else 0.0,
        "symbols": int(len(w)),
        "factor_count": int(len(exposures)),
    }
    return ArcanaSnapshot(summary, exposures, contributors, residual)
