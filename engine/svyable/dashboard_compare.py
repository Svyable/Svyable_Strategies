"""Strategy comparison toolkit — the PM's cross-strategy insight surface.

Given a set of candidate return series (loaded from each strategy's shadow-NAV
``pnl_diag``), this builds the artifacts a PM or the selection agent needs to
reason across strategies rather than one at a time:

* a **metrics matrix** — every strategy scored on the same institutional ruler
  (:func:`svyable.metrics.perf_summary`), enriched with registry metadata;
* a **correlation matrix** on aligned returns — the diversification map that
  decides which chimera blends are worth building;
* **relative performance** — head-to-head cumulative outperformance;
* **rolling correlation** — is a pair's diversification stable or fair-weather.

The compute helpers are pure so they can be unit-tested and, in principle, fed
straight to the agent's prompt as structured context.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.dashboard_ui import render_figure
from svyable.metrics import perf_summary

_METRIC_ORDER = [
    "ann_return",
    "ann_vol",
    "sharpe",
    "sortino",
    "calmar",
    "max_dd",
    "win_rate",
    "skew",
    "tail_ratio_95_5",
    "days",
]


def aligned_returns(curves: dict[str, pd.Series]) -> pd.DataFrame:
    """Inner-join candidate return series onto a shared calendar."""
    usable = {name: series for name, series in curves.items() if series is not None and not series.empty}
    if len(usable) < 1:
        return pd.DataFrame()
    frame = pd.concat(usable, axis=1, join="inner")
    frame.columns = list(usable.keys())
    return frame.dropna(how="all")


def metrics_matrix(
    curves: dict[str, pd.Series],
    registry: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per strategy scored on the shared institutional metric set.

    ``registry`` (indexed by strategy_id) optionally contributes ``family`` and
    ``regime_profile`` columns for context.
    """
    rows: dict[str, dict] = {}
    for name, series in curves.items():
        if series is None or series.empty:
            continue
        summary = perf_summary(series.dropna())
        if "error" in summary:
            continue
        row = {key: summary.get(key) for key in _METRIC_ORDER}
        if registry is not None and name in registry.index:
            for col in ("family", "regime_profile"):
                if col in registry.columns:
                    row[col] = registry.loc[name, col]
        rows[name] = row
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame.from_dict(rows, orient="index")
    frame.index.name = "strategy"
    return frame.sort_values("sharpe", ascending=False)


def correlation_matrix(curves: dict[str, pd.Series]) -> pd.DataFrame:
    frame = aligned_returns(curves)
    if frame.shape[1] < 2:
        return pd.DataFrame()
    return frame.corr()


def average_pairwise_correlation(corr: pd.DataFrame) -> float:
    """Mean of the off-diagonal correlations — the board's overall redundancy."""
    n = len(corr)
    if n < 2:
        return float("nan")
    off_diagonal = corr.values.sum() - float(corr.values.trace())
    return off_diagonal / (n * n - n)


def relative_performance(base: pd.Series, other: pd.Series) -> pd.Series:
    """Cumulative outperformance of ``base`` over ``other`` on their shared calendar.

    Positive and rising means ``base`` is pulling ahead.
    """
    joined = pd.concat([base.rename("a"), other.rename("b")], axis=1, join="inner").dropna()
    if joined.empty:
        return pd.Series(dtype=float)
    spread = (1.0 + joined["a"]).cumprod() / (1.0 + joined["b"]).cumprod() - 1.0
    spread.name = "relative"
    return spread


def rolling_correlation(base: pd.Series, other: pd.Series, window: int = 63) -> pd.Series:
    joined = pd.concat([base.rename("a"), other.rename("b")], axis=1, join="inner").dropna()
    if len(joined) <= window:
        return pd.Series(dtype=float)
    corr = joined["a"].rolling(window).corr(joined["b"])
    corr.name = f"rolling_corr_{window}"
    return corr.dropna()


def _format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    pct_cols = [c for c in ["ann_return", "ann_vol", "max_dd", "win_rate"] if c in display.columns]
    for col in pct_cols:
        display[col] = display[col].map(lambda v: f"{v:.1%}" if pd.notna(v) else "—")
    for col in [c for c in ["sharpe", "sortino", "calmar", "skew", "tail_ratio_95_5"] if c in display.columns]:
        display[col] = display[col].map(lambda v: f"{v:.2f}" if pd.notna(v) else "—")
    return display


def render_comparison(curves: dict[str, pd.Series], registry: pd.DataFrame | None = None) -> None:
    usable = {name: series for name, series in curves.items() if series is not None and not series.empty}
    if len(usable) < 2:
        st.info("Need at least two candidate return histories to compare. Run a candidate evaluation.")
        return

    st.caption(
        "Every candidate on the same ruler. The correlation map decides which "
        "chimera blends actually diversify; the risk/return map shows where each "
        "recipe sits before costs."
    )

    matrix = metrics_matrix(usable, registry)
    if not matrix.empty:
        st.subheader("Metrics matrix")
        gradient_cols = [c for c in ["sharpe", "sortino", "calmar", "ann_return", "win_rate"] if c in matrix.columns]
        numeric = matrix.drop(columns=[c for c in ["family", "regime_profile"] if c in matrix.columns], errors="ignore")
        styled = _format_metrics(matrix)
        try:
            st.dataframe(
                styled.style.background_gradient(subset=[c for c in gradient_cols if c in styled.columns], cmap="RdYlGn"),
                use_container_width=True,
            )
        except Exception:
            st.dataframe(styled, use_container_width=True)

        if {"ann_vol", "ann_return"} <= set(numeric.columns):
            render_figure(charts.risk_return_scatter(numeric))

    corr = correlation_matrix(usable)
    if not corr.empty:
        st.subheader("Return correlation")
        render_figure(charts.correlation_heatmap(corr))
        avg_corr = average_pairwise_correlation(corr)
        st.caption(
            f"Average pairwise correlation: **{avg_corr:.2f}** — lower means more "
            "diversification on the board."
        )

    st.subheader("Head-to-head")
    names = sorted(usable.keys())
    cols = st.columns(2)
    base_name = cols[0].selectbox("Strategy A", names, index=0)
    other_default = 1 if len(names) > 1 else 0
    other_name = cols[1].selectbox("Strategy B", names, index=other_default)
    if base_name != other_name:
        overlay = {base_name: usable[base_name], other_name: usable[other_name]}
        render_figure(charts.multi_equity_chart(overlay, highlight=base_name, title=f"{base_name} vs {other_name}"))

        spread = relative_performance(usable[base_name], usable[other_name])
        if not spread.empty:
            st.markdown(f"**Relative performance** — {base_name} minus {other_name} (positive = A ahead)")
            st.line_chart(spread)

        window = st.slider("Rolling correlation window", 21, 252, 63, step=7)
        roll = rolling_correlation(usable[base_name], usable[other_name], window)
        if not roll.empty:
            st.markdown("**Rolling correlation** — is their diversification stable?")
            st.line_chart(roll)
    else:
        st.caption("Pick two different strategies to see the head-to-head.")
