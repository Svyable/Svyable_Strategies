"""Live Tastytrade position analytics for the broker view.

Brings Q23-style portfolio insight to the *actual* broker book: exposure,
concentration, per-name unrealized P&L, winners/losers, and — the piece that
ties the two halves of Svyable together — a target-vs-actual drift view that
overlays the live Tastytrade holdings against the strategy's target weights.

The compute helpers are pure (DataFrame in, DataFrame/dict out) so they are
unit-tested without a broker session; the ``render_*`` functions are the thin
Streamlit layer.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.dashboard_ui import money, percent, render_figure

_EPS = 1e-12


def position_pnl(positions: pd.DataFrame) -> pd.DataFrame:
    """Add unrealized P&L, book weight, and return columns to a positions frame."""
    if positions.empty:
        return positions
    frame = positions.copy()
    for col in ("quantity", "mark", "market_value", "average_open_price", "realized_today"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

    cost = frame["average_open_price"].fillna(0.0) * frame["quantity"].fillna(0.0)
    frame["unrealized_pl"] = frame["market_value"].fillna(0.0) - cost
    frame["unrealized_pct"] = frame["unrealized_pl"] / (cost.abs() + _EPS)
    gross = float(frame["market_value"].abs().sum())
    frame["book_weight"] = frame["market_value"].fillna(0.0) / (gross + _EPS)
    return frame


def position_analytics(positions: pd.DataFrame) -> dict[str, float]:
    """Portfolio-level exposure, concentration, and P&L rollup for the live book."""
    if positions.empty:
        return {}
    frame = position_pnl(positions)
    market_value = frame["market_value"].fillna(0.0)
    longs = market_value[market_value > 0]
    shorts = market_value[market_value < 0]
    gross = float(market_value.abs().sum())
    abs_sorted = market_value.abs().sort_values(ascending=False)
    herfindahl = float(((market_value / (gross + _EPS)) ** 2).sum())

    return {
        "positions": int((market_value.abs() > _EPS).sum()),
        "gross_exposure": gross,
        "net_exposure": float(market_value.sum()),
        "long_exposure": float(longs.sum()),
        "short_exposure": float(abs(shorts.sum())),
        "largest_weight": float(abs_sorted.iloc[0] / (gross + _EPS)) if len(abs_sorted) else 0.0,
        "top5_concentration": float(abs_sorted.head(5).sum() / (gross + _EPS)) if gross else 0.0,
        "effective_n": float(1.0 / herfindahl) if herfindahl > _EPS else 0.0,
        "unrealized_pl": float(frame["unrealized_pl"].sum()),
        "realized_today": float(frame.get("realized_today", pd.Series(dtype=float)).fillna(0.0).sum()),
    }


def target_vs_actual(
    positions: pd.DataFrame, targets: pd.Series, net_liq: float | None = None
) -> pd.DataFrame:
    """Drift table: strategy target weight vs. live book weight, per symbol.

    When ``net_liq`` is supplied the actual weight is ``market_value / net_liq`` —
    a true fraction-of-NAV weight that lines up with strategy targets (which are
    also fractions of NAV, so a cash-heavy book compares honestly). Without it,
    weights fall back to gross-normalization. ``drift`` is ``actual - target``
    (positive = the book is over-weight the name relative to the strategy).
    """
    frame = position_pnl(positions)
    if not frame.empty and "symbol" in frame.columns:
        if net_liq and net_liq > _EPS:
            actual = frame.set_index("symbol")["market_value"].fillna(0.0) / net_liq
        else:
            actual = frame.set_index("symbol")["book_weight"]
    else:
        actual = pd.Series(dtype=float)
    actual.index = actual.index.astype(str)
    target = targets.copy()
    target.index = target.index.astype(str)

    symbols = sorted(set(actual.index) | set(target.index))
    table = pd.DataFrame(index=symbols)
    table["target_weight"] = target.reindex(symbols).fillna(0.0)
    table["actual_weight"] = actual.reindex(symbols).fillna(0.0)
    table["drift"] = table["actual_weight"] - table["target_weight"]
    table.index.name = "symbol"
    return table.sort_values("drift", key=lambda s: s.abs(), ascending=False)


def render_position_analytics(positions: pd.DataFrame) -> None:
    stats = position_analytics(positions)
    if not stats:
        st.info("No positions.")
        return

    row1 = st.columns(5)
    row1[0].metric("Positions", stats["positions"])
    row1[1].metric("Gross exposure", money(stats["gross_exposure"]))
    row1[2].metric("Net exposure", money(stats["net_exposure"]))
    row1[3].metric("Largest position", percent(stats["largest_weight"]), help="Share of gross book in the single biggest name.")
    row1[4].metric("Effective N", f"{stats['effective_n']:.1f}", help="1 / Herfindahl — diversification-equivalent position count.")

    row2 = st.columns(4)
    row2[0].metric("Long exposure", money(stats["long_exposure"]))
    row2[1].metric("Short exposure", money(stats["short_exposure"]))
    unreal = stats["unrealized_pl"]
    row2[2].metric("Unrealized P&L", money(unreal), delta=f"{unreal:+,.0f}", help="Mark-to-market gain/loss vs. average open price.")
    row2[3].metric("Realized today", money(stats["realized_today"]))

    frame = position_pnl(positions)
    detail = frame.copy()
    if "symbol" in detail.columns:
        detail = detail.set_index("symbol")
    display_cols = [c for c in ["quantity", "mark", "average_open_price", "market_value", "book_weight", "unrealized_pl", "unrealized_pct", "realized_today"] if c in detail.columns]
    st.subheader("Positions")
    st.dataframe(
        detail[display_cols].style.background_gradient(
            subset=[c for c in ["unrealized_pl", "unrealized_pct"] if c in display_cols], cmap="RdYlGn"
        ),
        use_container_width=True,
    )

    ranked = frame.dropna(subset=["unrealized_pl"])
    if not ranked.empty and "symbol" in ranked.columns:
        pnl = ranked.set_index("symbol")["unrealized_pl"]
        pnl = pd.concat([pnl.sort_values().head(10), pnl.sort_values().tail(10)]).drop_duplicates()
        if not pnl.empty:
            st.subheader("Winners & losers (unrealized)")
            render_figure(charts.signed_bar_chart(pnl, xlabel="Unrealized P&L ($)"))


def render_target_vs_actual(
    positions: pd.DataFrame, targets: pd.Series, net_liq: float | None = None
) -> None:
    st.subheader("Target vs. actual book")
    st.caption(
        "Strategy target weights overlaid on the live Tastytrade holdings. Weights "
        "are fractions of net liquidation value; drift is actual minus target — the "
        "exact gaps a rebalance closes."
    )
    table = target_vs_actual(positions, targets, net_liq)
    if table.empty:
        st.info("No overlap between the live book and strategy targets yet.")
        return

    tracking_error = float(table["drift"].abs().sum())
    held_off_target = int(((table["actual_weight"] > _EPS) & (table["target_weight"] <= _EPS)).sum())
    missing = int(((table["target_weight"] > _EPS) & (table["actual_weight"] <= _EPS)).sum())
    cols = st.columns(3)
    cols[0].metric("Sum |drift|", percent(tracking_error), help="Total one-way distance between book and target.")
    cols[1].metric("Held, not targeted", held_off_target)
    cols[2].metric("Targeted, not held", missing)

    render_figure(charts.position_drift_chart(table))
    display = table.copy()
    for col in ("target_weight", "actual_weight", "drift"):
        display[col] = display[col].map(percent)
    st.dataframe(display, use_container_width=True)
