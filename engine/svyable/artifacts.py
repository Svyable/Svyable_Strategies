"""Evidence chain (strategy.md §6): every run writes the full artifact set
BEFORE any order leaves the building. Plus the morning report the daily loop
delivers before 8:30 AM ET.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


class ArtifactWriter:
    def __init__(self, output_root: str | Path, strategy_id: str, tag: str | None = None):
        self.tag = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = Path(output_root) / strategy_id / self.tag
        self.dir.mkdir(parents=True, exist_ok=True)

    def write_frame(self, name: str, df: pd.DataFrame | pd.Series) -> Path:
        p = self.dir / f"{name}.csv"
        df.to_csv(p)
        return p

    def write_meta(self, meta: dict) -> Path:
        p = self.dir / "meta.json"
        p.write_text(json.dumps(meta, indent=2, default=str))
        return p

    def write_report(self, text: str) -> Path:
        p = self.dir / "morning_report.md"
        p.write_text(text)
        # also refresh a stable "latest" pointer for the loop/PM
        latest = self.dir.parent / "LATEST.md"
        latest.write_text(text)
        return p


def morning_report(*, strategy_id: str, tag: str, weights_today: pd.Series,
                   weights_prev: pd.Series | None, budget: float, seats: int,
                   sleeve_weights: pd.Series, ic_health: pd.Series,
                   stress: float, kill_switch: bool, data_report: dict,
                   perf_recent: dict, config_hash: str) -> str:
    """Human-readable (and Claude-readable) daily deliverable."""
    w = weights_today[weights_today > 0].sort_values(ascending=False)
    lines = [
        f"# {strategy_id} — Morning Report  ({tag})",
        "",
        f"- **Data**: {data_report.get('last_date')} close | {data_report.get('assets')} assets | "
        f"status **{data_report.get('status', 'ok').upper()}**",
        f"- **Gross budget**: {budget:.2f}x | **Seats**: {seats} | "
        f"**Stress**: {stress:.2f} | **Kill switch**: {'TRIPPED — at lev_min' if kill_switch else 'clear'}",
        f"- **Config hash**: `{config_hash}`",
        "",
        "## Target weights (before 8:30 AM ET)",
        "",
        "| Ticker | Weight | Δ vs yesterday |",
        "|---|---|---|",
    ]
    for sym, wt in w.items():
        prev = float(weights_prev.get(sym, 0.0)) if weights_prev is not None else 0.0
        lines.append(f"| {sym} | {wt:.2%} | {wt - prev:+.2%} |")

    if weights_prev is not None:
        exits = weights_prev[(weights_prev > 0) & (weights_today.reindex(weights_prev.index).fillna(0) <= 0)]
        if len(exits):
            lines += ["", "**Exits**: " + ", ".join(f"{s} ({v:.2%})" for s, v in exits.items())]
        l1 = float((weights_today.reindex(weights_prev.index.union(weights_today.index)).fillna(0)
                    - weights_prev.reindex(weights_prev.index.union(weights_today.index)).fillna(0)).abs().sum())
        lines += ["", f"**One-way turnover today**: {l1 / 2:.1%}"]

    lines += ["", "## Sleeve trust (IC meta-learner)", "",
              "| Sleeve | Weight | Smoothed IC |", "|---|---|---|"]
    for s in sleeve_weights.index:
        lines.append(f"| {s} | {sleeve_weights[s]:.1%} | {ic_health.get(s, float('nan')):+.4f} |")

    lines += ["", "## Recent performance (shadow book, net of modeled costs)", ""]
    for k, v in perf_recent.items():
        lines.append(f"- {k}: {v}")

    issues = data_report.get("issues") or []
    if issues:
        lines += ["", "## ⚠️ Data warnings", ""] + [f"- {i}" for i in issues]
        lines += ["", "**Rule: do not trade on DEGRADED data without human review.**"]

    lines += ["", "---", f"Generated {datetime.now().isoformat(timespec='seconds')} — Svyable engine"]
    return "\n".join(lines)
