"""Institutional performance metrics and deflated Sharpe diagnostics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANN = 252.0
EPS = 1e-12


def _annualized_return(returns: pd.Series) -> float:
    values = returns.dropna()
    if values.empty:
        return float("nan")
    growth = float((1.0 + values).prod())
    return growth ** (ANN / len(values)) - 1.0


def perf_summary(
    net_ret: pd.Series,
    benchmark: pd.Series | None = None,
) -> dict:
    """Return a compact institutional performance and market-exposure summary."""
    returns = net_ret.dropna()
    if len(returns) < 20:
        return {"error": "insufficient history"}

    mean = float(returns.mean())
    standard_deviation = float(returns.std())
    downside_deviation = float(returns[returns < 0].std())
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    annual_return = _annualized_return(returns)
    sharpe = mean / (standard_deviation + EPS) * math.sqrt(ANN)
    p05 = float(returns.quantile(0.05))
    p95 = float(returns.quantile(0.95))

    output = {
        "days": int(len(returns)),
        "ann_return": round(float(annual_return), 4),
        "ann_vol": round(standard_deviation * math.sqrt(ANN), 4),
        "sharpe": round(float(sharpe), 3),
        "sortino": round(
            mean / (downside_deviation + EPS) * math.sqrt(ANN),
            3,
        ),
        "max_dd": round(float(drawdown.min()), 4),
        "calmar": round(float(annual_return / (abs(drawdown.min()) + EPS)), 3),
        "win_rate": round(float((returns > 0).mean()), 4),
        "worst_day": round(float(returns.min()), 4),
        "best_day": round(float(returns.max()), 4),
        "skew": round(float(returns.skew()), 3),
        "kurtosis": round(float(returns.kurt()), 3),
        "tail_ratio_95_5": round(abs(p95) / (abs(p05) + EPS), 3),
    }

    if benchmark is not None:
        aligned = pd.concat(
            [returns.rename("portfolio"), benchmark.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        if len(aligned) >= 20:
            portfolio = aligned["portfolio"]
            market = aligned["benchmark"]
            market_variance = float(market.var())
            beta = float(portfolio.cov(market) / (market_variance + EPS))
            alpha_daily = float((portfolio - beta * market).mean())
            alpha_annual = alpha_daily * ANN
            correlation = float(portfolio.corr(market))
            active = portfolio - market
            active_volatility = float(active.std() * math.sqrt(ANN))

            up = market > 0
            down = market < 0
            upside_capture = (
                float(portfolio[up].mean() / (market[up].mean() + EPS))
                if up.any()
                else float("nan")
            )
            downside_capture = (
                float(portfolio[down].mean() / (market[down].mean() - EPS))
                if down.any()
                else float("nan")
            )

            output.update(
                {
                    "ann_active_return": round(_annualized_return(active), 4),
                    "active_vol": round(active_volatility, 4),
                    "info_ratio": round(
                        float(active.mean() / (active.std() + EPS) * math.sqrt(ANN)),
                        3,
                    ),
                    "benchmark_ann_return": round(_annualized_return(market), 4),
                    "beta": round(beta, 3),
                    "regression_alpha_ann": round(alpha_annual, 4),
                    "market_correlation": round(correlation, 3),
                    "upside_capture": round(upside_capture, 3),
                    "downside_capture": round(downside_capture, 3),
                    "capture_spread": round(upside_capture - downside_capture, 3),
                }
            )
    return output


def deflated_sharpe(net_ret: pd.Series, n_trials: int = 10) -> dict:
    """Bailey and López de Prado deflated-Sharpe approximation."""
    returns = net_ret.dropna()
    count = len(returns)
    if count < 60:
        return {"error": "insufficient history"}
    sharpe = float(returns.mean() / (returns.std() + EPS))
    skew = float(returns.skew())
    kurtosis = float(returns.kurt())
    euler_gamma = 0.5772156649
    variance_sharpe = 1.0 / count
    z1 = _norm_ppf(1 - 1.0 / n_trials)
    z2 = _norm_ppf(1 - 1.0 / (n_trials * math.e))
    expected_max = math.sqrt(variance_sharpe) * (
        (1 - euler_gamma) * z1 + euler_gamma * z2
    )
    denominator = math.sqrt(
        max(
            EPS,
            1 - skew * sharpe + (kurtosis + 2) / 4.0 * sharpe**2,
        )
    )
    probability = _norm_cdf(
        (sharpe - expected_max) * math.sqrt(count - 1) / denominator
    )
    return {
        "sharpe_ann": round(sharpe * math.sqrt(ANN), 3),
        "expected_max_unskilled_sharpe_ann": round(
            expected_max * math.sqrt(ANN), 3
        ),
        "deflated_sharpe_prob": round(float(probability), 4),
        "n_trials_assumed": n_trials,
        "verdict": (
            "PASS"
            if probability > 0.95
            else "INCONCLUSIVE"
            if probability > 0.5
            else "FAIL"
        ),
    }


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_ppf(probability: float) -> float:
    if not 0 < probability < 1:
        raise ValueError("probability must be in (0,1)")
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    lower, upper = 0.02425, 1 - 0.02425
    if probability < lower:
        value = math.sqrt(-2 * math.log(probability))
        return (
            (((((c[0] * value + c[1]) * value + c[2]) * value + c[3]) * value + c[4]) * value + c[5])
            / ((((d[0] * value + d[1]) * value + d[2]) * value + d[3]) * value + 1)
        )
    if probability > upper:
        value = math.sqrt(-2 * math.log(1 - probability))
        return -(
            (((((c[0] * value + c[1]) * value + c[2]) * value + c[3]) * value + c[4]) * value + c[5])
            / ((((d[0] * value + d[1]) * value + d[2]) * value + d[3]) * value + 1)
        )
    value = probability - 0.5
    square = value * value
    return (
        (((((a[0] * square + a[1]) * square + a[2]) * square + a[3]) * square + a[4]) * square + a[5])
        * value
        / (((((b[0] * square + b[1]) * square + b[2]) * square + b[3]) * square + b[4]) * square + 1)
    )
