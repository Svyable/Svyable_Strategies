"""Performance & risk analytics view for the Streamlit console.

Ports the highest-value Q23 dashboard visualizations (cumulative return, drawdown,
rolling metrics, calendar/monthly heatmaps, return distribution) onto Svyable's own
data. Everything here is driven by the shadow-NAV return series in ``pnl_diag.csv``
and the institutional metric functions in :mod:`svyable.metrics`, so it ports
robustly without any Q23 runtime dependency.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.dashboard_data import clean_returns, clean_timeseries, numeric_timeseries
from svyable.dashboard_service import DashboardService
from svyable.dashboard_stack import render_position_stack
from svyable.dashboard_ui import percent, render_figure
from svyable.metrics import ANN, deflated_sharpe, perf_summary

_MIN_DAYS = 20


def _rolling_frame(returns: pd.Series, window: int) -> pd.DataFrame:
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std()
    sharpe = (mean / (std + 1e-12)) * math.sqrt(ANN)
    vol = std * math.sqrt(ANN)
    return pd.DataFrame({"rolling_sharpe": sharpe, "rolling_vol": vol}).dropna()


def _period_return(returns: pd.Series, start: pd.Timestamp) -> float:
    window = returns[returns.index >= start]
    if window.empty:
        return float("nan")
    return float((1.0 + window).prod() - 1.0)


def _render_weights_section(weights_history: pd.DataFrame) -> None:
    """Concentration and turnover deep-dive, ported from Q23 `_weights` ideas."""
    frame = numeric_timeseries(weights_history)
    if frame.empty:
        st.info("No weights history yet. Run `svyable daily` to populate `weights_history.csv`.")
        return

    latest = frame.iloc[-1]
    gross = float(latest.abs().sum())
    herfindahl = float((latest**2).sum())
    sorted_abs = latest.abs().sort_values(ascending=False)
    top5 = float(sorted_abs.head(5).sum() / (gross + 1e-12)) if gross else 0.0
    top10 = float(sorted_abs.head(10).sum() / (gross + 1e-12)) if gross else 0.0
    turnover = frame.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = 0.0

    cols = st.columns(5)
    cols[0].metric("Positions", int((latest.abs() > 1e-9).sum()))
    cols[1].metric("Gross exposure", percent(gross))
    cols[2].metric("Top-5 concentration", percent(top5), help="Share of gross book in the 5 largest names.")
    cols[3].metric("Top-10 concentration", percent(top10))
    cols[4].metric(
        "Effective N",
        f"{1.0 / herfindahl:.1f}" if herfindahl > 0 else "—",
        help="1 / Herfindahl index — the diversification-equivalent number of equal positions.",
    )

    st.subheader("Top target positions")
    top_positions = latest[sorted_abs.head(20).index].rename("weight")
    top_positions.index.name = "symbol"
    display = pd.DataFrame(
        {"weight": top_positions, "weight_pct": top_positions.map(percent)}
    )
    st.dataframe(display, use_container_width=True)
    st.bar_chart(top_positions)

    st.subheader("Daily turnover")
    st.caption(
        f"Average one-way turnover: **{percent(float(turnover.mean()))}**  ·  "
        f"most recent: **{percent(float(turnover.iloc[-1]))}**"
    )
    st.line_chart(turnover.rename("turnover"))


def render_analytics(service: DashboardService) -> None:
    snapshot = service.strategy_snapshot()
    pnl = snapshot["pnl"]
    returns = clean_returns(pnl)

    if len(returns) < _MIN_DAYS:
        st.info(
            "Not enough return history for analytics yet. Run `svyable daily` to build "
            "up the shadow-NAV series in `pnl_diag.csv` (need at least "
            f"{_MIN_DAYS} days)."
        )
        return

    st.caption(
        f"Shadow-NAV analytics over {len(returns):,} trading days "
        f"({returns.index[0].date()} → {returns.index[-1].date()})."
    )

    summary = perf_summary(returns)
    last = returns.index[-1]
    wtd = _period_return(returns, last - pd.Timedelta(days=7))
    mtd = _period_return(returns, last - pd.DateOffset(months=1))
    ytd = _period_return(returns, pd.Timestamp(year=last.year, month=1, day=1))

    top = st.columns(6)
    top[0].metric("Ann. return", percent(summary.get("ann_return")), help="Annualized compounded shadow-NAV return.")
    top[1].metric("Ann. vol", percent(summary.get("ann_vol")), help="Annualized volatility of daily returns.")
    top[2].metric("Sharpe", summary.get("sharpe", "—"), help="Annualized return / volatility (rf assumed 0).")
    top[3].metric("Sortino", summary.get("sortino", "—"), help="Return per unit of downside deviation.")
    top[4].metric("Max drawdown", percent(summary.get("max_dd")), help="Deepest peak-to-trough decline.")
    top[5].metric("Calmar", summary.get("calmar", "—"), help="Annual return / |max drawdown|.")

    second = st.columns(6)
    second[0].metric("WTD", percent(wtd))
    second[1].metric("MTD", percent(mtd))
    second[2].metric("YTD", percent(ytd))
    second[3].metric("Win rate", percent(summary.get("win_rate")))
    second[4].metric("Best day", percent(summary.get("best_day")))
    second[5].metric("Worst day", percent(summary.get("worst_day")))

    perf_tab, risk_tab, calendar_tab, weights_tab, stack_tab, factor_tab = st.tabs(
        ["📈 Performance", "🛡️ Risk", "🗓️ Calendar", "⚖️ Weights", "🧱 Stack", "🔬 Distribution & IC"]
    )

    with perf_tab:
        render_figure(charts.cumulative_return_chart(returns))
        render_figure(charts.drawdown_chart(returns))
        diag = clean_timeseries(pnl)
        if not diag.empty and {"turnover", "gross_exposure"} & set(diag.columns):
            render_figure(charts.exposure_turnover_chart(diag))

    with risk_tab:
        max_window = min(252, len(returns) - 1)
        default_window = min(126, max_window)
        window = st.slider(
            "Rolling window (trading days)",
            min_value=20,
            max_value=max(max_window, 21),
            value=max(default_window, 20),
            step=5,
            help="Lookback used for rolling Sharpe and annualized volatility.",
        )
        rolling = _rolling_frame(returns, window)
        if not rolling.empty:
            render_figure(charts.rolling_metrics_chart(rolling, ["rolling_sharpe"], title=f"Rolling Sharpe ({window}d)"))
            render_figure(
                charts.rolling_metrics_chart(
                    rolling, ["rolling_vol"], title=f"Rolling Volatility ({window}d, annualized)"
                )
            )

        dsr = deflated_sharpe(returns)
        if "error" not in dsr:
            cols = st.columns(4)
            cols[0].metric("Deflated Sharpe prob", dsr["deflated_sharpe_prob"], help="P(true Sharpe > 0) after multiple-testing deflation (Bailey & López de Prado).")
            cols[1].metric("Verdict", dsr["verdict"])
            cols[2].metric("Skew", summary.get("skew", "—"))
            cols[3].metric("Kurtosis", summary.get("kurtosis", "—"))

    with calendar_tab:
        render_figure(charts.monthly_returns_heatmap(returns))
        render_figure(charts.calendar_heatmap(returns))

    with weights_tab:
        _render_weights_section(snapshot["weights_history"])

    with stack_tab:
        render_position_stack(snapshot["weights_history"])

    with factor_tab:
        render_figure(charts.return_distribution_chart(returns))
        ic = snapshot["ic_health"]
        if not ic.empty:
            st.subheader("Factor IC health (latest)")
            latest = ic.iloc[-1].sort_values(ascending=False).rename("smoothed_ic")
            st.bar_chart(latest)
        tail = summary.get("tail_ratio_95_5")
        if tail is not None:
            st.caption(
                f"Tail ratio (|p95| / |p05|): **{tail}** — values > 1 mean fatter right "
                "(gain) tail than left (loss) tail."
            )
