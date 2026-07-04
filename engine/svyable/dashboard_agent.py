"""Agentic strategy-selection command center for the Streamlit console.

This is the "new and improved" surface for Svyable's agentic setup. It composes:

1. A decision hero panel — what the PM agent proposed, its confidence, and the
   cost-aware edge over simply holding — read from the strategy-selection state.
2. Board visualizations — per-candidate utility / net-alpha rankings and an
   alpha-vs-turnover scatter, so the trade-off the agent optimizes is legible.
3. A cross-candidate equity overlay — every eligible recipe's shadow NAV on one
   axis, the currently-held strategy highlighted.

Then it delegates to the existing :func:`render_strategy_selector` control
surface (policy, chimera blends, evaluation, activation) which was previously
built but never wired into the app.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.dashboard_compare import render_comparison
from svyable.dashboard_data import load_candidate_returns, load_candidate_weights
from svyable.dashboard_stack import render_overlap
from svyable.dashboard_strategy_selector import render_strategy_selector
from svyable.dashboard_ui import render_figure
from svyable.strategy_selection_service import StrategySelectionService


def _render_decision_hero(service: StrategySelectionService, board: pd.DataFrame) -> None:
    state = service.state()
    decision = service.latest_decision() or {}
    pending = service.pending_agent_decision() or {}

    action = state.get("selected_action", "—")
    held = state.get("selected_strategy_id", "not selected")
    badge = {"hold": "🟢 HOLD", "rebalance": "🟡 REBALANCE", "switch": "🔵 SWITCH"}.get(
        str(action).lower(), f"⚪ {action}"
    )

    hold_row = board[board["candidate_id"] == "hold_current"]
    hold_util = float(hold_row.iloc[0]["utility_bps"]) if not hold_row.empty else None

    cols = st.columns(4)
    cols[0].metric("Agent action", badge, help="Latest activated selection action.")
    cols[1].metric("Held strategy", held)
    confidence = pending.get("confidence", decision.get("confidence"))
    cols[2].metric(
        "Confidence",
        f"{float(confidence):.0%}" if confidence is not None else "—",
        help="Agent's stated confidence in the current proposal.",
    )
    cols[3].metric(
        "Hold utility",
        f"{hold_util:.2f} bps" if hold_util is not None else "—",
        help="Cost-aware utility of doing nothing — the bar every switch must clear.",
    )

    reason = pending.get("reason") or decision.get("reason") or state.get("reason")
    if reason:
        if confidence is not None:
            st.progress(min(max(float(confidence), 0.0), 1.0), text="Agent confidence")
        st.markdown(f"> 🤖 **PM agent rationale** — {reason}")
    else:
        st.caption("No agent rationale recorded yet. Run a candidate evaluation to build a board.")


def render_agent(output_root: str | Path) -> None:
    service = StrategySelectionService(output_root)
    board = service.latest_board()

    st.subheader("🤖 Agentic strategy command center")
    st.caption(
        "The agent proposes; a human approves. Every morning the deterministic "
        "evaluation emits an immutable candidate board; the PM agent writes one "
        "cost-aware decision; nothing trades until it is activated below."
    )

    if board.empty:
        st.info(
            "No candidate board yet. Use **Run fresh candidate evaluation** in the "
            "control surface below to build one."
        )
        render_strategy_selector(service)
        return

    _render_decision_hero(service, board)

    board_tab, compare_tab, control_tab = st.tabs(
        ["🎯 Board", "⚖️ Compare strategies", "🛠️ Control surface"]
    )

    with board_tab:
        left, right = st.columns(2)
        with left:
            if "utility_bps" in board.columns:
                render_figure(charts.candidate_ranking_chart(board, "utility_bps", title="Net utility (bps)"))
        with right:
            alpha_col = "net_expected_alpha_bps" if "net_expected_alpha_bps" in board.columns else "expected_alpha_bps"
            if alpha_col in board.columns:
                render_figure(charts.candidate_ranking_chart(board, alpha_col, title="Net expected alpha (bps)"))
        if {"one_way_turnover", "expected_alpha_bps"} <= set(board.columns):
            render_figure(charts.alpha_vs_cost_scatter(board))

    with compare_tab:
        curves = load_candidate_returns(service.output_root, board)
        if len(curves) >= 2:
            common_start = st.checkbox(
                "Align to common start date",
                value=True,
                help="Trim every curve to the latest shared start so the comparison is apples-to-apples.",
            )
            if common_start:
                start = max(series.index[0] for series in curves.values())
                curves = {name: series[series.index >= start] for name, series in curves.items()}
            render_figure(
                charts.multi_equity_chart(
                    curves, highlight=service.state().get("selected_strategy_id")
                )
            )
            try:
                registry = service.registry()
            except Exception:
                registry = None
            render_comparison(curves, registry)
            render_overlap(load_candidate_weights(service.output_root, board))
        else:
            st.caption("No per-candidate return history found yet for the current board.")

    with control_tab:
        render_strategy_selector(service)
