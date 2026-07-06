"""Plotly charts for the Streamlit PM console.

Matplotlib remains the robust static fallback. Plotly is used where interactivity
materially improves the PM workflow: hoverable candidate diagnostics, zoomable
risk/return maps, stress tapes, overlap heatmaps, factor-health maps, and
readable multi-strategy equity curves.
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


def signed_bar(series: pd.Series, *, title: str, xlabel: str = ""):
    """Interactive horizontal signed bar chart for stress and tail diagnostics."""
    _require_plotly()
    clean = pd.Series(series).dropna().astype(float).sort_values()
    frame = pd.DataFrame({"name": clean.index.astype(str), "value": clean.values})
    frame["sign"] = frame["value"].map(lambda value: "positive" if value >= 0 else "negative")
    fig = px.bar(
        frame,
        x="value",
        y="name",
        color="sign",
        orientation="h",
        title=title,
        template=_DARK_TEMPLATE,
        color_discrete_map={"positive": "#2ecc71", "negative": "#e74c3c"},
        hover_data={"value": ":.3%", "sign": False, "name": False},
    )
    fig.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.45)")
    fig.update_layout(
        height=max(360, 26 * len(frame) + 120),
        margin=dict(l=10, r=10, t=55, b=35),
        xaxis_title=xlabel,
        yaxis_title="",
        showlegend=False,
    )
    return fig


def matrix_heatmap(
    matrix: pd.DataFrame,
    *,
    title: str,
    z_format: str = ".2%",
    colorscale: str = "RdYlGn",
):
    """Interactive heatmap for monthly returns, overlap, IC, and position matrices."""
    _require_plotly()
    frame = matrix.copy()
    fig = px.imshow(
        frame,
        aspect="auto",
        color_continuous_scale=colorscale,
        title=title,
        template=_DARK_TEMPLATE,
        text_auto=z_format,
    )
    fig.update_layout(
        height=max(420, 22 * len(frame) + 150),
        margin=dict(l=10, r=10, t=55, b=40),
        xaxis_title="",
        yaxis_title="",
    )
    return fig


def drawdown_tape(drawdowns: pd.DataFrame, *, title: str = "Drawdown tape"):
    """Interactive multi-candidate drawdown tape."""
    _require_plotly()
    fig = go.Figure()
    for name in drawdowns.columns:
        series = pd.Series(drawdowns[name]).dropna().astype(float)
        if series.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                name=str(name),
                hovertemplate="%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.35)")
    fig.update_layout(
        title=title,
        template=_DARK_TEMPLATE,
        height=580,
        margin=dict(l=10, r=10, t=55, b=35),
        xaxis_title="Date",
        yaxis_title="Drawdown",
        hovermode="x unified",
    )
    return fig


def return_distribution(returns: pd.Series, *, title: str = "Return distribution"):
    """Interactive return-distribution histogram with hoverable bins."""
    _require_plotly()
    clean = pd.Series(returns).dropna().astype(float)
    fig = px.histogram(
        clean,
        nbins=60,
        title=title,
        template=_DARK_TEMPLATE,
        labels={"value": "Daily return", "count": "Days"},
    )
    fig.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.45)")
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=55, b=35), showlegend=False)
    return fig


def time_series_lines(frame: pd.DataFrame, *, title: str, y_title: str = ""):
    """Interactive line chart for candidate diagnostics such as exposure or regime tape."""
    _require_plotly()
    clean = frame.copy()
    fig = go.Figure()
    for column in clean.columns:
        series = pd.Series(clean[column]).dropna().astype(float)
        if series.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                name=str(column),
                hovertemplate="%{x}<br>%{y:.3f}<extra>%{fullData.name}</extra>",
            )
        )
    fig.update_layout(
        title=title,
        template=_DARK_TEMPLATE,
        height=500,
        margin=dict(l=10, r=10, t=55, b=35),
        xaxis_title="Date",
        yaxis_title=y_title,
        hovermode="x unified",
    )
    return fig


def factor_ic_scatter(frame: pd.DataFrame, *, title: str = "Factor IC reliability"):
    """Interactive factor-health map: IC IR versus coverage, sized by weight."""
    _require_plotly()
    data = frame.copy()
    if data.index.name or "factor" not in data.columns:
        data = data.reset_index().rename(columns={data.index.name or "index": "factor"})
    for column in ["ic_ir", "coverage", "weight", "mean_ic", "hit_rate", "observations"]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    if "ic_ir" not in data.columns or "coverage" not in data.columns:
        raise ValueError("factor health frame is missing ic_ir or coverage")
    if "weight" not in data.columns:
        data["weight"] = 1.0
    data["marker_size"] = data["weight"].abs().fillna(0.0).clip(lower=0.01)
    hover = [column for column in ["factor", "stage", "pm_state", "mean_ic", "hit_rate", "observations", "weight"] if column in data.columns]
    fig = px.scatter(
        data,
        x="coverage",
        y="ic_ir",
        color="pm_state" if "pm_state" in data.columns else "stage" if "stage" in data.columns else None,
        size="marker_size",
        text="factor" if "factor" in data.columns else None,
        hover_data=hover,
        title=title,
        template=_DARK_TEMPLATE,
        color_discrete_sequence=_COLOR_SEQUENCE,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.45)")
    fig.update_traces(textposition="top center")
    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=55, b=40),
        xaxis_title="Coverage",
        yaxis_title="IC information ratio",
        legend_title_text="PM state",
    )
    return fig


def strategy_shadow_mix(coverage: pd.DataFrame):
    """Interactive stacked bar for proven versus shadow factor mix by strategy."""
    _require_plotly()
    cols = [column for column in ["proven_factors", "shadow_factors"] if column in coverage.columns]
    if not cols:
        raise ValueError("coverage frame is missing proven/shadow factor counts")
    frame = coverage.copy().reset_index().rename(columns={coverage.index.name or "index": "strategy_id"})
    id_col = "strategy_id" if "strategy_id" in frame.columns else frame.columns[0]
    long = frame.melt(
        id_vars=[id_col],
        value_vars=cols,
        var_name="factor_type",
        value_name="count",
    )
    fig = px.bar(
        long,
        x=id_col,
        y="count",
        color="factor_type",
        title="Strategy factor maturity mix",
        template=_DARK_TEMPLATE,
        color_discrete_map={"proven_factors": "#2ecc71", "shadow_factors": "#f1c40f"},
    )
    fig.update_layout(
        height=max(450, 20 * frame[id_col].nunique() + 160),
        margin=dict(l=10, r=10, t=55, b=120),
        xaxis_title="Strategy",
        yaxis_title="Factor count",
        legend_title_text="Factor type",
    )
    return fig


def multi_equity(curves: Mapping[str, pd.Series], *, highlight: str | None = None, title: str = "Candidate equity curves"):
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
        title=title,
        template=_DARK_TEMPLATE,
        height=650,
        margin=dict(l=10, r=10, t=60, b=40),
        xaxis_title="Date",
        yaxis_title="Growth of $1",
        legend_title_text="Candidate",
        hovermode="x unified",
    )
    return fig
