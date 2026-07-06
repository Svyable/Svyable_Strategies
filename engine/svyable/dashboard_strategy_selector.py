"""Streamlit PM control surface for registered strategy selection."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from svyable.strategy_selector import SelectionPolicy
from svyable.strategy_selection_service import StrategySelectionService


def _short_hash(value: object, length: int = 10) -> str:
    text = str(value or "")
    return text[:length] if text else "—"


def _bps(value: object) -> str:
    try:
        return f"{float(value):.2f} bps"
    except (TypeError, ValueError):
        return "—"


def _pct(value: object) -> str:
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "—"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _gate_status_label(status: object) -> str:
    status_text = str(status or "BLOCK").upper()
    if status_text == "PASS":
        return "✅ PASS"
    if status_text == "WARN":
        return "⚠️ WARN"
    if status_text in {"OK", "SUCCESS"}:
        return "✅ PASS"
    return "⛔ BLOCK"


def _candidate_label(row: pd.Series | dict[str, Any]) -> str:
    candidate_id = str(row.get("candidate_id", ""))
    action = str(row.get("action", ""))
    family = str(row.get("family", ""))
    utility = _bps(row.get("utility_bps"))
    return f"{candidate_id} · {action} · {family} · utility {utility}"


def _blocked_reasons(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    if not _truthy(row.get("eligible", False)):
        reasons.append("not eligible")
    if _truthy(row.get("hold_lock", False)):
        reasons.append("minimum hold active")
    if not _truthy(row.get("cadence_due", True)):
        reasons.append("cadence not due")
    if not _truthy(row.get("rebalance_required", True)) and str(row.get("action", "")) != "hold":
        reasons.append("drift below rebalance threshold")
    if _truthy(row.get("kill_switch", False)):
        reasons.append("kill switch")
    try:
        if float(row.get("one_way_turnover", 0.0)) > 0.35:
            reasons.append("high turnover")
    except (TypeError, ValueError):
        pass
    return reasons


def render_frontier_coverage(
    service: StrategySelectionService, *, allow_enable: bool = True
) -> None:
    """Show how much of the full strategy registry the current board analyzes.

    A board narrower than the registry is the usual reason only a handful of
    strategies appear in the analysis charts. Surfacing the gap — and a one-click
    way to close it — keeps every app surface working against the whole frontier.
    Shared by the agent-lab Board tab and the PM control surface so both report
    coverage identically.
    """
    try:
        status = service.frontier_status()
    except Exception:
        return

    board_count = status.get("board_candidate_count", 0)
    expected = status.get("expected_candidate_count", 0)
    registry_count = status.get("registry_strategy_count", 0)
    blend_count = status.get("blend_registry_count", 0)

    cols = st.columns(4)
    cols[0].metric("Board candidates", board_count)
    cols[1].metric("Enabled frontier", expected, help="Enabled strategies + chimeras + hold_current.")
    cols[2].metric("Roster strategies", registry_count, help="Every strategy the codebase can evaluate.")
    cols[3].metric("Chimera blends", blend_count)

    if status.get("is_incomplete_latest_board"):
        missing = status.get("missing_enabled_strategy_ids", []) + status.get("missing_enabled_blend_ids", [])
        st.warning(
            "The latest board analyzes "
            f"**{board_count} of {expected}** enabled candidates. "
            + (f"Missing: {', '.join(missing[:12])}{'…' if len(missing) > 12 else ''}. " if missing else "")
            + "Enable the full registry frontier, then run a fresh evaluation."
        )
        if allow_enable and st.button(
            "Enable full roster frontier",
            help="Turn on every default strategy and chimera in the selection policy.",
            key="enable_full_frontier",
        ):
            try:
                path = service.save_full_frontier_policy()
                st.success(f"Full frontier enabled in policy: {path}. Now run a fresh candidate evaluation.")
            except Exception as exc:
                st.error(f"Could not enable full frontier: {exc}")
    else:
        st.success(f"Board analyzes all {board_count} enabled candidates across the roster frontier.")


def _render_regime_panel(service: StrategySelectionService) -> None:
    st.subheader("Market regime")
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
        help="Multiplier applied to the risk budget by the turbulence stack. 100% = calm tape.",
    )
    turb_pct = latest.get("turb_pct")
    cols[1].metric(
        "Turbulence",
        f"{float(turb_pct):.0%}" if turb_pct == turb_pct else "warming up",
    )
    absorption = latest.get("absorption")
    cols[2].metric(
        "Absorption",
        f"{float(absorption):.0%}" if absorption == absorption else "warming up",
    )
    cols[3].metric("Regime", "DEFENSIVE" if throttle < 0.995 else "NORMAL")
    with st.expander("Regime history"):
        chart_columns = [
            column for column in ("throttle", "turb_pct", "absorption")
            if column in regime.columns
        ]
        st.line_chart(regime[chart_columns].tail(252))
        st.caption(f"Source: {regime.attrs.get('source', 'latest candidate run')}")


def _render_candidate_snapshot(row: pd.Series | None) -> None:
    if row is None:
        st.info("Select an eligible strategy candidate to review its summary.")
        return
    cols = st.columns(6)
    cols[0].metric("Candidate", str(row.get("candidate_id", "—")))
    cols[1].metric("Action", str(row.get("action", "—")))
    cols[2].metric("Utility", _bps(row.get("utility_bps")))
    cols[3].metric("Net alpha", _bps(row.get("net_expected_alpha_bps", row.get("expected_alpha_bps"))))
    cols[4].metric("Cost", _bps(row.get("estimated_cost_bps")))
    cols[5].metric("Turnover", _pct(row.get("one_way_turnover")))

    detail_cols = [
        column
        for column in [
            "candidate_id",
            "strategy_id",
            "action",
            "family",
            "maturity",
            "eligible",
            "expected_alpha_bps",
            "alpha_confidence",
            "estimated_cost_bps",
            "net_expected_alpha_bps",
            "utility_bps",
            "one_way_turnover",
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
            "output_dir",
        ]
        if column in row.index
    ]
    with st.expander("Selected candidate details", expanded=False):
        st.json({column: row.get(column) for column in detail_cols})
        reasons = _blocked_reasons(row)
        if reasons:
            st.warning("Blockers / cautions: " + ", ".join(reasons))


def _render_board_table(board: pd.DataFrame) -> None:
    if board.empty:
        st.info("No board exists yet. Run a fresh evaluation above or wait for the scheduled PM job.")
        return
    display = board.copy()
    if "eligible" in display.columns:
        display["decision_status"] = display.apply(
            lambda row: "eligible" if _truthy(row.get("eligible")) else "; ".join(_blocked_reasons(row)),
            axis=1,
        )
    columns = [
        column
        for column in [
            "candidate_id",
            "decision_status",
            "action",
            "family",
            "eligible",
            "utility_bps",
            "net_expected_alpha_bps",
            "expected_alpha_bps",
            "estimated_cost_bps",
            "one_way_turnover",
            "current_overlap",
            "sharpe_252d",
            "recent_max_drawdown",
        ]
        if column in display.columns
    ]
    if "utility_bps" in display.columns:
        display = display.sort_values("utility_bps", ascending=False)
    st.dataframe(display[columns], use_container_width=True, hide_index=True)


def _render_context_status(service: StrategySelectionService, board: pd.DataFrame) -> None:
    context = service.latest_agent_context()
    memo = service.latest_agent_memo()
    if not context:
        st.warning(
            "The latest agent context pack is missing. Run a fresh evaluation, or use "
            "Refresh context + run review checks after a board exists."
        )
        return
    board_hash = str(board.iloc[0].get("candidate_set_hash", "")) if not board.empty else ""
    context_hash = str(context.get("candidate_set_hash", ""))
    status = "PASS" if board_hash and context_hash == board_hash else "BLOCK"
    cols = st.columns(4)
    cols[0].metric("Context", _gate_status_label(status))
    cols[1].metric("Board date", context.get("as_of", "—"))
    cols[2].metric("Board hash", _short_hash(context_hash))
    cols[3].metric("Allowed IDs", len((context.get("rails") or {}).get("allowed_candidate_ids", [])))
    readiness = context.get("decision_readiness", {}) or {}
    if readiness.get("status") == "PASS":
        st.success("Agent context is ready for a PM decision.")
    else:
        st.warning("Decision readiness is not PASS yet.")
        issues = readiness.get("issues", []) or []
        if issues:
            st.write("Fix before decision:")
            st.write(issues)
    if memo:
        with st.expander("Read latest PM memo", expanded=False):
            st.markdown(memo)


def _render_review_chain(service: StrategySelectionService) -> dict[str, Any]:
    chain = service.latest_agent_review_chain()
    receipt = service.latest_agent_review_receipt()
    audit = service.latest_agent_review_audit()

    cols = st.columns(4)
    cols[0].metric("Review chain", _gate_status_label(chain.get("status")))
    cols[1].metric("Receipt", _gate_status_label(receipt.get("status")))
    cols[2].metric("Audit", _gate_status_label(audit.get("status")))
    cols[3].metric("Decision fingerprint", _short_hash(receipt.get("decision_fingerprint"), 12))

    if st.button("Run review checks", type="primary", key="run_agent_review_chain"):
        try:
            with st.spinner("Running guard, receipt, and audit checks..."):
                chain = service.run_review_chain(refresh_context=False)
            st.success("Review checks completed.")
            st.session_state["agent_review_chain_result"] = chain
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if st.button(
        "Refresh context + run checks",
        help="Use this when a board exists but the latest context pack is missing or stale.",
        key="refresh_context_and_run_chain",
    ):
        try:
            with st.spinner("Refreshing context and running review checks..."):
                chain = service.run_review_chain(refresh_context=True)
            st.success("Context refresh and review checks completed.")
            st.session_state["agent_review_chain_result"] = chain
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    chain = service.latest_agent_review_chain()
    if chain:
        stages = pd.DataFrame(
            [
                {
                    "stage": stage.get("name"),
                    "status": stage.get("status"),
                    "detail": stage.get("error")
                    or (stage.get("payload", {}) or {}).get("next_step")
                    or ", ".join((stage.get("payload", {}) or {}).get("blockers", [])[:2]),
                }
                for stage in chain.get("stages", [])
            ]
        )
        if not stages.empty:
            st.dataframe(stages, use_container_width=True, hide_index=True)
        if chain.get("blockers"):
            st.error("Blocked stages: " + ", ".join(chain.get("blockers", [])))
    if receipt:
        with st.expander("Review receipt", expanded=False):
            st.json(receipt)
    return chain


def _render_today_strategy_decision(service: StrategySelectionService, board: pd.DataFrame) -> None:
    st.subheader("Which strategy should we run today?")
    st.caption(
        "Start here. The app helps you choose one candidate from the strategy roster, "
        "write a guarded decision, run review checks, and activate only after PASS."
    )

    if board.empty:
        st.info("No candidate board yet. Run a fresh candidate evaluation below.")
        return

    first = board.iloc[0]
    eligible = board[board["eligible"].map(_truthy)] if "eligible" in board.columns else board
    if "utility_bps" in eligible.columns:
        eligible = eligible.sort_values("utility_bps", ascending=False)
    eligible_ids = eligible["candidate_id"].astype(str).tolist() if "candidate_id" in eligible.columns else []
    pending = service.pending_agent_decision()
    readiness = service.activation_readiness()

    cols = st.columns(5)
    cols[0].metric("Board date", first.get("as_of", "—"))
    cols[1].metric("Board hash", _short_hash(first.get("candidate_set_hash")))
    cols[2].metric("Eligible choices", len(eligible_ids))
    cols[3].metric("Review", _gate_status_label(service.latest_agent_review_chain().get("status")))
    cols[4].metric("Next action", readiness.get("next_action", "Review board"))

    _render_context_status(service, board)

    st.markdown("### 1 · Review the roster")
    _render_board_table(board)
    if not eligible_ids:
        st.error("No eligible candidate exists on the latest board. Do not activate.")
        return

    default_id = str(pending.get("candidate_id") or eligible_ids[0])
    default_index = eligible_ids.index(default_id) if default_id in eligible_ids else 0
    selected_candidate = st.selectbox(
        "Recommended decision candidate",
        eligible_ids,
        index=default_index,
        format_func=lambda cid: _candidate_label(eligible[eligible["candidate_id"].astype(str) == cid].iloc[0]),
        help="Choose one allowed candidate ID. Security weights stay immutable and deterministic.",
    )
    selected_row = eligible[eligible["candidate_id"].astype(str) == selected_candidate].iloc[0]
    _render_candidate_snapshot(selected_row)

    hold = board[board.get("candidate_id", pd.Series(dtype=object)).astype(str) == "hold_current"]
    if not hold.empty and selected_candidate != "hold_current":
        hold_row = hold.iloc[0]
        try:
            delta = float(selected_row.get("utility_bps", 0.0)) - float(hold_row.get("utility_bps", 0.0))
            st.caption(f"Edge versus holding current book: **{delta:.2f} bps utility**.")
        except (TypeError, ValueError):
            pass

    st.markdown("### 2 · Write the guarded decision")
    confidence = st.slider(
        "Decision confidence",
        min_value=0.0,
        max_value=1.0,
        value=float(pending.get("confidence", 0.55) or 0.55),
        step=0.05,
        help="Use low confidence when the evidence is mixed. Low confidence still requires human review.",
    )
    default_reason = pending.get("reason") or (
        f"Run {selected_candidate} today because it has the best reviewed utility after costs, turnover, "
        "current-position overlap, regime context, and artifact checks."
    )
    reason = st.text_area(
        "Plain-English PM rationale",
        value=str(default_reason),
        help="This becomes part of the review receipt. Keep it concise and evidence-based.",
    )
    if st.button("Write guarded decision", type="primary", disabled=not selected_candidate):
        try:
            result = service.write_guarded_decision(
                candidate_id=selected_candidate,
                confidence=confidence,
                reason=reason,
                operator="streamlit_pm",
            )
            st.session_state["guarded_decision_result"] = result
            if result.get("status") == "PASS":
                st.success("Decision written and guard passed. Run review checks next.")
            else:
                st.error("Decision was written, but guard blocked it. Review blockers below.")
            st.json(result)
        except Exception as exc:
            st.error(str(exc))

    pending = service.pending_agent_decision()
    if pending:
        st.info(
            f"Pending decision: **{pending.get('candidate_id')}** · confidence "
            f"{_pct(pending.get('confidence'))} · utility {_bps(pending.get('utility_bps'))}"
        )

    st.markdown("### 3 · Run review checks")
    _render_review_chain(service)

    st.markdown("### 4 · Approve today’s strategy")
    readiness = service.activation_readiness()
    if readiness.get("activated"):
        st.success("This board has already been activated. Portfolio Ops can use the canonical target.")
        return
    if readiness.get("status") != "PASS":
        st.error("Activation is blocked until review checks pass.")
        for blocker in readiness.get("blockers", []):
            st.write(f"- {blocker}")
        return

    expected = str(readiness.get("candidate_id") or selected_candidate)
    typed = st.text_input(
        f"Type `{expected}` to approve activation",
        value="",
        help="Activation writes the canonical portfolio artifact. It still does not submit broker orders.",
    )
    if st.button(
        "Approve today’s strategy",
        type="primary",
        disabled=typed.strip() != expected,
        help="Creates canonical weights only. Broker preflight remains separate in Portfolio Ops.",
    ):
        try:
            result = service.activate_latest()
            st.success(f"Activated {result['strategy_id']} with action {result['action']}.")
            st.json(result)
        except Exception as exc:
            st.error(str(exc))


def _render_strategy_registry_and_policy(service: StrategySelectionService) -> None:
    snapshot = service.snapshot()
    registry = snapshot["registry"]
    blends = snapshot["blends"]
    policy = service.policy()

    st.subheader("Strategy roster")
    st.caption(
        "These are complete strategy recipes. The app helps choose one roster candidate for today; "
        "future research can add overnight, intraday, sector, market-neutral, or any other book style."
    )
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
        "A chimera is a portfolio-level blend of registered strategies. It joins the next board; "
        "it never directly edits security weights."
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
                    f"Saved (weights normalized to sum to 1) to {path}. It joins the next candidate board."
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
            "Deterministic ranks and activates immediately; agent emits a board and waits for a validated "
            "decision; manual selects one registered strategy."
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
        help="A blend is evaluated only when every component strategy is also enabled.",
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
            "Switch buffer (bps)", min_value=0.0, max_value=25.0, value=float(policy.switch_buffer_bps), step=0.5
        )
        rebalance_buffer = st.number_input(
            "Same-strategy rebalance buffer (bps)", min_value=0.0, max_value=10.0, value=float(policy.rebalance_buffer_bps), step=0.25
        )
        max_turnover = st.slider(
            "Maximum one-way turnover", min_value=0.05, max_value=1.0, value=float(policy.max_one_way_turnover), step=0.01
        )
    with right:
        turnover_penalty = st.number_input(
            "Extra turnover penalty (bps per 100%)", min_value=0.0, max_value=25.0, value=float(policy.turnover_penalty_bps), step=0.5
        )
        minimum_alpha = st.number_input(
            "Minimum net expected alpha (bps)", min_value=-25.0, max_value=25.0, value=float(policy.min_expected_net_alpha_bps), step=0.5
        )
        fallback = st.checkbox("Fall back to current portfolio", value=bool(policy.fallback_to_current))

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


def _render_candidate_evaluation(service: StrategySelectionService) -> None:
    st.subheader("Refresh today’s board")
    render_frontier_coverage(service, allow_enable=False)
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
        force_evaluation = st.checkbox("Allow holiday/weekend evaluation", value=True)
    evaluate_full_frontier = st.checkbox(
        "Evaluate the entire roster frontier",
        value=True,
        help="Enable every default strategy and chimera before running so the board covers the whole roster.",
    )
    if st.button("Run fresh candidate evaluation"):
        try:
            spinner_text = "Computing the full roster frontier..." if evaluate_full_frontier else "Computing enabled candidates..."
            with st.spinner(spinner_text):
                result = service.run_evaluation(
                    start=evaluation_start,
                    provider=evaluation_provider,
                    force=force_evaluation,
                    full_frontier=evaluate_full_frontier,
                )
            st.session_state["strategy_evaluation_result"] = result
            st.success("Candidate evaluation completed. Refreshing the page state.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("strategy_evaluation_result"):
        with st.expander("Latest evaluation process output"):
            st.json(st.session_state["strategy_evaluation_result"])


def render_strategy_selector(service: StrategySelectionService) -> None:
    snapshot = service.snapshot()
    board = snapshot["board"]
    state = snapshot["state"]

    st.caption(
        "Simple daily objective: pick which strategy from the roster should run today. "
        "The app keeps the agent/human decision separate from activation and broker execution."
    )

    cols = st.columns(5)
    cols[0].metric("Current strategy", state.get("selected_strategy_id", "not selected"))
    cols[1].metric("Last action", state.get("selected_action", "—"))
    cols[2].metric("Selection source", state.get("source", "—"))
    cols[3].metric("Position source", state.get("current_position_source", "—"))
    cols[4].metric("Candidate hash", _short_hash(state.get("candidate_set_hash")))

    _render_today_strategy_decision(service, board)

    st.divider()
    with st.expander("Market regime and roster policy", expanded=False):
        _render_regime_panel(service)
        st.divider()
        _render_strategy_registry_and_policy(service)

    st.divider()
    with st.expander("Refresh or rebuild the candidate board", expanded=False):
        _render_candidate_evaluation(service)

    with st.expander("Agent prompt", expanded=False):
        st.code(service.agent_prompt(), language="text")

    with st.expander("Latest selection JSON", expanded=False):
        st.json(snapshot["decision"] or {})
