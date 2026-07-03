"""Streamlit PM control surface for registered strategy selection."""

from __future__ import annotations

import streamlit as st

from svyable.strategy_selector import SelectionPolicy
from svyable.strategy_selection_service import StrategySelectionService


def render_strategy_selector(service: StrategySelectionService) -> None:
    snapshot = service.snapshot()
    registry = snapshot["registry"]
    policy = service.policy()
    board = snapshot["board"]
    state = snapshot["state"]

    st.caption(
        "Strategies are complete registered recipes. The PM or agent selects a "
        "candidate portfolio; neither the GUI nor the agent edits weights directly."
    )

    cols = st.columns(5)
    cols[0].metric("Current strategy", state.get("selected_strategy_id", "not selected"))
    cols[1].metric("Last action", state.get("selected_action", "—"))
    cols[2].metric("Selection source", state.get("source", "—"))
    cols[3].metric("Position source", state.get("current_position_source", "—"))
    cols[4].metric("Candidate hash", state.get("candidate_set_hash", "—"))

    st.subheader("Strategy registry")
    st.dataframe(registry, use_container_width=True)

    st.subheader("Selection policy")
    mode = st.radio(
        "Mode",
        ["deterministic", "agent", "manual"],
        index=["deterministic", "agent", "manual"].index(policy.mode),
        horizontal=True,
        help=(
            "Deterministic ranks and activates immediately; agent emits a board and "
            "waits for a validated decision; manual selects one registered strategy."
        ),
    )
    strategy_options = list(registry.index)
    enabled = st.multiselect(
        "Enabled strategies",
        strategy_options,
        default=[value for value in policy.enabled_strategy_ids if value in strategy_options],
    )
    manual_default = (
        strategy_options.index(policy.manual_strategy_id)
        if policy.manual_strategy_id in strategy_options
        else 0
    )
    manual_strategy = st.selectbox(
        "Manual strategy",
        strategy_options,
        index=manual_default,
        disabled=mode != "manual",
    )

    left, right = st.columns(2)
    with left:
        switch_buffer = st.number_input(
            "Switch buffer (bps)",
            min_value=0.0,
            max_value=25.0,
            value=float(policy.switch_buffer_bps),
            step=0.5,
        )
        rebalance_buffer = st.number_input(
            "Same-strategy rebalance buffer (bps)",
            min_value=0.0,
            max_value=10.0,
            value=float(policy.rebalance_buffer_bps),
            step=0.25,
        )
        max_turnover = st.slider(
            "Maximum one-way turnover",
            min_value=0.05,
            max_value=1.0,
            value=float(policy.max_one_way_turnover),
            step=0.01,
        )
    with right:
        turnover_penalty = st.number_input(
            "Extra turnover penalty (bps per 100%)",
            min_value=0.0,
            max_value=25.0,
            value=float(policy.turnover_penalty_bps),
            step=0.5,
        )
        minimum_alpha = st.number_input(
            "Minimum net expected alpha (bps)",
            min_value=-25.0,
            max_value=25.0,
            value=float(policy.min_expected_net_alpha_bps),
            step=0.5,
        )
        fallback = st.checkbox(
            "Fall back to current portfolio",
            value=bool(policy.fallback_to_current),
        )

    if st.button("Save strategy-selection policy", type="primary"):
        try:
            updated = SelectionPolicy(
                mode=mode,
                enabled_strategy_ids=tuple(enabled),
                manual_strategy_id=manual_strategy,
                switch_buffer_bps=float(switch_buffer),
                rebalance_buffer_bps=float(rebalance_buffer),
                turnover_penalty_bps=float(turnover_penalty),
                max_one_way_turnover=float(max_turnover),
                risk_penalty_scale=policy.risk_penalty_scale,
                min_expected_net_alpha_bps=float(minimum_alpha),
                alpha_halflife=policy.alpha_halflife,
                alpha_min_history=policy.alpha_min_history,
                fallback_to_current=bool(fallback),
            )
            path = service.save_policy(updated)
            st.success(f"Saved policy to {path}")
        except Exception as exc:
            st.error(str(exc))

    st.subheader("Latest candidate board")
    if board.empty:
        st.info(
            "No board exists yet. Run `python -m svyable.strategy_daily --force` "
            "or wait for the next scheduled PM run."
        )
    else:
        position_source = str(board.iloc[0].get("current_position_source", "unknown"))
        st.caption(
            f"Turnover and overlap are measured from `{position_source}`. "
            "Expected alpha is a causal, confidence-shrunk one-day estimate—not a promise."
        )
        display_columns = [
            column
            for column in [
                "candidate_id",
                "action",
                "eligible",
                "expected_alpha_bps",
                "alpha_confidence",
                "estimated_cost_bps",
                "net_expected_alpha_bps",
                "utility_bps",
                "one_way_turnover",
                "max_weight_change",
                "avg_one_way_turnover_63d",
                "current_overlap",
                "return_63d",
                "return_252d",
                "sharpe_252d",
                "recent_vol",
                "recent_max_drawdown",
                "rebalance_required",
                "cadence_due",
                "hold_lock",
                "kill_switch",
            ]
            if column in board.columns
        ]
        st.dataframe(
            board[display_columns].sort_values("utility_bps", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        eligible = board[board["eligible"] == True]  # noqa: E712
        eligible_ids = eligible["candidate_id"].astype(str).tolist()
        st.subheader("Agent / PM decision")
        selected_candidate = st.selectbox(
            "Eligible candidate",
            eligible_ids,
            disabled=not eligible_ids,
        )
        confidence = st.slider(
            "Decision confidence",
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.05,
        )
        reason = st.text_area(
            "PM rationale",
            value="Prefer the highest robust net expected alpha after costs, turnover, and current-position overlap.",
        )
        decision_col, activate_col = st.columns(2)
        with decision_col:
            if st.button("Write validated agent decision", disabled=not eligible_ids):
                try:
                    path = service.save_agent_decision(
                        candidate_id=selected_candidate,
                        reason=reason,
                        confidence=confidence,
                    )
                    st.success(f"Decision saved to {path}.")
                except Exception as exc:
                    st.error(str(exc))
        with activate_col:
            if st.button("Activate latest validated decision", type="primary"):
                try:
                    result = service.activate_latest()
                    st.success(
                        f"Activated {result['strategy_id']} with action {result['action']}."
                    )
                    st.json(result)
                except Exception as exc:
                    st.error(str(exc))

    with st.expander("Agent prompt"):
        st.code(service.agent_prompt(), language="text")

    with st.expander("Latest selection JSON"):
        st.json(snapshot["decision"] or {})
