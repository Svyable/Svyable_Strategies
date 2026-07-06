"""Per-candidate temporal deep-dive for the agent lab.

The board charts answer "which candidate today"; this surface answers "how has a
single candidate behaved through time". It reuses the same Q23-ported chart
helpers the held-strategy analytics use — the ``position stack`` weight-by-name
heatmap, cumulative return, drawdown, monthly seasonality, exposure/turnover,
sleeve trust, and IC health — but drives them from any candidate's run
artifacts, so the whole registry frontier gets the deep back-view analytics, not
just the one book that happens to be live.

Data access lives in :mod:`svyable.dashboard_data`; charts in
:mod:`svyable.dashboard_charts`. This module is the thin Streamlit layer.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable import dashboard_interactive as interactive
from svyable.dashboard_data import clean_returns, load_candidate_timeseries
from svyable.dashboard_stack import render_position_stack
from svyable.dashboard_ui import render_figure, render_plotly
from svyable.strategy_selection_service import StrategySelectionService


def _metric_row(board_row: pd.Series | None) -> None:
    if board_row is None:
        return
    cols = st.columns(6)

    def _fmt(value: object, suffix: str = "", pct: bool = False) -> str:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return "—"
        return f"{number:.1%}" if pct else f"{number:.2f}{suffix}"

    cols[0].metric("Family", str(board_row.get("family", "—")))
    cols[1].metric("Eligible", "yes" if bool(board_row.get("eligible", False)) else "NO")
    cols[2].metric("Utility", _fmt(board_row.get("utility_bps"), " bps"))
    cols[3].metric("Return 252d", _fmt(board_row.get("return_252d"), pct=True))
    cols[4].metric("Sharpe 252d", _fmt(board_row.get("sharpe_252d")))
    cols[5].metric("Max drawdown", _fmt(board_row.get("recent_max_drawdown"), pct=True))


def _drawdown(returns: pd.Series) -> pd.Series:
    nav = (1.0 + returns.fillna(0.0)).cumprod()
    return nav / nav.cummax() - 1.0


def _rolling_hit_rate(returns: pd.Series, window: int = 63) -> pd.Series:
    clean = returns.dropna().astype(float)
    return (clean > 0).rolling(window).mean().dropna()


def _monthly_matrix(returns: pd.Series) -> pd.DataFrame:
    monthly = (1.0 + returns.dropna().astype(float)).resample("ME").prod() - 1.0
    if monthly.empty:
        return pd.DataFrame()
    frame = monthly.to_frame("return")
    frame["year"] = frame.index.year.astype(str)
    frame["month"] = frame.index.strftime("%b")
    order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return frame.pivot(index="year", columns="month", values="return").reindex(columns=order)


def render_candidate_analytics(
    service: StrategySelectionService,
    board: pd.DataFrame,
    registry: pd.DataFrame | None = None,
    *,
    default_candidate: str | None = None,
) -> None:
    """Interactive temporal deep-dive for one candidate on the current board."""
    if board is None or board.empty or "candidate_id" not in board.columns:
        st.caption("No candidate board yet — run a fresh evaluation to unlock deep-dive analytics.")
        return

    st.markdown("### 🔬 Candidate deep-dive")
    st.caption(
        "Pick any candidate on the board to see its full back-view: how its book "
        "of names, exposure, sleeves, and risk have evolved through time — the "
        "same analytics the live strategy gets, for every candidate in the registry."
    )

    output_root = Path(service.output_root)
    candidates = board["candidate_id"].astype(str).tolist()
    # Prefer the held/selected candidate, then the top-utility row, as the default.
    if default_candidate not in candidates:
        default_candidate = candidates[0]
    candidate = st.selectbox(
        "Candidate",
        candidates,
        index=candidates.index(default_candidate),
        key="candidate_deepdive_select",
    )

    board_row = board[board["candidate_id"].astype(str) == candidate].iloc[0]
    _metric_row(board_row)

    diag = load_candidate_timeseries(output_root, board, candidate, "pnl_diag.csv")
    weights_history = load_candidate_timeseries(output_root, board, candidate, "weights_history.csv", numeric=True)
    returns = clean_returns(diag, "net_ret") if not diag.empty else pd.Series(dtype=float)
    benchmark = clean_returns(diag, "benchmark_ret") if not diag.empty else pd.Series(dtype=float)

    if returns.empty and weights_history.empty:
        st.info(
            f"No temporal run artifacts found for `{candidate}` yet. Run a fresh "
            "candidate evaluation so each candidate writes its shadow history."
        )
        return

    stack_tab, perf_tab, exposure_tab, sleeve_tab, regime_tab = st.tabs(
        [
            "📚 Position stack",
            "📈 Performance",
            "⚖️ Exposure & turnover",
            "🧭 Sleeves & IC",
            "🌡️ Regime",
        ]
    )

    with stack_tab:
        if weights_history.empty:
            st.caption("No `weights_history.csv` for this candidate yet.")
        else:
            render_position_stack(weights_history)

    with perf_tab:
        if returns.empty:
            st.caption("No return history (`pnl_diag.csv`) for this candidate yet.")
        else:
            if interactive.available():
                overlay = {candidate: returns}
                if not benchmark.empty:
                    overlay["benchmark"] = benchmark
                render_plotly(interactive.multi_equity(overlay, highlight=candidate, title=f"{candidate} — cumulative return"))
                left, right = st.columns(2)
                with left:
                    render_plotly(interactive.drawdown_tape(pd.DataFrame({candidate: _drawdown(returns)}), title="Drawdown"))
                with right:
                    hit_rate = _rolling_hit_rate(returns)
                    if hit_rate.empty:
                        st.caption("Need more return history for rolling hit rate.")
                    else:
                        render_plotly(interactive.time_series_lines(hit_rate.to_frame("rolling_hit_rate"), title="Rolling hit rate", y_title="Hit rate"))
                if len(returns) >= 40:
                    monthly = _monthly_matrix(returns)
                    if not monthly.empty:
                        render_plotly(interactive.matrix_heatmap(monthly, title=f"{candidate} — monthly returns", z_format=".1%"))
                render_plotly(interactive.return_distribution(returns, title=f"{candidate} — return distribution"))
            else:
                render_figure(
                    charts.cumulative_return_chart(
                        returns,
                        benchmark if not benchmark.empty else None,
                        title=f"{candidate} — cumulative return",
                    )
                )
                left, right = st.columns(2)
                with left:
                    render_figure(charts.drawdown_chart(returns, title="Drawdown"))
                with right:
                    render_figure(charts.rolling_hit_rate_chart(returns))
                if len(returns) >= 40:
                    render_figure(charts.monthly_returns_heatmap(returns))
                render_figure(charts.return_distribution_chart(returns))

    with exposure_tab:
        if not diag.empty and {"gross_exposure", "turnover"} & set(diag.columns):
            if interactive.available():
                cols = [col for col in ["gross_exposure", "turnover", "net_exposure", "cash"] if col in diag.columns]
                render_plotly(interactive.time_series_lines(diag[cols], title=f"{candidate} — exposure & turnover"))
            else:
                render_figure(charts.exposure_turnover_chart(diag, title=f"{candidate} — exposure & turnover"))
        else:
            st.caption("No exposure/turnover columns in this candidate's diagnostics.")
        if not weights_history.empty:
            render_figure(charts.long_short_exposure_chart(weights_history))

    with sleeve_tab:
        sleeve_weights = load_candidate_timeseries(output_root, board, candidate, "sleeve_weights.csv", numeric=True)
        ic_health = load_candidate_timeseries(output_root, board, candidate, "ic_health.csv", numeric=True)
        if sleeve_weights.empty and ic_health.empty:
            st.caption("No sleeve or IC-health artifacts for this candidate.")
        if not sleeve_weights.empty:
            if interactive.available():
                render_plotly(interactive.time_series_lines(sleeve_weights, title=f"{candidate} — sleeve allocation over time"))
            else:
                render_figure(charts.sleeve_trust_area_chart(sleeve_weights, title=f"{candidate} — sleeve allocation over time"))
        if not ic_health.empty:
            if interactive.available():
                render_plotly(interactive.matrix_heatmap(ic_health.T, title=f"{candidate} — smoothed IC health over time", z_format=".2f"))
            else:
                render_figure(charts.ic_health_heatmap(ic_health, title=f"{candidate} — smoothed IC health over time"))

    with regime_tab:
        regime = load_candidate_timeseries(output_root, board, candidate, "regime.csv", numeric=True)
        if regime.empty:
            st.caption("No regime diagnostics for this candidate.")
        else:
            columns = [c for c in ("throttle", "turb_pct", "absorption", "breadth", "regime_risk") if c in regime.columns]
            if columns:
                st.caption(
                    "Regime tape shared by the market panel: budget throttle, turbulence "
                    "and absorption percentiles, breadth, and composite regime risk."
                )
                if interactive.available():
                    render_plotly(interactive.time_series_lines(regime[columns].tail(252), title=f"{candidate} — regime tape"))
                else:
                    st.line_chart(regime[columns].tail(252))
            else:
                st.dataframe(regime.tail(60), use_container_width=True)
