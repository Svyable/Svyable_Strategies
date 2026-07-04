"""Institutional alpha, beta, regime, and chimera observability page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.institutional_observability import (
    candidate_artifacts,
    candidate_frontier_columns,
    enrich_candidate_board,
)
from svyable.streamlit_app import configured_output_root
from svyable.strategy_selection_service import StrategySelectionService


st.set_page_config(
    page_title="Svyable Institutional Alpha Lab",
    page_icon="🏛️",
    layout="wide",
)
st.title("Institutional Alpha Lab")
st.caption(
    "Read-only pitch and PM observability. Metrics are historical engineering "
    "evidence, not promised returns or live performance."
)

settings = TastySettings.from_env(require_credentials=False)
output_root = configured_output_root(settings)
service = StrategySelectionService(output_root)
status = service.frontier_status()
board = enrich_candidate_board(service.latest_board())
regime = service.latest_regime()

if board.empty:
    st.info("Run a fresh candidate evaluation from the Strategy Selector first.")
    if st.button("Enable full default frontier", key="alpha_lab_enable_full_frontier_empty"):
        path = service.save_full_frontier_policy()
        st.success(f"Enabled every default strategy and chimera in `{path}`. Run a fresh evaluation next.")
    st.stop()

eligible = board[board.get("eligible", False) == True]  # noqa: E712
best = (
    eligible.sort_values("utility_bps", ascending=False).iloc[0]
    if not eligible.empty
    else board.iloc[0]
)
latest_regime = regime.ffill().iloc[-1] if not regime.empty else pd.Series(dtype=float)

summary = st.columns(6)
summary[0].metric("Candidates", len(board), help="Rows in the latest candidate board, including hold_current.")
summary[1].metric("Eligible", len(eligible))
summary[2].metric("Best utility", f"{float(best.get('utility_bps', 0.0)):.2f} bps")
summary[3].metric("Best candidate", str(best.get("candidate_id", "—")))
summary[4].metric(
    "Regime multiplier",
    f"{float(latest_regime.get('multiplier', latest_regime.get('throttle', 1.0))):.0%}",
)
summary[5].metric(
    "Market breadth",
    f"{float(latest_regime.get('breadth', float('nan'))):.0%}"
    if pd.notna(latest_regime.get("breadth"))
    else "warming up",
)

coverage = st.columns(4)
coverage[0].metric("Registered strategies", status["registry_strategy_count"])
coverage[1].metric("Default strategies", status["default_strategy_count"])
coverage[2].metric("Policy strategies", status["policy_strategy_count"])
coverage[3].metric(
    "Board coverage",
    f"{status['board_candidate_count']}/{status['expected_candidate_count']}",
    help="Latest board candidates versus the candidates implied by the current policy.",
)
if status["is_incomplete_latest_board"]:
    st.warning(status["explanation"])
    with st.expander("Frontier repair actions"):
        st.caption(
            "The Alpha Lab can only display the most recent candidate-board artifact. "
            "If the registry grew after the policy was saved, enable the full default "
            "frontier and run a fresh evaluation from Strategy Registry & PM Selector."
        )
        st.json({
            "missing_enabled_strategy_ids": status["missing_enabled_strategy_ids"],
            "missing_enabled_blend_ids": status["missing_enabled_blend_ids"],
            "latest_board_dir": status["board_dir"],
        })
        if st.button("Enable full default frontier", key="alpha_lab_enable_full_frontier"):
            path = service.save_full_frontier_policy()
            st.success(f"Saved full-frontier policy to `{path}`. Run a fresh candidate evaluation next.")
else:
    st.caption(status["explanation"])

st.subheader("Candidate frontier")
frontier_columns = candidate_frontier_columns(board)
st.dataframe(
    board[frontier_columns].sort_values("utility_bps", ascending=False),
    use_container_width=True,
    hide_index=True,
)

plot_frame = board.dropna(subset=[column for column in ["beta", "regression_alpha_ann"] if column in board.columns])
if {"beta", "regression_alpha_ann"} <= set(plot_frame.columns) and not plot_frame.empty:
    st.caption("Regression alpha versus market beta; point size reflects absolute utility.")
    plot_frame = plot_frame.copy()
    plot_frame["utility_size"] = plot_frame["utility_bps"].abs().clip(lower=0.25)
    st.scatter_chart(
        plot_frame,
        x="beta",
        y="regression_alpha_ann",
        size="utility_size",
    )

candidate_ids = board["candidate_id"].astype(str).tolist()
default_index = candidate_ids.index(str(best.get("candidate_id"))) if str(best.get("candidate_id")) in candidate_ids else 0
selected_id = st.selectbox("Inspect candidate", candidate_ids, index=default_index)
selected = board.loc[board["candidate_id"].astype(str) == selected_id].iloc[0]
artifacts = candidate_artifacts(selected)

st.subheader("Candidate scorecard")
scorecard = st.columns(6)
scorecard[0].metric("Annual return", f"{float(selected.get('ann_return', 0.0)):.1%}")
scorecard[1].metric("Annual volatility", f"{float(selected.get('ann_vol', 0.0)):.1%}")
scorecard[2].metric("Sharpe", f"{float(selected.get('sharpe', 0.0)):.2f}")
scorecard[3].metric("Beta", f"{float(selected.get('beta', 0.0)):.2f}")
scorecard[4].metric("Regression alpha", f"{float(selected.get('regression_alpha_ann', 0.0)):.1%}")
scorecard[5].metric("Maximum drawdown", f"{float(selected.get('max_dd', 0.0)):.1%}")

capture = st.columns(4)
capture[0].metric("Upside capture", f"{float(selected.get('upside_capture', 0.0)):.2f}x")
capture[1].metric("Downside capture", f"{float(selected.get('downside_capture', 0.0)):.2f}x")
capture[2].metric("Capture spread", f"{float(selected.get('capture_spread', 0.0)):.2f}")
capture[3].metric("Information ratio", f"{float(selected.get('info_ratio', 0.0)):.2f}")

pnl = artifacts["pnl"]
if not pnl.empty and "net_ret" in pnl:
    nav = (1.0 + pnl["net_ret"].fillna(0.0)).cumprod().rename("strategy")
    if "benchmark_ret" in pnl:
        benchmark = (1.0 + pnl["benchmark_ret"].fillna(0.0)).cumprod().rename("benchmark")
        nav = pd.concat([nav, benchmark], axis=1)
    st.subheader("Recent NAV evidence")
    st.line_chart(nav.tail(252))

components = artifacts["components"]
if not components.empty:
    st.subheader("Causal chimera allocation history")
    st.line_chart(components.tail(252))
    st.dataframe(
        components.tail(1).T.rename(columns={components.tail(1).index[-1]: "current_weight"}),
        use_container_width=True,
    )

weights = artifacts["weights"]
if not weights.empty:
    st.subheader("Current target weights")
    column = "weight" if "weight" in weights else weights.columns[0]
    current_weights = weights[[column]].sort_values(column, ascending=False)
    st.dataframe(current_weights, use_container_width=True)
    st.bar_chart(current_weights.head(30))

factor_catalog = artifacts["factors"]
if not factor_catalog.empty:
    st.subheader("Factor inventory")
    factor_summary = factor_catalog.groupby(["sleeve", "stage"]).size().rename("count")
    st.dataframe(factor_summary.to_frame(), use_container_width=True)
    with st.expander("Full factor catalog"):
        st.dataframe(factor_catalog, use_container_width=True)

if not regime.empty:
    st.subheader("Turbulence and beta-efficiency regime")
    columns = [
        column
        for column in [
            "multiplier",
            "throttle",
            "boost",
            "breadth",
            "turb_pct",
            "absorption",
            "panic_signal",
            "regime_risk",
        ]
        if column in regime.columns
    ]
    st.line_chart(regime[columns].tail(252))

with st.expander("Candidate metadata"):
    st.json(artifacts["meta"])
