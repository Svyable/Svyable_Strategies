"""Plotly charts for the Streamlit PM console.

Matplotlib remains the robust static fallback. Plotly is used where interactivity
materially improves the PM workflow: hoverable candidate diagnostics, zoomable
risk/return maps, and readable multi-strategy equity curves.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

try:  # pragma: no cover - exercised when the GUI extra is installed
    import plotly.express as px
    import plotly.graph_objects as go
except Exception:  # pragma: no cover - optional dependency fallback
    px = None
    go = None

_DARK_TEMPLATE = "plotly_dark"
_COLOR_SEQUENCE = (
    "#2ecc71",
    "#3498db",
    "#f39c12",
    "#9b59b6",
    "#e74c3c",
    "#1abc9c",
    "#f1c40f",
    "#e67e22",
    "#ecf0f1",
    "#7f8c8d",
)
_CALL_COLORS = {
    "GREENLIGHT": "#2ecc71",
    "REVIEW": "#f1c40f",
    "HOLD CURRENT": "#3498db",
    "HOLD BASELINE": "#95a5a6",
    "BLOCK": "#e74c3c",
}


def available() -> bool:
    return px is not None and go is not None


def _require_plotly() -> None:
    if not available():
        raise RuntimeError("Plotly is not installed; install the gui extra to enable interactive charts.")


def _candidate_frame(board: pd.DataFrame) -> pd.DataFrame:
    frame = board.copy()
    if "candidate_id" in frame.columns:
        frame["candidate_id"] = frame["candidate_id"].astype(str)
    if "eligible" in frame.columns:
        frame["eligibility"] = frame["eligible"].map(lambda value: "eligible" if bool(value) else "blocked")
    else:
        frame["eligibility"] = "eligible"
    for column in [
        "utility_bps",
        "expected_alpha_bps",
        "net_expected_alpha_bps",
        "estimated_cost_bps",
        "one_way_turnover",
        "current_overlap",
        "recent_vol",
        "recent_max_drawdown",
        "sharpe_252d",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def candidate_ranking(
    board: pd.DataFrame,
    value_col: str = "utility_bps",
    *,
    title: str = "Candidate ranking",
):
    """Interactive horizontal ranking with hover diagnostics."""
    _require_plotly()
    frame = _candidate_frame(board)
    if value_col not in frame.columns or "candidate_id" not in frame.columns:
        raise ValueError(f"candidate board is missing {value_col!r} or candidate_id")
    frame = frame.dropna(subset=[value_col]).sort_values(value_col, ascending=True)
    hover = [
        column for column in [
            "name",
            "family",
            "eligibility",
            "net_expected_alpha_bps",
            "estimated_cost_bps",
            "one_way_turnover",
            "current_overlap",
            "recent_vol",
            "recent_max_drawdown",
            "output_dir",
        ] if column in frame.columns
    ]
    fig = px.bar(
        frame,
        x=value_col,
        y="candidate_id",
        color="family" if "family" in frame.columns else "eligibility",
        pattern_shape="eligibility",
        orientation="h",
        hover_data=hover,
        title=title,
        template=_DARK_TEMPLATE,
        color_discrete_sequence=_COLOR_SEQUENCE,
    )
    fig.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.45)")
    fig.update_layout(
        height=max(420, 26 * len(frame) + 140),
        margin=dict(l=10, r=10, t=60, b=40),
        xaxis_title=value_col.replace("_", " ").title(),
        yaxis_title="",
        legend_title_text="Family",
    )
    return fig


def alpha_cost_map(board: pd.DataFrame, *, highlight: str | None = None):
    """Interactive expected-alpha versus turnover/cost map for PM trade-off review."""
    _require_plotly()
    frame = _candidate_frame(board)
    if "expected_alpha_bps" not in frame.columns or "one_way_turnover" not in frame.columns:
        raise ValueError("candidate board is missing expected_alpha_bps or one_way_turnover")
    frame["turnover_pct"] = frame["one_way_turnover"] * 100.0
    size_source = frame.get("utility_bps", pd.Series(1.0, index=frame.index)).abs().fillna(1.0)
    frame["marker_size"] = size_source.clip(lower=0.25) + 1.0
    hover = [
        column for column in [
            "name",
            "family",
            "eligibility",
            "utility_bps",
            "net_expected_alpha_bps",
            "estimated_cost_bps",
            "current_overlap",
            "sharpe_252d",
            "recent_max_drawdown",
        ] if column in frame.columns
    ]
    fig = px.scatter(
        frame,
        x="turnover_pct",
        y="expected_alpha_bps",
        color="family" if "family" in frame.columns else "eligibility",
        symbol="eligibility",
        size="marker_size",
        text="candidate_id",
        hover_data=hover,
        title="Expected alpha vs. turnover",
        template=_DARK_TEMPLATE,
        color_discrete_sequence=_COLOR_SEQUENCE,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.45)")
    fig.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.25)")
    if highlight and "candidate_id" in frame.columns:
        selected = frame[frame["candidate_id"] == str(highlight)]
        if not selected.empty:
            fig.add_trace(
                go.Scatter(
                    x=selected["turnover_pct"],
                    y=selected["expected_alpha_bps"],
                    mode="markers+text",
                    text=selected["candidate_id"],
                    textposition="top center",
                    marker=dict(size=22, color="rgba(0,0,0,0)", line=dict(width=4, color="#f1c40f")),
                    name="currently held",
                    hoverinfo="skip",
                )
            )
    fig.update_traces(textposition="top center", selector=dict(mode="markers+text"))
    fig.update_layout(
        height=650,
        margin=dict(l=10, r=10, t=60, b=40),
        xaxis_title="One-way turnover (%)",
        yaxis_title="Expected alpha (bps)",
        legend_title_text="Family",
    )
    return fig


def decision_scorecard_map(scorecard: pd.DataFrame):
    """Interactive PM scorecard: edge versus risk, colored by play call."""
    _require_plotly()
    if scorecard.empty:
        raise ValueError("scorecard is empty")
    frame = scorecard.copy()
    frame["marker_size"] = pd.to_numeric(frame["conviction_score"], errors="coerce").abs().fillna(1.0).clip(lower=1.0)
    hover = [
        column for column in [
            "name",
            "family",
            "play_call",
            "utility_bps",
            "net_expected_alpha_bps",
            "estimated_cost_bps",
            "one_way_turnover",
            "current_overlap",
            "recent_vol",
            "recent_max_drawdown",
            "risk_flags",
            "action",
        ] if column in frame.columns
    ]
    fig = px.scatter(
        frame,
        x="risk_points",
        y="edge_vs_hold_bps",
        color="play_call",
        size="marker_size",
        text="candidate_id",
        hover_data=hover,
        title="Decision scorecard: edge vs. risk",
        template=_DARK_TEMPLATE,
        color_discrete_map=_CALL_COLORS,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.45)")
    fig.update_traces(textposition="top center")
    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=60, b=40),
        xaxis_title="Risk points (lower is cleaner)",
        yaxis_title="Edge versus hold-current utility (bps)",
        legend_title_text="Play call",
    )
    return fig


def multi_equity(curves: Mapping[str, pd.Series], *, highlight: str | None = None):
    """Interactive normalized NAV overlay for candidate return curves."""
    _require_plotly()
    fig = go.Figure()
    for name, series in curves.items():
        clean = pd.Series(series).dropna().astype(float)
        if clean.empty:
            continue
        nav = (1.0 + clean).cumprod()
        is_highlight = str(name) == str(highlight)
        fig.add_trace(
            go.Scatter(
                x=nav.index,
                y=nav.values,
                mode="lines",
                name=str(name),
                line=dict(width=4 if is_highlight else 1.7, color="#f1c40f" if is_highlight else None),
                opacity=1.0 if is_highlight else 0.72,
                hovertemplate="%{x}<br>%{y:.3f}x<extra>%{fullData.name}</extra>",
            )
        )
    fig.update_layout(
        title="Candidate equity curves",
        template=_DARK_TEMPLATE,
        height=650,
        margin=dict(l=10, r=10, t=60, b=40),
        xaxis_title="Date",
        yaxis_title="Growth of $1",
        legend_title_text="Candidate",
        hovermode="x unified",
    )
    return fig
