"""Agentic strategy-selection command center for the Streamlit console.

This is the "new and improved" surface for Svyable's agentic setup. It composes:

1. A decision hero panel — what the PM agent proposed, its confidence, and the
   cost-aware edge over simply holding — read from the strategy-selection state.
2. Board visualizations — per-candidate utility / net-alpha rankings and an
   alpha-vs-turnover scatter, so the trade-off the agent optimizes is legible.
3. A daily playbook — PM one-pager style cards for every candidate strategy.
4. A cross-candidate equity overlay — every eligible recipe's shadow NAV on one
   axis, the currently-held strategy highlighted.
5. A Q23-style stress and what-if lab — red-market survival, drawdown recovery,
   monthly candidate heatmaps, and research-only blend experiments.

Then it delegates to the existing :func:`render_strategy_selector` control
surface (policy, chimera blends, evaluation, activation) which was previously
built but never wired into the app.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.dashboard_candidate_analysis import render_candidate_analytics
from svyable.dashboard_compare import render_comparison
from svyable.dashboard_data import load_candidate_returns, load_candidate_weights
from svyable.dashboard_playbook import render_strategy_playbook
from svyable.dashboard_stack import render_overlap
from svyable.dashboard_strategy_selector import render_frontier_coverage, render_strategy_selector
from svyable.dashboard_stress import render_stress_lab
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


def _plotly_available() -> bool:
    try:
        from svyable import dashboard_interactive as interactive
    except Exception:
        return False
    return bool(interactive.available())


def _render_candidate_ranking(board: pd.DataFrame, value_col: str, title: str) -> None:
    if _plotly_available():
        from svyable import dashboard_interactive as interactive
        from svyable.dashboard_ui import render_plotly

        render_plotly(interactive.candidate_ranking(board, value_col, title=title))
    else:
        render_figure(charts.candidate_ranking_chart(board, value_col, title=title))


def _render_alpha_cost_map(board: pd.DataFrame, held_strategy: str | None) -> None:
    if _plotly_available():
        from svyable import dashboard_interactive as interactive
        from svyable.dashboard_ui import render_plotly

        render_plotly(interactive.alpha_cost_map(board, highlight=held_strategy))
    else:
        render_figure(charts.alpha_vs_cost_scatter(board, highlight=held_strategy))


def _render_equity_overlay(curves: dict[str, pd.Series], held_strategy: str | None) -> None:
    if _plotly_available():
        from svyable import dashboard_interactive as interactive
        from svyable.dashboard_ui import render_plotly

        render_plotly(interactive.multi_equity(curves, highlight=held_strategy))
    else:
        render_figure(charts.multi_equity_chart(curves, highlight=held_strategy))


def _render_pm_scorecard(board: pd.DataFrame) -> pd.DataFrame:
    from svyable.strategy_decision_scorecard import (
        best_play,
        build_decision_scorecard,
        decision_reason,
        render_decision_ticket,
    )

    scorecard = build_decision_scorecard(board)
    if scorecard.empty:
        st.info("No candidate scorecard available yet.")
        return scorecard
    top = best_play(scorecard)
    cols = st.columns(4)
    cols[0].metric("Best play", top.get("candidate_id", "—"))
    cols[1].metric("Call", top.get("play_call", "—"))
    cols[2].metric("Edge vs hold", f"{float(top.get('edge_vs_hold_bps', 0.0)):.2f} bps")
    cols[3].metric("Next action", top.get("next_action", "Review board"))
    if str(top.get("play_call")) == "GREENLIGHT":
        st.success("Scorecard says this candidate clears the hold-current hurdle with clean risk flags.")
    elif str(top.get("play_call")) == "REVIEW":
        st.warning("Scorecard says this is reviewable, but the PM should inspect flags before approval.")
    elif str(top.get("play_call")) == "BLOCK":
        st.error("Top candidate is blocked. Resolve blockers or hold current.")
    else:
        st.info("Scorecard favors holding current unless the PM has additional evidence.")

    st.markdown("#### Draft guarded-decision rationale")
    st.text_area(
        "Copy this into the guarded decision writer after review",
        value=decision_reason(top),
        height=120,
        key="agent_lab_scorecard_decision_reason",
    )

    ticket = render_decision_ticket(scorecard)
    csv_bytes = scorecard.to_csv(index=False).encode("utf-8")
    left, right = st.columns(2)
    left.download_button(
        "Download decision ticket",
        data=ticket,
        file_name="svyable_pm_decision_ticket.md",
        mime="text/markdown",
    )
    right.download_button(
        "Download scorecard CSV",
        data=csv_bytes,
        file_name="svyable_pm_scorecard.csv",
        mime="text/csv",
    )

    table_cols = [
        "candidate_id",
        "play_call",
        "edge_vs_hold_bps",
        "conviction_score",
        "risk_points",
        "utility_bps",
        "one_way_turnover",
        "current_overlap",
        "recent_max_drawdown",
        "risk_flags",
    ]
    st.dataframe(
        scorecard[[col for col in table_cols if col in scorecard.columns]],
        use_container_width=True,
        hide_index=True,
    )
    if _plotly_available():
        from svyable import dashboard_interactive as interactive
        from svyable.dashboard_ui import render_plotly

        render_plotly(interactive.decision_scorecard_map(scorecard))
    return scorecard


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

    board_tab, playbook_tab, compare_tab, stress_tab, control_tab = st.tabs(
        ["🎯 Board", "📖 Playbook", "⚖️ Compare strategies", "🧪 Stress / what-if lab", "🛠️ Control surface"]
    )

    curves = load_candidate_returns(service.output_root, board)
    registry = None
    try:
        registry = service.registry()
    except Exception:
        pass

    held_strategy = service.state().get("selected_strategy_id")

    with board_tab:
        render_frontier_coverage(service)
        st.markdown("### PM decision scorecard")
        _render_pm_scorecard(board)
        st.markdown("### Candidate rankings")
        left, right = st.columns(2)
        with left:
            if "utility_bps" in board.columns:
                _render_candidate_ranking(board, "utility_bps", "Net utility (bps)")
        with right:
            alpha_col = "net_expected_alpha_bps" if "net_expected_alpha_bps" in board.columns else "expected_alpha_bps"
            if alpha_col in board.columns:
                _render_candidate_ranking(board, alpha_col, "Net expected alpha (bps)")
        if {"one_way_turnover", "expected_alpha_bps"} <= set(board.columns):
            _render_alpha_cost_map(board, held_strategy)
            st.caption(
                "Every candidate on the board is plotted — colored by family, sized by "
                "cost-aware utility, hollow when ineligible, gold-ringed when held. "
                "Use hover, zoom, and legend filtering to inspect the exact alpha/cost trade-off."
            )

    with playbook_tab:
        render_strategy_playbook(service, board)

    with compare_tab:
        if len(curves) >= 2:
            common_start = st.checkbox(
                "Align to common start date",
                value=True,
                help="Trim every curve to the latest shared start so the comparison is apples-to-apples.",
            )
            display_curves = curves
            if common_start:
                start = max(series.index[0] for series in curves.values())
                display_curves = {name: series[series.index >= start] for name, series in curves.items()}
            _render_equity_overlay(display_curves, service.state().get("selected_strategy_id"))
            render_comparison(display_curves, registry)
            render_overlap(load_candidate_weights(service.output_root, board))
        else:
            st.caption("No per-candidate return history found yet for the current board.")

        st.divider()
        render_candidate_analytics(service, board, registry, default_candidate=held_strategy)

    with stress_tab:
        if len(curves) >= 2:
            render_stress_lab(curves, board=board, registry=registry)
        else:
            st.caption("No per-candidate return history found yet for the current board.")

    with control_tab:
        render_strategy_selector(service)
