"""Robust factor research harness and promotion gate."""

from __future__ import annotations

from math import erfc, sqrt

import numpy as np
import pandas as pd

from svyable import factor_library as flib
from svyable.config import SvyableConfig
from svyable.panel import Panel, forward_returns
from svyable.weighting import ic_coverage, rank_ic

ANN = 252.0


def nw_tstat(series: pd.Series, lag: int) -> float:
    values = series.dropna().to_numpy(dtype=float)
    count = len(values)
    if count < lag + 10:
        return float("nan")
    centered = values - values.mean()
    variance = float(centered @ centered) / count
    for offset in range(1, lag + 1):
        covariance = float(centered[offset:] @ centered[:-offset]) / count
        variance += 2.0 * (1.0 - offset / (lag + 1.0)) * covariance
    return float(values.mean() / np.sqrt(max(variance, 1e-18) / count))


def _pvalue(t_stat: float) -> float:
    return float(erfc(abs(t_stat) / sqrt(2.0))) if np.isfinite(t_stat) else np.nan


def _bh_qvalues(pvalues: pd.Series) -> pd.Series:
    valid = pvalues.dropna().sort_values()
    result = pd.Series(np.nan, index=pvalues.index, dtype=float)
    if valid.empty:
        return result
    count = len(valid)
    raw = valid.to_numpy() * count / np.arange(1, count + 1)
    result.loc[valid.index] = np.minimum.accumulate(raw[::-1])[::-1].clip(0.0, 1.0)
    return result


def factor_report(
    panel: Panel,
    cfg: SvyableConfig,
    horizons: tuple[int, ...] = (1, 5, 21, 63),
    names: list[str] | None = None,
    burn_in: int = 252,
) -> pd.DataFrame:
    factors = flib.compute_all(panel, cfg, names=names)
    catalog = flib.factor_metadata(factors)
    forward = {h: forward_returns(panel.close, h) for h in horizons}
    eligible = panel.liquidity_mask(cfg.min_adv, cfg.min_price, cfg.adv_win).astype(bool)
    rows = []

    for name, full_factor in factors.items():
        factor = full_factor.iloc[burn_in:]
        liquid = eligible.iloc[burn_in:]
        row = {
            "factor": name,
            "sleeve": catalog.loc[name, "sleeve"],
            "stage": catalog.loc[name, "stage"],
            "lineage": catalog.loc[name, "lineage"],
        }
        for horizon in horizons:
            future = forward[horizon].iloc[burn_in:]
            ic = rank_ic(
                factor,
                future,
                eligible=liquid,
                min_obs=cfg.ic_min_cross_section,
            )
            coverage = ic_coverage({name: factor}, future, eligible=liquid)[name]
            mean_ic, ic_vol = float(ic.mean()), float(ic.std())
            row[f"ic{horizon}"] = round(mean_ic, 4)
            row[f"ir{horizon}"] = round(
                mean_ic / (ic_vol + 1e-12) * np.sqrt(ANN / horizon), 2
            )
            row[f"hit{horizon}"] = round(float((ic > 0).mean()), 3)
            row[f"coverage{horizon}"] = round(float(coverage.mean()), 3)
            row[f"n_ic{horizon}"] = int(ic.notna().sum())
            if horizon == 21:
                t_stat = nw_tstat(ic, horizon)
                midpoint = len(ic) // 2
                first, second = float(ic.iloc[:midpoint].mean()), float(ic.iloc[midpoint:].mean())
                row.update(
                    tstat_nw21=round(t_stat, 2),
                    pvalue_nw21=_pvalue(t_stat),
                    ic21_h1=round(first, 4),
                    ic21_h2=round(second, 4),
                    stable=bool(
                        np.sign(first) == np.sign(second)
                        and abs(first) > 1e-4
                        and abs(second) > 1e-4
                    ),
                )

        ranks = factor.rank(axis=1, pct=True)
        future_21 = forward[21].iloc[burn_in:]
        spread = future_21.where((ranks > 0.8) & liquid).mean(axis=1) - future_21.where(
            (ranks < 0.2) & liquid
        ).mean(axis=1)
        row["q5_q1_ann"] = round(float(spread.mean()) * ANN / 21, 4)
        row["rank_stab5"] = round(
            float(
                rank_ic(
                    factor,
                    factor.shift(5),
                    eligible=liquid,
                    min_obs=cfg.ic_min_cross_section,
                ).mean()
            ),
            3,
        )
        rows.append(row)

    report = pd.DataFrame(rows).set_index("factor")
    report["qvalue_bh21"] = _bh_qvalues(report["pvalue_nw21"])
    enough = report["coverage21"].ge(cfg.ic_min_coverage) & report["n_ic21"].ge(
        max(cfg.ic_min_history, 42)
    )
    valid = (
        report["tstat_nw21"].ge(3.0)
        & report["qvalue_bh21"].le(0.10)
        & report["stable"].fillna(False)
        & report["ir21"].gt(0)
    )
    report["promotion_state"] = "monitor"
    report.loc[~enough, "promotion_state"] = "insufficient_evidence"
    report.loc[enough & report["ir21"].le(0), "promotion_state"] = "quarantine"
    report.loc[enough & valid & report["stage"].eq("proven"), "promotion_state"] = "validated"
    report.loc[enough & valid & report["stage"].eq("shadow"), "promotion_state"] = "promotion_candidate"
    return report.sort_values(["promotion_state", "ir21"], ascending=[True, False])


def report_markdown(df: pd.DataFrame, title: str = "Factor tearsheet") -> str:
    lines = [
        f"# {title}",
        "",
        "IC uses eligible pairwise observations. tNW is overlap-aware; qBH controls false discoveries across factors.",
        "",
        "| factor | stage | state | sleeve | ic21 | ir21 | tNW | qBH | cov | stable | spread |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, row in df.iterrows():
        lines.append(
            f"| {name} | {row['stage']} | {row['promotion_state']} | {row['sleeve']} | "
            f"{row['ic21']:+.4f} | {row['ir21']:+.2f} | {row['tstat_nw21']:+.1f} | "
            f"{row['qvalue_bh21']:.3f} | {row['coverage21']:.1%} | "
            f"{'Y' if row.get('stable') else 'n'} | {row['q5_q1_ann']:+.1%} |"
        )
    candidates = df[df["promotion_state"].eq("promotion_candidate")]
    if len(candidates):
        lines += ["", "**Promotion candidates**: " + ", ".join(candidates.index)]
    lines += [
        "",
        "_Promotion is an evidence state, not an automatic production change; walk-forward and capacity review remain required._",
    ]
    return "\n".join(lines)
