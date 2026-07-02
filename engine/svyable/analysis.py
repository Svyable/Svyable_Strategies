"""Factor research harness — the IC microscope.

Per factor: IC mean / vol / IR / hit-rate at multiple horizons, IC decay,
top-minus-bottom quintile spread, and rank stability (Spearman autocorrelation
of the cross-sectional ranks — a turnover/cost proxy).

This is the promotion gate (strategy.md §8.10): a factor earns sleeve
membership by looking good HERE first, on out-of-sample data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.panel import Panel, forward_returns
from svyable.config import SvyableConfig
from svyable import factors as flib
from svyable.weighting import rank_ic

ANN = 252.0


def nw_tstat(series: pd.Series, lag: int) -> float:
    """Newey-West t-stat for the mean of an autocorrelated series.

    IC computed against h-day forward returns overlaps h consecutive days, so
    consecutive ICs share information; the naive t-stat overstates significance
    by roughly sqrt(h). NW with lag=h corrects the variance with Bartlett
    weights: var = (g0 + 2*sum_{l=1..L}(1 - l/(L+1)) * g_l) / n.
    """
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < lag + 10:
        return float("nan")
    xd = x - x.mean()
    g0 = float(xd @ xd) / n
    var = g0
    for l in range(1, lag + 1):
        gl = float(xd[l:] @ xd[:-l]) / n
        var += 2.0 * (1.0 - l / (lag + 1.0)) * gl
    var = max(var, 1e-18)
    return float(x.mean() / np.sqrt(var / n))


def factor_report(panel: Panel, cfg: SvyableConfig,
                  horizons: tuple[int, ...] = (1, 5, 21, 63),
                  names: list[str] | None = None,
                  burn_in: int = 252) -> pd.DataFrame:
    """One row per factor. Columns: sleeve, ic stats per horizon, spread, stability."""
    F = flib.compute_all(panel, cfg, names=names)
    fwd = {h: forward_returns(panel.close, h) for h in horizons}

    rows = []
    for name, f in F.items():
        f = f.iloc[burn_in:]
        row: dict = {"factor": name, "sleeve": flib.REGISTRY[name]["sleeve"]}

        for h in horizons:
            ic = rank_ic(f, fwd[h].iloc[burn_in:])
            m, s = float(ic.mean()), float(ic.std())
            row[f"ic{h}"] = round(m, 4)
            row[f"ir{h}"] = round(m / (s + 1e-12) * np.sqrt(ANN / h), 2)
            row[f"hit{h}"] = round(float((ic > 0).mean()), 3)
            if h == 21:
                # overlap-corrected significance + regime stability
                row["tstat_nw21"] = round(nw_tstat(ic, lag=h), 2)
                # vol-regime conditioning: market realized vol terciles
                mvol = panel.market_ret.rolling(63, min_periods=21).std() \
                    .reindex(ic.index)
                lo_t, hi_t = mvol.quantile(1 / 3), mvol.quantile(2 / 3)
                row["ic21_lowvol"] = round(float(ic[mvol <= lo_t].mean()), 4)
                row["ic21_highvol"] = round(float(ic[mvol >= hi_t].mean()), 4)
                half = len(ic) // 2
                row["ic21_h1"] = round(float(ic.iloc[:half].mean()), 4)
                row["ic21_h2"] = round(float(ic.iloc[half:].mean()), 4)
                same_sign = np.sign(row["ic21_h1"]) == np.sign(row["ic21_h2"]) \
                    and abs(row["ic21_h1"]) > 1e-4 and abs(row["ic21_h2"]) > 1e-4
                row["stable"] = bool(same_sign)

        # quintile spread at 21d (annualized top-minus-bottom)
        r = f.rank(axis=1, pct=True)
        fw = fwd[21].iloc[burn_in:]
        top = fw.where(r > 0.8).mean(axis=1)
        bot = fw.where(r < 0.2).mean(axis=1)
        row["q5_q1_ann"] = round(float((top - bot).mean()) * ANN / 21, 4)

        # rank stability: Spearman(ranks_t, ranks_{t-5}); low => costly signal
        row["rank_stab5"] = round(float(rank_ic(f, f.shift(5)).mean()), 3)

        # IC decay half-life across horizons (days until IC halves; capped)
        ics = [abs(row.get(f"ic{h}", 0.0)) / h for h in horizons]   # per-day IC
        if ics[0] > 1e-5 and ics[-1] > 0:
            ratio = max(ics[-1] / ics[0], 1e-3)
            row["decay_hl"] = round(min(
                float(np.log(0.5) / (np.log(ratio) / (horizons[-1] - horizons[0]))
                      ) if ratio < 1 else 999.0, 999.0), 1)
        else:
            row["decay_hl"] = float("nan")

        rows.append(row)

    df = pd.DataFrame(rows).set_index("factor")
    return df.sort_values("ir21", ascending=False)


def report_markdown(df: pd.DataFrame, title: str = "Factor tearsheet") -> str:
    lines = [f"# {title}", "",
             "IR = annualized IC information ratio. q5_q1_ann = top-minus-bottom "
             "quintile 21d spread, annualized. rank_stab5 = 5d rank autocorr "
             "(low = high-turnover signal).", "",
             "| factor | sleeve | ic21 | ir21 | tNW | stable | ic5 | ic63 | q5-q1 ann | rank stab | decay hl |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in df.iterrows():
        lines.append(
            f"| {name} | {r['sleeve']} | {r['ic21']:+.4f} | {r['ir21']:+.2f} | "
            f"{r.get('tstat_nw21', float('nan')):+.1f} | "
            f"{'Y' if r.get('stable') else 'n'} | {r['ic5']:+.4f} | {r['ic63']:+.4f} | "
            f"{r['q5_q1_ann']:+.1%} | {r['rank_stab5']:.2f} | {r.get('decay_hl', float('nan')):.0f} |")

    weak = df[(df["ir21"].abs() < 0.3) & (df["ir5"].abs() < 0.3)]
    if len(weak):
        lines += ["", f"**Review list** (|IR| < 0.3 at 5d and 21d): "
                  + ", ".join(weak.index)]
    sig = df[(df.get("tstat_nw21", pd.Series(dtype=float)).abs() > 2.0) & df.get("stable", False)]
    if len(sig):
        lines += ["", f"**High-conviction** (|t_NW| > 2 AND sign-stable across halves): "
                  + ", ".join(sig.index)]
    lines += ["", "_Sign convention: factors are oriented long-attractive; negative IC "
              "means the orientation is wrong on this sample, not that the factor is dead._"]
    return "\n".join(lines)
