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

        # quintile spread at 21d (annualized top-minus-bottom)
        r = f.rank(axis=1, pct=True)
        fw = fwd[21].iloc[burn_in:]
        top = fw.where(r > 0.8).mean(axis=1)
        bot = fw.where(r < 0.2).mean(axis=1)
        row["q5_q1_ann"] = round(float((top - bot).mean()) * ANN / 21, 4)

        # rank stability: Spearman(ranks_t, ranks_{t-5}); low => costly signal
        row["rank_stab5"] = round(float(rank_ic(f, f.shift(5)).mean()), 3)

        rows.append(row)

    df = pd.DataFrame(rows).set_index("factor")
    return df.sort_values("ir21", ascending=False)


def report_markdown(df: pd.DataFrame, title: str = "Factor tearsheet") -> str:
    lines = [f"# {title}", "",
             "IR = annualized IC information ratio. q5_q1_ann = top-minus-bottom "
             "quintile 21d spread, annualized. rank_stab5 = 5d rank autocorr "
             "(low = high-turnover signal).", "",
             "| factor | sleeve | ic21 | ir21 | hit21 | ic5 | ir5 | ic63 | q5-q1 ann | stab |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in df.iterrows():
        lines.append(
            f"| {name} | {r['sleeve']} | {r['ic21']:+.4f} | {r['ir21']:+.2f} | "
            f"{r['hit21']:.0%} | {r['ic5']:+.4f} | {r['ir5']:+.2f} | {r['ic63']:+.4f} | "
            f"{r['q5_q1_ann']:+.1%} | {r['rank_stab5']:.2f} |")

    weak = df[(df["ir21"].abs() < 0.3) & (df["ir5"].abs() < 0.3)]
    if len(weak):
        lines += ["", f"**Review list** (|IR| < 0.3 at 5d and 21d): "
                  + ", ".join(weak.index)]
    lines += ["", "_Sign convention: factors are oriented long-attractive; negative IC "
              "means the orientation is wrong on this sample, not that the factor is dead._"]
    return "\n".join(lines)
