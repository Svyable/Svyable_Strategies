"""Walk-forward validation + parameter fragility scan (strategy.md §8.5, §13).

The pipeline is causal end-to-end (purged IC shifts, trailing ML windows), so a
single run IS out-of-sample with respect to signal estimation; what a single
run does NOT cover is (a) period luck and (b) config choice. This module covers
both:

- per-period table: yearly slices of the same causal run, so a good aggregate
  can't hide one lucky year;
- sensitivity scan: perturb each key knob and re-run; a strategy whose Sharpe
  collapses under ±20% parameter wiggles is overfit regardless of its backtest.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from svyable.panel import Panel
from svyable.config import SvyableConfig
from svyable.metrics import perf_summary, deflated_sharpe
from svyable.pipeline import run_pipeline


def yearly_table(net_ret: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    rows = []
    for year, r in net_ret.groupby(net_ret.index.year):
        if len(r) < 40:
            continue
        b = benchmark.reindex(r.index).fillna(0.0)
        s = perf_summary(r, benchmark=b)
        rows.append({"year": year, "days": s["days"], "net": s["ann_return"],
                     "sharpe": s["sharpe"], "max_dd": s["max_dd"],
                     "active_vs_ew": s.get("ann_active_return")})
    return pd.DataFrame(rows).set_index("year")


PERTURBATIONS: dict[str, list] = {
    "ic_lambda": [0.92, 0.97],
    "sleeve_ic_lambda": [0.90, 0.97],
    "seats_base": [15, 25],
    "softmax_tilt_alpha": [0.40, 0.80],
    "weight_smooth_alpha": [0.25, 0.55],
    "no_trade_band": [0.02, 0.08],
    "target_vol": [0.14, 0.22],
    "dd_win": [63, 189],
}


def sensitivity_scan(panel: Panel, cfg: SvyableConfig,
                     perturbations: dict[str, list] | None = None) -> pd.DataFrame:
    """Re-run the pipeline once per perturbed knob (ML off for speed/isolation)."""
    perturbations = perturbations or PERTURBATIONS
    base_cfg = replace(cfg, ml_enabled=False)

    def _sharpe(c: SvyableConfig) -> tuple[float, float]:
        res = run_pipeline(panel, c, write_artifacts=False)
        s = perf_summary(res.pnl["net_ret"])
        return s["sharpe"], s["max_dd"]

    rows = [{"knob": "BASE", "value": "-", "sharpe": _sharpe(base_cfg)[0],
             "max_dd": _sharpe(base_cfg)[1]}]
    base_sharpe = rows[0]["sharpe"]

    for knob, values in perturbations.items():
        for v in values:
            sh, dd = _sharpe(replace(base_cfg, **{knob: v}))
            rows.append({"knob": knob, "value": v, "sharpe": sh, "max_dd": dd})

    df = pd.DataFrame(rows)
    df["d_sharpe"] = (df["sharpe"] - base_sharpe).round(3)
    return df


def fragility_verdict(scan: pd.DataFrame) -> dict:
    per = scan[scan["knob"] != "BASE"]
    base = float(scan.loc[scan["knob"] == "BASE", "sharpe"].iloc[0])
    worst = float(per["sharpe"].min())
    spread = float(per["sharpe"].max() - worst)
    frac_positive = float((per["sharpe"] > 0).mean())
    fragile = (base > 0 and worst < 0.25 * base) or spread > max(1.0, abs(base))
    return {
        "base_sharpe": round(base, 3),
        "worst_perturbed_sharpe": round(worst, 3),
        "sharpe_spread": round(spread, 3),
        "frac_perturbations_positive": round(frac_positive, 3),
        "verdict": "FRAGILE" if fragile else "ROBUST",
    }


def walkforward_report(panel: Panel, cfg: SvyableConfig, *,
                       n_trials: int = 20, run_sensitivity: bool = True) -> dict:
    res = run_pipeline(panel, cfg, write_artifacts=False)
    net = res.pnl["net_ret"]
    out: dict = {
        "aggregate": perf_summary(net, benchmark=panel.market_ret),
        "deflated_sharpe": deflated_sharpe(net, n_trials=n_trials),
        "by_year": yearly_table(net, panel.market_ret).to_dict(orient="index"),
        "config_hash": cfg.config_hash(),
    }
    years = out["by_year"]
    if years:
        sharpes = [v["sharpe"] for v in years.values()]
        out["consistency"] = {
            "profitable_years_frac": round(float(np.mean([v["net"] > 0 for v in years.values()])), 3),
            "worst_year_net": round(min(v["net"] for v in years.values()), 4),
            "sharpe_min": round(min(sharpes), 3),
            "sharpe_median": round(float(np.median(sharpes)), 3),
        }
    if run_sensitivity:
        scan = sensitivity_scan(panel, cfg)
        out["sensitivity"] = scan.to_dict(orient="records")
        out["fragility"] = fragility_verdict(scan)
    return out
