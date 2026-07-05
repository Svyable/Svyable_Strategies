"""DataFrame adapters for alpha-family governance reports.

The core alpha-family report is JSON/Markdown friendly. These adapters make the
same information easy to display in Streamlit, notebooks, and future review
surfaces without changing any portfolio artifacts or operational state.
"""

from __future__ import annotations

import pandas as pd

from svyable.alpha_family_governance import alpha_family_governance_report


def alpha_family_governance_frames() -> dict[str, pd.DataFrame]:
    """Return report tables as DataFrames for dashboards and notebooks."""
    report = alpha_family_governance_report()
    strategies = pd.DataFrame(report["strategy_rows"])
    factors = pd.DataFrame(report["factor_rows"])
    stage_counts = pd.DataFrame(report["stage_counts"])
    if not stage_counts.empty:
        stage_matrix = stage_counts.pivot_table(
            index="family",
            columns="stage",
            values="count",
            aggfunc="sum",
            fill_value=0,
        )
    else:
        stage_matrix = pd.DataFrame()
    return {
        "strategies": strategies,
        "factors": factors,
        "stage_counts": stage_counts,
        "stage_matrix": stage_matrix,
    }


def alpha_family_summary_rows() -> list[dict[str, object]]:
    """Return compact metric rows for PM review cards."""
    report = alpha_family_governance_report()
    return [
        {"metric": "status", "value": report["status"]},
        {"metric": "families", "value": len(report["families"])},
        {"metric": "factors", "value": report["factor_count"]},
        {"metric": "strategies", "value": report["strategy_count"]},
        {"metric": "warnings", "value": len(report.get("warnings", []) or [])},
        {"metric": "blockers", "value": len(report.get("blockers", []) or [])},
    ]
