"""Q23-style stress, regime, and what-if lab for candidate portfolios.

This view keeps the PM selector honest by asking: which candidates survive red
markets, which recover fastest, and what happens if the PM blends recipes before
promoting a chimera to the registry. It is read-only research over the existing
candidate shadow-NAV artifacts; it never writes weights or activation state.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable import dashboard_interactive as interactive
from svyable.dashboard_compare import aligned_returns, metrics_matrix
from svyable.dashboard_ui import percent, render_figure, render_plotly
from svyable.metrics import perf_summary

ANN = 252.0
_PCT_COLS = [
    "ann_return",
    "ann_vol",
    "hit_rate",
    "worst_day",
    "cvar_5",
    "max_dd",
    "stress_mean",
    "stress_hit_rate",
    "calm_mean",
    "red_green_spread",
]


def _drawdown(returns: pd.Series) -> pd.Series:
    nav = (1.0 + returns.fillna(0.0)).cumprod()
    return nav / nav.cummax() - 1.0


def _max_recovery_days(returns: pd.Series) -> int | None:
    dd = _drawdown(returns.dropna())
    if dd.empty:
        return None
    underwater = dd < -1e-12
    if not underwater.any():
        return 0
    longest = 0
    current = 0
    for flag in underwater.astype(bool):
        if flag:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _cvar(values: pd.Series, q: float = 0.05) -> float:
    clean = values.dropna().astype(float)
    if clean.empty:
        return float("nan")
    threshold = clean.quantile(q)
    tail = clean[clean <= threshold]
    return float(tail.mean()) if len(tail) else float(threshold)


def _stress_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    proxy = frame.mean(axis=1)
    stress_cut = proxy.quantile(0.10)
    calm_cut = proxy.quantile(0.90)
    stress_days = proxy <= stress_cut
    calm_days = proxy >= calm_cut

    rows = []
    for name in frame.columns:
        series = frame[name].dropna().astype(float)
        if series.empty:
            continue
        dd = _drawdown(series)
        rows.append(
            {
                "candidate": name,
                "ann_return": float((1.0 + series).prod() ** (ANN / len(series)) - 1.0),
                "ann_vol": float(series.std() * math.sqrt(ANN)),
                "sharpe": float(series.mean() / (series.std() + 1e-12) * math.sqrt(ANN)),
                "hit_rate": float((series > 0).mean()),
                "worst_day": float(series.min()),
                "cvar_5": _cvar(series, 0.05),
                "max_dd": float(dd.min()) if len(dd) else float("nan"),
                "max_underwater_days": _max_recovery_days(series),
                "stress_mean": float(frame.loc[stress_days, name].mean()) if stress_days.any() else float("nan"),
                "stress_hit_rate": float((frame.loc[stress_days, name] > 0).mean()) if stress_days.any() else float("nan"),
                "calm_mean": float(frame.loc[calm_days, name].mean()) if calm_days.any() else float("nan"),
            }
        )
    result = pd.DataFrame(rows).set_index("candidate") if rows else pd.DataFrame()
    if not result.empty:
        result["red_green_spread"] = result["calm_mean"] - result["stress_mean"]
        result = result.sort_values(["stress_mean", "max_dd"], ascending=False)
    return result


def _stress_styler(frame: pd.DataFrame):
    formatters = {col: "{:.2%}" for col in _PCT_COLS if col in frame.columns}
    if "sharpe" in frame.columns:
        formatters["sharpe"] = "{:.2f}"
    if "max_underwater_days" in frame.columns:
        formatters["max_underwater_days"] = "{:.0f}"
    return frame.style.format(formatters, na_rep="—").background_gradient(
        subset=[
            col
            for col in ["stress_mean", "stress_hit_rate", "max_dd", "cvar_5", "calm_mean"]
            if col in frame.columns
        ],
        cmap="RdYlGn",
    )


def _blend_returns(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    active = {name: weight for name, weight in weights.items() if weight > 0 and name in frame.columns}
    total = sum(active.values())
    if not active or total <= 0:
        return pd.Series(dtype=float)
    normalized = {name: weight / total for name, weight in active.items()}
    result = sum(frame[name].fillna(0.0) * weight for name, weight in normalized.items())
    result.name = "what_if_blend"
    return result


def _monthly_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    monthly = (1.0 + frame).resample("ME").prod() - 1.0
    if monthly.empty:
        return monthly
    monthly.index = monthly.index.strftime("%Y-%m")
    return monthly.tail(18).T


def _render_signed_bar(series: pd.Series, *, title: str, xlabel: str) -> None:
    if interactive.available():
        render_plotly(interactive.signed_bar(series, title=title, xlabel=xlabel))
    else:
        render_figure(charts.signed_bar_chart(series.sort_values(), title=title, xlabel=xlabel))


def render_stress_lab(
    curves: dict[str, pd.Series],
    board: pd.DataFrame | None = None,
    registry: pd.DataFrame | None = None,
) -> None:
    """Render a PM-facing stress and exploratory blend lab for candidate returns."""
    frame = aligned_returns(curves)
    if frame.shape[1] < 2:
        st.info("Need at least two candidate return histories for the stress lab.")
        return

    st.caption(
        "Q23-style PM lab: red-market conditional returns, drawdown recovery, "
        "candidate monthly heatmaps, and a no-write what-if blend sandbox."
    )

    if board is not None and not board.empty:
        candidate_meta = board.set_index("candidate_id", drop=False)
        eligible_count = int(board.get("eligible", pd.Series(dtype=bool)).astype(bool).sum()) if "eligible" in board else 0
        cols = st.columns(4)
        cols[0].metric("Candidate histories", frame.shape[1])
        cols[1].metric("Eligible board rows", eligible_count)
        if "utility_bps" in candidate_meta.columns:
            best = candidate_meta["utility_bps"].astype(float).idxmax()
            cols[2].metric("Top utility", str(best))
        if "one_way_turnover" in candidate_meta.columns:
            avg_turnover = float(candidate_meta["one_way_turnover"].astype(float).mean())
            cols[3].metric("Avg board turnover", percent(avg_turnover))

    stress = _stress_matrix(frame)
    if not stress.empty:
        st.subheader("Red / green stress table")
        st.caption(
            "Stress days are the worst 10% of the cross-candidate return proxy. Calm days are the best 10%."
        )
        try:
            st.dataframe(_stress_styler(stress), use_container_width=True)
        except Exception:
            st.dataframe(stress, use_container_width=True)

        left, right = st.columns(2)
        with left:
            _render_signed_bar(
                stress["stress_mean"].sort_values(),
                title="Average return on red-market days",
                xlabel="Daily return",
            )
        with right:
            _render_signed_bar(
                stress["max_dd"].sort_values(),
                title="Maximum drawdown by candidate",
                xlabel="Drawdown",
            )

    st.subheader("Drawdown tape")
    drawdowns = pd.concat({name: _drawdown(frame[name]) for name in frame.columns}, axis=1)
    if interactive.available():
        render_plotly(interactive.drawdown_tape(drawdowns.tail(504)))
    else:
        st.line_chart(drawdowns.tail(504))

    st.subheader("Monthly candidate heatmap")
    monthly = _monthly_matrix(frame)
    if monthly.empty:
        st.caption("No monthly candidate matrix yet.")
    elif interactive.available():
        render_plotly(interactive.matrix_heatmap(monthly, title="Monthly candidate returns", z_format=".1%"))
    else:
        st.dataframe(
            monthly.style.format("{:.1%}").background_gradient(cmap="RdYlGn", axis=None),
            use_container_width=True,
        )

    st.subheader("What-if blend sandbox")
    st.caption(
        "Research-only blend math over shadow returns. This does not create a chimera, policy, or Tastytrade target."
    )
    ranked = metrics_matrix({name: frame[name] for name in frame.columns}, registry)
    defaults = list(ranked.head(min(4, len(ranked))).index) if not ranked.empty else list(frame.columns[:4])
    picks = st.multiselect("Blend candidates", sorted(frame.columns), default=defaults, max_selections=6)
    if not picks:
        st.info("Select at least one candidate to build a what-if blend.")
        return

    weights: dict[str, float] = {}
    weight_cols = st.columns(len(picks))
    for i, name in enumerate(picks):
        weights[name] = weight_cols[i].number_input(
            f"{name} weight",
            min_value=0.0,
            max_value=1.0,
            value=round(1.0 / len(picks), 2),
            step=0.05,
            key=f"stress_lab_blend_weight_{name}",
        )
    blend = _blend_returns(frame, weights)
    if blend.empty:
        st.info("Set at least one positive blend weight.")
        return

    blend_summary = perf_summary(blend)
    cols = st.columns(5)
    cols[0].metric("Blend ann. return", percent(blend_summary.get("ann_return")))
    cols[1].metric("Blend ann. vol", percent(blend_summary.get("ann_vol")))
    cols[2].metric("Blend Sharpe", blend_summary.get("sharpe", "—"))
    cols[3].metric("Blend max DD", percent(blend_summary.get("max_dd")))
    cols[4].metric("Blend win rate", percent(blend_summary.get("win_rate")))

    overlay = {name: frame[name] for name in picks}
    overlay["what_if_blend"] = blend
    if interactive.available():
        render_plotly(interactive.multi_equity(overlay, highlight="what_if_blend", title="What-if blend vs components"))
        render_plotly(interactive.drawdown_tape(pd.DataFrame({"what_if_blend": _drawdown(blend)}), title="What-if blend drawdown"))
    else:
        render_figure(charts.multi_equity_chart(overlay, highlight="what_if_blend", title="What-if blend vs components"))
        render_figure(charts.drawdown_chart(blend, title="What-if blend drawdown"))
