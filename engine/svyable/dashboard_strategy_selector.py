"""Streamlit PM control surface for registered strategy selection."""

from __future__ import annotations

import json

import streamlit as st

from svyable.strategy_selector import SelectionPolicy
from svyable.strategy_selection_service import StrategySelectionService


def _render_regime_panel(service: StrategySelectionService) -> None:
    st.subheader("Regime — turbulence & absorption")
    regime = service.latest_regime()
    if regime.empty:
        st.info("No regime diagnostics yet. Run a candidate evaluation.")
        return
    latest = regime.ffill().iloc[-1]
    throttle = float(latest.get("throttle", 1.0))
    cols = st.columns(4)
    cols[0].metric(
        "Budget throttle",
        f"{throttle:.0%}",
        help="Multiplier applied to the risk budget by the turbulence stack. "
             "100% = calm tape; the floor is the configured turb_floor.",
    )
    turb_pct = latest.get("turb_pct")
    cols[1].metric(
        "Turbulence percentile",
        f"{float(turb_pct):.0%}" if turb_pct == turb_pct else "warming up",
        help="Rolling percentile of the Mahalanobis turbulence index "
             "(return-vector distance from the robust normal-times model).",
    )
    absorption = latest.get("absorption")
    cols[2].metric(
        "Absorption ratio",
        f"{float(absorption):.0%}" if absorption == absorption else "warming up",
        help="Variance share of the top principal components — how tightly "
             "coupled the market currently is.",
    )
    cols[3].metric(
        "Regime",
        "THROTTLED" if throttle < 0.995 else "CALM",
    )
    with st.expander("Regime history (last 252 sessions)"):
        chart_columns = [
            column for column in ("throttle", "turb_pct", "absorption")
            if column in regime.columns
        ]
        st.line_chart(regime[chart_columns].tail(252))
        st.caption(f"Source: {regime.attrs.get('source', 'latest candidate run')}")


def _render_morning_approval(service: StrategySelectionService, pending: dict) -> None:
    st.subheader("Morning proposal awaiting approval")
    if not pending:
        st.caption(
            "No pending agent proposal for the latest board. In agent mode the "
            "morning job emits the board, the agent writes a proposal, and "
            "nothing trades until it is approved here (or via "
            "`python -m svyable.strategy_activate`)."
        )
        return
    candidate = str(pending.get("candidate_id", ""))
    is_blend = candidate.startswith("chimera_")
    cols = st.columns(4)
    cols[0].metric("Proposed candidate", candidate)
    cols[1].metric("Agent confidence", f"{float(pending.get('confidence') or 0.0):.0%}")
    cols[2].metric("Net utility", f"{pending.get('utility_bps', '—')} bps")
    cols[3].metric("Eligible", "yes" if pending.get("eligible") else "NO")
    if is_blend and pending.get("components"):
        st.caption("Chimera composition:")
        st.json(json.loads(str(pending["components"])))
    st.markdown(f"> {pending.get('reason', '')}")
    if not pending.get("eligible"):
        st.error(
            "The proposal is no longer eligible on the latest board; activation "
            "will refuse it. Ask the agent for a fresh decision."
        )


