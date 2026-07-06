"""Position-stack views — the historical weights-evolution side of the book.

Ports the signature ideas from the Q23 ``_position_stack`` page onto Svyable's
``weights_history.csv``: how the portfolio's names and cash have evolved through
time, how consistently each name is held, and — across candidate strategies —
how much their books actually overlap (the position-level analog of return
correlation, which decides whether a chimera blend truly diversifies).

Compute helpers are pure; ``render_*`` is the thin Streamlit layer.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable import dashboard_interactive as interactive
from svyable.dashboard_compare import average_pairwise_correlation
from svyable.dashboard_data import numeric_timeseries
from svyable.dashboard_ui import percent, render_figure, render_plotly

_EPS = 1e-9


def weights_matrix(weights_history: pd.DataFrame) -> pd.DataFrame:
    """Clean date-indexed numeric weight matrix (date × asset)."""
    return numeric_timeseries(weights_history)


def top_names_matrix(matrix: pd.DataFrame, top_n: int = 40, tail_days: int = 252) -> pd.DataFrame:
    """Trim to the ``top_n`` names by peak absolute weight over the last ``tail_days``."""
    if matrix.empty:
        return matrix
    recent = matrix.tail(tail_days)
    ranked = recent.abs().max().sort_values(ascending=False)
    keep = ranked.head(top_n).index
    return recent[keep]


def participation_frequency(matrix: pd.DataFrame, tail_days: int = 252) -> pd.Series:
    """Share of recent days each name carried a non-trivial weight."""
    if matrix.empty:
        return pd.Series(dtype=float)
    recent = matrix.tail(tail_days)
    freq = (recent.abs() > _EPS).mean().sort_values(ascending=False)
    freq.name = "participation"
    return freq[freq > 0]


def cash_exposure(matrix: pd.DataFrame) -> pd.DataFrame:
    """Gross invested vs. cash weight per date (long-only book: cash = 1 - gross)."""
    if matrix.empty:
        return pd.DataFrame()
    gross = matrix.abs().sum(axis=1).clip(upper=1.0)
    return pd.DataFrame({"invested": gross, "cash": (1.0 - gross).clip(lower=0.0)})


def jaccard_overlap(weights_a: pd.Series, weights_b: pd.Series) -> float:
    """Jaccard similarity of the held (non-zero) names in two books."""
    held_a = set(weights_a.index[weights_a.abs() > 1e-12])
    held_b = set(weights_b.index[weights_b.abs() > 1e-12])
    union = held_a | held_b
    if not union:
        return 0.0
    return len(held_a & held_b) / len(union)


def overlap_matrix(latest_weights: dict[str, pd.Series]) -> pd.DataFrame:
    """Pairwise Jaccard name-overlap across strategies' latest books."""
    names = [n for n, w in latest_weights.items() if w is not None and not w.empty]
    if len(names) < 2:
        return pd.DataFrame()
    table = pd.DataFrame(index=names, columns=names, dtype=float)
    for i, a in enumerate(names):
        for b in names[i:]:
            value = jaccard_overlap(latest_weights[a], latest_weights[b])
            table.loc[a, b] = value
            table.loc[b, a] = value
    return table.astype(float)


def render_position_stack(weights_history: pd.DataFrame) -> None:
    matrix = weights_matrix(weights_history)
    if matrix.empty:
        st.info("No weights history yet. Run `svyable daily` to populate `weights_history.csv`.")
        return

    st.caption(
        "How the book has evolved: each row is a name, each column a day, colour is "
        "the target weight. Consistent green bands are durable convictions; flickering "
        "rows are names the model trades in and out of."
    )
    controls = st.columns(2)
    top_n = controls[0].slider("Names to show", 10, 80, 40, step=5)
    tail_days = controls[1].slider("Lookback (days)", 60, min(756, len(matrix)), min(252, len(matrix)), step=21)

    trimmed = top_names_matrix(matrix, top_n=top_n, tail_days=tail_days)
    if interactive.available():
        # Transpose so the Plotly y-axis matches the PM mental model: rows are names,
        # columns are dates, and hover reveals the exact historical target weight.
        render_plotly(interactive.matrix_heatmap(trimmed.T, title="Position stack", z_format=".2%"))
    else:
        render_figure(charts.position_heatmap(trimmed))

    left, right = st.columns(2)
    with left:
        st.subheader("Holding consistency")
        st.caption("Share of the lookback each name was held — durability of conviction.")
        freq = participation_frequency(matrix, tail_days=tail_days).head(top_n)
        if interactive.available():
            render_plotly(interactive.signed_bar(freq.sort_values(), title="Holding consistency", xlabel="Share of lookback held"))
        else:
            st.bar_chart(freq)
    with right:
        st.subheader("Invested vs. cash")
        cash = cash_exposure(matrix).tail(tail_days)
        st.caption(
            f"Current invested: **{percent(float(cash['invested'].iloc[-1]))}** · "
            f"cash: **{percent(float(cash['cash'].iloc[-1]))}**"
        )
        st.area_chart(cash)


def render_overlap(latest_weights: dict[str, pd.Series]) -> None:
    table = overlap_matrix(latest_weights)
    if table.empty:
        st.caption("Need at least two candidate books to measure position overlap.")
        return
    st.subheader("Position overlap (name-level)")
    st.caption(
        "Jaccard similarity of held names across candidate books — the position-level "
        "companion to return correlation. Low overlap plus low return correlation is "
        "what makes a chimera blend genuinely diversifying."
    )
    avg = average_pairwise_correlation(table)
    st.metric("Average pairwise overlap", f"{avg:.2f}")
    if interactive.available():
        render_plotly(interactive.matrix_heatmap(table, title="Candidate position-overlap heatmap", z_format=".2f", colorscale="RdYlGn_r"))
    else:
        try:
            st.dataframe(
                table.style.background_gradient(cmap="RdYlGn_r", vmin=0.0, vmax=1.0).format("{:.2f}"),
                use_container_width=True,
            )
        except Exception:
            st.dataframe(table.round(2), use_container_width=True)
