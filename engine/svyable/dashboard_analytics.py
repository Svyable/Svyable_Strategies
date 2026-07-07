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
from svyable.factor_health_tools import factor_review_summary, factor_trend_alerts
from svyable.metrics import ANN, deflated_sharpe, perf_summary
from svyable.portfolio_arcana import market_model

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


def _render_arcana_section(pnl: pd.DataFrame, returns: pd.Series, snapshot: dict) -> None:
    st.caption(
        "Arcana lens: separates market exposure from residual return so any book can be judged "
        "by idiosyncratic alpha, residual volatility, and residual hit rate rather than headline PnL alone."
    )
    diag = clean_timeseries(pnl)
    benchmark = pd.Series(dtype=float)
    if "benchmark_ret" in diag.columns:
        benchmark = pd.to_numeric(diag["benchmark_ret"], errors="coerce")
    if benchmark.empty or benchmark.dropna().empty:
        st.info("No benchmark return column is available yet for market-model residual analysis.")
        return

    summary, residual = market_model(returns, benchmark)
    if summary.get("status") != "ok":
        st.info(f"Arcana needs more aligned return history. Current days: {summary.get('days', 0)}.")
        return

    cols = st.columns(6)
    cols[0].metric("Market beta", f"{summary['beta']:.2f}")
    cols[1].metric("Ann. residual alpha", percent(summary["ann_residual_alpha"]))
    cols[2].metric("Idio vol", percent(summary["ann_idio_vol"]))
    cols[3].metric("Idio IR", f"{summary['idio_information_ratio']:.2f}")
    cols[4].metric("Market R²", percent(summary["r2_market"]))
    cols[5].metric("Residual hit rate", percent(summary["residual_hit_rate"]))

    if not residual.empty:
        st.markdown("**Residual return stream**")
        render_figure(charts.cumulative_return_chart(residual, title="Beta-adjusted residual return"))
        rolling = residual.rolling(63, min_periods=32).mean() * ANN
        st.line_chart(rolling.rename("rolling_ann_residual_alpha_63d"))

    ic = snapshot.get("ic_health", pd.DataFrame())
    if not ic.empty:
        st.markdown("**Factor trend alerts**")
        alerts = factor_trend_alerts(ic)
        summary_row = factor_review_summary(alerts, pd.DataFrame())
        cols = st.columns(5)
        cols[0].metric("Factor review", summary_row["headline"])
        cols[1].metric("Deteriorating", summary_row["deteriorating"])
        cols[2].metric("Watch", summary_row["watch"])
        cols[3].metric("Improving", summary_row["improving"])
        cols[4].metric("IC series", len(alerts))
        if alerts.empty:
            st.info("Not enough factor IC history for trend alerts yet.")
        else:
            display = alerts.head(25).copy()
            st.dataframe(
                display.style.format(
                    {
                        "latest_ic": "{:.4f}",
                        "short_ic": "{:.4f}",
                        "long_ic": "{:.4f}",
                        "ic_delta": "{:.4f}",
                        "slope": "{:.6f}",
                    }
                ).background_gradient(subset=["latest_ic", "ic_delta"], cmap="RdYlGn"),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("**Current factor health context**")
        latest = ic.iloc[-1].sort_values(ascending=False).rename("smoothed_ic")
        st.dataframe(latest.to_frame().head(20), use_container_width=True)


def _render_weights_section(weights_history: pd.DataFrame) -> None:
    """Concentration, turnover, and long/short exposure deep-dive."""
    frame = numeric_timeseries(weights_history)
    if frame.empty:
        st.info("No weights history yet. Run `svyable daily` to populate `weights_history.csv`.")
        return

    latest = frame.iloc[-1].astype(float)
    gross = float(latest.abs().sum())
    long_gross = float(latest.clip(lower=0.0).sum())
    short_gross = float(latest.clip(upper=0.0).abs().sum())
    net = float(latest.sum())
    herfindahl = float((latest**2).sum())
    sorted_abs = latest.abs().sort_values(ascending=False)
    top5 = float(sorted_abs.head(5).sum() / (gross + 1e-12)) if gross else 0.0
    top10 = float(sorted_abs.head(10).sum() / (gross + 1e-12)) if gross else 0.0
    turnover = frame.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = 0.0

    cols = st.columns(6)
    cols[0].metric("Long gross", percent(long_gross), help="Total positive target weight.")
    cols[1].metric("Short gross", percent(short_gross), help="Absolute value of negative target weight.")
    cols[2].metric("Net exposure", percent(net), help="Long minus short exposure.")
    cols[3].metric("Gross exposure", percent(gross), help="Long plus absolute short exposure.")
    cols[4].metric("Long / short names", f"{int((latest > 0).sum())} / {int((latest < 0).sum())}")
    cols[5].metric(
        "Effective N",
        f"{1.0 / herfindahl:.1f}" if herfindahl > 0 else "—",
        help="1 / Herfindahl index — the diversification-equivalent number of equal positions.",
    )

    conc = st.columns(3)
    conc[0].metric("Top-5 concentration", percent(top5), help="Share of gross book in the 5 largest absolute weights.")
    conc[1].metric("Top-10 concentration", percent(top10))
    conc[2].metric(
        "Avg one-way turnover",
        percent(float(turnover.mean() / 2.0)) if len(turnover) else "—",
        help="Average half-turnover from weights_history changes.",
    )

    st.subheader("Long / short exposure tape")
    render_figure(charts.long_short_exposure_chart(frame))

    st.subheader("Current long / short targets")
    longs = latest[latest > 0].sort_values(ascending=False).head(15)
    shorts = latest[latest < 0].sort_values(ascending=True).head(15)
    extremes = pd.concat([shorts, longs])
    if not extremes.empty:
        render_figure(
            charts.signed_bar_chart(
                extremes,
                title="Top long and short target weights",
                xlabel="Portfolio weight",
            )
        )

    top_positions = latest[sorted_abs.head(30).index].rename("weight")
    display = pd.DataFrame({
        "side": top_positions.map(lambda value: "LONG" if value > 0 else "SHORT" if value < 0 else "FLAT"),
        "weight": top_positions,
        "abs_weight": top_positions.abs(),
    })
    st.dataframe(
        display.style.format({"weight": "{:.2%}", "abs_weight": "{:.2%}"}).background_gradient(
            subset=["weight"], cmap="RdYlGn"
        ),
        use_container_width=True,
    )

    st.subheader("Daily turnover")
    st.caption(
        f"Average one-way turnover: **{percent(float(turnover.mean() / 2.0))}**  ·  "
        f"most recent: **{percent(float(turnover.iloc[-1] / 2.0))}**"
    )
    st.line_chart((turnover / 2.0).rename("one_way_turnover"))


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

    perf_tab, risk_tab, calendar_tab, arcana_tab, weights_tab, stack_tab, factor_tab = st.tabs(
        ["📈 Performance", "🛡️ Risk", "🗓️ Temporal heatmaps", "🧠 Arcana", "🟢🔴 Long / short", "🧱 Stack", "🔬 Distribution & IC"]
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
            help="Lookback used for rolling Sharpe, annualized volatility, and hit rate.",
            key="analytics_rolling_window",
        )
        rolling = _rolling_frame(returns, window)
        if not rolling.empty:
            render_figure(charts.rolling_metrics_chart(rolling, ["rolling_sharpe"], title=f"Rolling Sharpe ({window}d)"))
            render_figure(
                charts.rolling_metrics_chart(
                    rolling, ["rolling_vol"], title=f"Rolling Volatility ({window}d, annualized)"
                )
            )
            render_figure(charts.rolling_hit_rate_chart(returns, window=window, title=f"Rolling hit rate ({window}d)"))

        dsr = deflated_sharpe(returns)
        if "error" not in dsr:
            cols = st.columns(4)
            cols[0].metric("Deflated Sharpe prob", dsr["deflated_sharpe_prob"], help="P(true Sharpe > 0) after multiple-testing deflation (Bailey & López de Prado).")
            cols[1].metric("Verdict", dsr["verdict"])
            cols[2].metric("Skew", summary.get("skew", "—"))
            cols[3].metric("Kurtosis", summary.get("kurtosis", "—"))

    with calendar_tab:
        render_figure(charts.monthly_returns_heatmap(returns))
        render_figure(charts.weekday_month_heatmap(returns))
        render_figure(charts.calendar_heatmap(returns))

    with arcana_tab:
        _render_arcana_section(pnl, returns, snapshot)

    with weights_tab:
        _render_weights_section(snapshot["weights_history"])

    with stack_tab:
        render_position_stack(snapshot["weights_history"], key_prefix="analytics_position_stack")

    with factor_tab:
        render_figure(charts.return_distribution_chart(returns))
        ic = snapshot["ic_health"]
        if not ic.empty:
            st.subheader("Factor / sleeve IC health over time")
            render_figure(charts.ic_health_heatmap(ic))
            latest = ic.iloc[-1].sort_values(ascending=False).rename("smoothed_ic")
            strongest = latest.tail(min(8, len(latest)))
            weakest = latest.head(min(8, len(latest)))
            extremes = pd.concat([weakest, strongest]).drop_duplicates()
            render_figure(
                charts.signed_bar_chart(
                    extremes,
                    title="Latest smoothed IC — red / green extremes",
                    xlabel="Smoothed IC",
                )
            )
        tail = summary.get("tail_ratio_95_5")
        if tail is not None:
            st.caption(
                f"Tail ratio (|p95| / p05|): **{tail}** — values > 1 mean fatter right "
                "(gain) tail than left (loss) tail."
            )