def render_strategy_selector(service: StrategySelectionService) -> None:
    snapshot = service.snapshot()
    registry = snapshot["registry"]
    blends = snapshot["blends"]
    policy = service.policy()
    board = snapshot["board"]
    state = snapshot["state"]

    st.caption(
        "Strategies are complete registered recipes; chimeras are convex blends "
        "of them. The PM or agent selects a candidate portfolio from the "
        "immutable morning board; neither the GUI nor the agent edits weights "
        "directly."
    )

    cols = st.columns(5)
    cols[0].metric("Current strategy", state.get("selected_strategy_id", "not selected"))
    cols[1].metric("Last action", state.get("selected_action", "—"))
    cols[2].metric("Selection source", state.get("source", "—"))
    cols[3].metric("Position source", state.get("current_position_source", "—"))
    cols[4].metric("Candidate hash", state.get("candidate_set_hash", "—"))

    _render_regime_panel(service)
    _render_morning_approval(service, snapshot.get("pending_agent_decision") or {})

    st.subheader("Strategy registry")
    st.dataframe(registry, use_container_width=True)
    strategy_options = list(registry.index)
    inspect_strategy = st.selectbox(
        "Inspect registered strategy",
        strategy_options,
        key="inspect_registered_strategy",
    )
    with st.expander("Strategy recipe", expanded=False):
        st.json(service.strategy_details(inspect_strategy))

    st.subheader("Chimera blends")
    st.caption(
        "A chimera deploys hybrid strategy weights: a convex combination of "
        "registered candidate portfolios, blended at the portfolio level with "
        "honest netting-aware costs. Definitions are data; weights only ever "
        "come from the deterministic morning evaluation."
    )
    st.dataframe(blends, use_container_width=True)
    custom_blends = list(policy.custom_blends)
    if custom_blends:
        st.caption("Custom chimeras persisted with the policy:")
        for item in custom_blends:
            blend_id = str(item.get("blend_id"))
            row = st.columns([4, 1])
            row[0].write(
                f"`{blend_id}` — "
                + ", ".join(
                    f"{sid} {float(w):.0%}"
                    for sid, w in dict(item.get("components", {})).items()
                )
            )
            if row[1].button("Remove", key=f"remove_blend_{blend_id}"):
                service.remove_custom_blend(blend_id)
                st.rerun()
    with st.expander("Build a custom chimera"):
        blend_name = st.text_input(
            "Blend id (must start with `chimera_`)", value="chimera_custom"
        )
        component_ids = st.multiselect(
            "Components (2-4 registered strategies)",
            list(registry.index),
            max_selections=4,
            key="chimera_builder_components",
        )
        weights: dict[str, float] = {}
        if component_ids:
            weight_cols = st.columns(len(component_ids))
            for i, sid in enumerate(component_ids):
                weights[sid] = weight_cols[i].number_input(
                    f"{sid} weight",
                    min_value=0.01,
                    max_value=1.0,
                    value=round(1.0 / len(component_ids), 2),
                    step=0.05,
                    key=f"chimera_builder_w_{sid}",
                )
        hold_days = st.number_input(
            "Minimum hold days", min_value=0, max_value=20, value=3
        )
        if st.button("Save custom chimera", disabled=len(component_ids) < 2):
            try:
                total = sum(weights.values())
                path = service.add_custom_blend({
                    "blend_id": blend_name.strip(),
                    "display_name": blend_name.strip(),
                    "components": {
                        sid: round(weight / total, 6)
                        for sid, weight in weights.items()
                    },
                    "minimum_hold_days": int(hold_days),
                })
                st.success(
                    f"Saved (weights normalized to sum to 1) to {path}. It joins "
                    "the next candidate board."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

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
    enabled = st.multiselect(
        "Enabled strategies",
        strategy_options,
        default=[value for value in policy.enabled_strategy_ids if value in strategy_options],
    )
    blend_options = list(blends.index)
    enabled_blends = st.multiselect(
        "Enabled chimera blends",
        blend_options,
        default=[value for value in policy.enabled_blend_ids if value in blend_options],
        help=(
            "A blend is evaluated only when every component strategy is also "
            "enabled; otherwise it silently sits out that board."
        ),
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
                enabled_blend_ids=tuple(enabled_blends),
                custom_blends=policy.custom_blends,
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

    st.subheader("Candidate evaluation")
    run_left, run_middle, run_right = st.columns(3)
    with run_left:
        evaluation_start = st.text_input("Evaluation start", value="2020-01-01")
    with run_middle:
        evaluation_provider = st.selectbox(
            "Market-data provider",
            ["yf", "tasty"],
            help="Tasty requires configured credentials and available candle history.",
        )
    with run_right:
        force_evaluation = st.checkbox(
            "Allow holiday/weekend evaluation",
            value=True,
        )
    if st.button("Run fresh candidate evaluation"):
        try:
            with st.spinner("Computing all enabled strategy candidates..."):
                result = service.run_evaluation(
                    start=evaluation_start,
                    provider=evaluation_provider,
                    force=force_evaluation,
                )
            st.session_state["strategy_evaluation_result"] = result
            st.success("Candidate evaluation completed. Refreshing the page state.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("strategy_evaluation_result"):
        with st.expander("Latest evaluation process output"):
            st.json(st.session_state["strategy_evaluation_result"])

    snapshot = service.snapshot()
    board = snapshot["board"]
    st.subheader("Latest candidate board")
    if board.empty:
        st.info(
            "No board exists yet. Run a fresh evaluation above or wait for the "
            "scheduled PM job."
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
                "components",
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
            if st.button("Approve & activate latest decision", type="primary"):
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
