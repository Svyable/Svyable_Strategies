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
    strategy_id = str(row.get("strategy_id", ""))
    name = str(row.get("name", ""))
    net_alpha = _bps(row.get("net_expected_alpha_bps", row.get("expected_alpha_bps")))
    utility = _bps(row.get("utility_bps"))
    if candidate_id == "hold_current":
        provenance = str(row.get("current_strategy_provenance") or strategy_id or "cash")
        return f"hold_current · {provenance} · net alpha {net_alpha} · utility {utility}"
    label_name = name if name and name != candidate_id else strategy_id
    return f"{candidate_id} · {action} · {label_name} · net alpha {net_alpha} · utility {utility}"


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


def _strategy_name(service: StrategySelectionService, strategy_id: object) -> str:
    sid = str(strategy_id or "cash")
    if sid == "cash":
        return "Cash / no active strategy"
    try:
        return str(service.strategy_details(sid).get("name") or sid)
    except Exception:
        return sid


def _hold_row(board: pd.DataFrame) -> pd.Series | None:
    if board.empty or "candidate_id" not in board.columns:
        return None
    matches = board[board["candidate_id"].astype(str) == "hold_current"]
    return None if matches.empty else matches.iloc[0]


def _render_hold_current_explanation(service: StrategySelectionService, board: pd.DataFrame) -> None:
    hold = _hold_row(board)
    if hold is None:
        return

    strategy_id = str(hold.get("strategy_id", "cash") or "cash")
    strategy_name = _strategy_name(service, strategy_id)
    position_source = str(hold.get("current_position_source", "canonical target"))
    provenance = f"{strategy_id} — {strategy_name} · positions from {position_source}"

    with st.container(border=True):
        st.markdown("#### Current holdings provenance")
        st.caption(
            "`hold_current` means **do not trade**. It keeps the canonical target weights already on file; "
            "the fields below show which strategy or blend created those holdings."
        )
        cols = st.columns(5)
        cols[0].metric("Hold row", "hold_current")
        cols[1].metric("Underlying strategy_id", strategy_id)
        cols[2].metric("Strategy / blend name", strategy_name)
        cols[3].metric("Position source", position_source)
        cols[4].metric("Current holdings", f"{int(hold.get('positions', 0) or 0)} names")
        st.caption(
            f"Current strategy provenance: **{provenance}** · "
            f"net alpha after estimated cost: **{_bps(hold.get('net_expected_alpha_bps'))}** · "
            f"utility after conservative penalties: **{_bps(hold.get('utility_bps'))}**."
        )


def _alpha_policy_from_controls(
    *,
    mode: str,
    enabled: list[str],
    enabled_blends: list[str],
    custom_blends: tuple[dict, ...],
    manual_strategy: str,
    switch_buffer: float,
    rebalance_buffer: float,
    turnover_penalty: float,
    max_turnover: float,
    risk_penalty_scale: float,
    minimum_alpha: float,
    alpha_halflife: int,
    alpha_min_history: int,
    fallback: bool,
) -> SelectionPolicy:
    return SelectionPolicy(
        mode=mode,
        enabled_strategy_ids=tuple(enabled),
        enabled_blend_ids=tuple(enabled_blends),
        custom_blends=custom_blends,
        manual_strategy_id=manual_strategy,
        switch_buffer_bps=float(switch_buffer),
        rebalance_buffer_bps=float(rebalance_buffer),
        turnover_penalty_bps=float(turnover_penalty),
        max_one_way_turnover=float(max_turnover),
        risk_penalty_scale=float(risk_penalty_scale),
        min_expected_net_alpha_bps=float(minimum_alpha),
        alpha_halflife=int(alpha_halflife),
        alpha_min_history=int(alpha_min_history),
        fallback_to_current=bool(fallback),
    )


def _max_alpha_policy(
    policy: SelectionPolicy,
    *,
    enabled: list[str],
    enabled_blends: list[str],
    manual_strategy: str,
    mode: str,
) -> SelectionPolicy:
    """Aggressive selector preset: keep real trading cost, remove incumbent bias."""
    return _alpha_policy_from_controls(
        mode=mode,
        enabled=enabled,
        enabled_blends=enabled_blends,
        custom_blends=policy.custom_blends,
        manual_strategy=manual_strategy,
        switch_buffer=0.0,
        rebalance_buffer=0.0,
        turnover_penalty=0.0,
        max_turnover=1.0,
        risk_penalty_scale=0.0,
        minimum_alpha=-25.0,
        alpha_halflife=policy.alpha_halflife,
        alpha_min_history=policy.alpha_min_history,
        fallback=False,
    )


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
    cols[1].metric("strategy_id", str(row.get("strategy_id", "—")))
    cols[2].metric("Net alpha after est. cost", _bps(row.get("net_expected_alpha_bps", row.get("expected_alpha_bps"))))
    cols[3].metric(
        "Utility after conservative penalties",
        _bps(row.get("utility_bps")),
        help="Net alpha minus extra turnover and risk penalties. In deterministic mode, switch/hold buffers are applied when comparing to hold_current.",
    )
    cols[4].metric("Est. trading cost", _bps(row.get("estimated_cost_bps")))
    cols[5].metric("One-way turnover", _pct(row.get("one_way_turnover")))

    if str(row.get("candidate_id", "")) == "hold_current":
        st.info(
            "`hold_current` is a no-trade baseline. It keeps the current canonical holdings, "
            f"which were predicated on **{row.get('current_strategy_provenance', row.get('strategy_id', 'cash'))}**."
        )

    detail_cols = [
        column
        for column in [
            "candidate_id",
            "strategy_id",
            "name",
            "current_strategy_id",
            "current_strategy_name",
            "current_strategy_provenance",
            "current_position_source",
            "action",
            "family",
            "maturity",
            "eligible",
            "expected_alpha_bps",
            "alpha_confidence",
            "estimated_cost_bps",
            "net_expected_alpha_bps",
            "turnover_penalty_bps",
            "risk_penalty_bps",
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
    if {"net_expected_alpha_bps", "utility_bps"} <= set(display.columns):
        display["alpha_vs_utility_bps"] = (
            pd.to_numeric(display["net_expected_alpha_bps"], errors="coerce")
            - pd.to_numeric(display["utility_bps"], errors="coerce")
        ).round(3)
    columns = [
        column
        for column in [
            "candidate_id",
            "strategy_id",
            "name",
            "current_strategy_provenance",
            "decision_status",
            "action",
            "family",
            "eligible",
            "net_expected_alpha_bps",
            "utility_bps",
            "alpha_vs_utility_bps",
            "expected_alpha_bps",
            "estimated_cost_bps",
            "turnover_penalty_bps",
            "risk_penalty_bps",
            "one_way_turnover",
            "current_overlap",
            "sharpe_252d",
            "recent_max_drawdown",
        ]
        if column in display.columns
    ]
    if "utility_bps" in display.columns:
        display = display.sort_values("utility_bps", ascending=False)
    st.caption(
        "**Net alpha after estimated cost** = expected alpha minus estimated trading cost. "
        "**Utility after conservative penalties** = net alpha minus extra turnover/risk penalties; "
        "deterministic selection then compares against hold_current using the configured buffers."
    )
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
    _render_hold_current_explanation(service, board)
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
        key="strategy_decision_candidate",
    )
    selected_row = eligible[eligible["candidate_id"].astype(str) == selected_candidate].iloc[0]
    _render_candidate_snapshot(selected_row)

    hold = board[board.get("candidate_id", pd.Series(dtype=object)).astype(str) == "hold_current"]
    if not hold.empty and selected_candidate != "hold_current":
        hold_row = hold.iloc[0]
        try:
            utility_delta = float(selected_row.get("utility_bps", 0.0)) - float(hold_row.get("utility_bps", 0.0))
            net_alpha_delta = float(selected_row.get("net_expected_alpha_bps", 0.0)) - float(
                hold_row.get("net_expected_alpha_bps", hold_row.get("expected_alpha_bps", 0.0))
            )
            st.caption(
                "Edge versus holding current book: "
                f"**{net_alpha_delta:.2f} bps net alpha after estimated cost** · "
                f"**{utility_delta:.2f} bps utility after conservative penalties**."
            )
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
        key="strategy_decision_confidence",
    )
    default_reason = pending.get("reason") or (
        f"Run {selected_candidate} today because it has the best reviewed balance of net alpha after estimated cost, "
        "conservative utility penalties, turnover, current-position overlap, regime context, and artifact checks."
    )
    reason = st.text_area(
        "Plain-English PM rationale",
        value=str(default_reason),
        help="This becomes part of the review receipt. Keep it concise and evidence-based.",
        key="strategy_decision_reason",
    )
    if st.button("Write guarded decision", type="primary", disabled=not selected_candidate, key="write_guarded_decision"):
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
            f"{_pct(pending.get('confidence'))} · net alpha after est. cost "
            f"{_bps(pending.get('net_expected_alpha_bps', pending.get('expected_alpha_bps')))} · "
            f"utility after conservative penalties {_bps(pending.get('utility_bps'))}"
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
        key="strategy_activation_confirm_text",
    )
    if st.button(
        "Approve today’s strategy",
        type="primary",
        disabled=typed.strip() != expected,
        help="Creates canonical weights only. Broker preflight remains separate in Portfolio Ops.",
        key="approve_today_strategy",
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
            "Blend id (must start with `chimera_`)", value="chimera_custom", key="chimera_builder_blend_id"
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
            "Minimum hold days", min_value=0, max_value=20, value=3, key="chimera_builder_min_hold_days"
        )
        if st.button("Save custom chimera", disabled=len(component_ids) < 2, key="save_custom_chimera"):
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
    st.caption(
        "Choose whether the selector should behave like a conservative PM or pursue max-alpha rotation. "
        "Estimated trading cost is always shown separately from the extra conservative utility penalties."
    )
    mode = st.radio(
        "Mode",
        ["deterministic", "agent", "manual"],
        index=["deterministic", "agent", "manual"].index(policy.mode),
        horizontal=True,
        help=(
            "Deterministic ranks and activates immediately; agent emits a board and waits for a validated "
            "decision; manual selects one registered strategy."
        ),
        key="selection_policy_mode",
    )
    enabled = st.multiselect(
        "Enabled strategies",
        strategy_options,
        default=[value for value in policy.enabled_strategy_ids if value in strategy_options],
        key="selection_policy_enabled_strategies",
    )
    blend_options = list(blends.index)
    enabled_blends = st.multiselect(
        "Enabled chimera blends",
        blend_options,
        default=[value for value in policy.enabled_blend_ids if value in blend_options],
        help="A blend is evaluated only when every component strategy is also enabled.",
        key="selection_policy_enabled_blends",
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
        key="selection_policy_manual_strategy",
    )

    st.info(
        "**Max alpha preset** sets switch/rebalance buffers to 0, removes the extra turnover/risk penalties, "
        "raises max turnover to 100%, and disables fallback-to-current. It still displays estimated trading cost."
    )
    if st.button("Save MAX ALPHA policy preset", type="primary", key="save_max_alpha_policy"):
        try:
            updated = _max_alpha_policy(
                policy,
                enabled=enabled,
                enabled_blends=enabled_blends,
                manual_strategy=manual_strategy,
                mode=mode,
            )
            path = service.save_policy(updated)
            st.success(f"Saved max-alpha policy to {path}. Run a fresh candidate evaluation to rebuild the board.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    left, right = st.columns(2)
    with left:
        switch_buffer = st.number_input(
            "Switch buffer (bps)",
            min_value=0.0,
            max_value=25.0,
            value=float(policy.switch_buffer_bps),
            step=0.5,
            key="selection_policy_switch_buffer",
            help="Extra edge required before switching away from the current holdings.",
        )
        rebalance_buffer = st.number_input(
            "Same-strategy rebalance buffer (bps)",
            min_value=0.0,
            max_value=10.0,
            value=float(policy.rebalance_buffer_bps),
            step=0.25,
            key="selection_policy_rebalance_buffer",
        )
        max_turnover = st.slider(
            "Maximum one-way turnover",
            min_value=0.05,
            max_value=1.0,
            value=float(policy.max_one_way_turnover),
            step=0.01,
            key="selection_policy_max_turnover",
        )
    with right:
        turnover_penalty = st.number_input(
            "Extra turnover penalty (bps per 100%)",
            min_value=0.0,
            max_value=25.0,
            value=float(policy.turnover_penalty_bps),
            step=0.5,
            key="selection_policy_turnover_penalty",
            help="Additional conservative penalty beyond estimated trading cost.",
        )
        risk_penalty_scale = st.number_input(
            "Risk penalty scale",
            min_value=0.0,
            max_value=0.50,
            value=float(policy.risk_penalty_scale),
            step=0.01,
            key="selection_policy_risk_penalty_scale",
        )
        minimum_alpha = st.number_input(
            "Minimum net expected alpha (bps)",
            min_value=-25.0,
            max_value=25.0,
            value=float(policy.min_expected_net_alpha_bps),
            step=0.5,
            key="selection_policy_minimum_alpha",
        )
        fallback = st.checkbox(
            "Fall back to current portfolio",
            value=bool(policy.fallback_to_current),
            key="selection_policy_fallback_current",
            help="When on, hold_current can win unless a candidate clears the configured buffer.",
        )

    if st.button("Save strategy-selection policy", type="primary", key="save_strategy_selection_policy"):
        try:
            updated = _alpha_policy_from_controls(
                mode=mode,
                enabled=enabled,
                enabled_blends=enabled_blends,
                custom_blends=policy.custom_blends,
                manual_strategy=manual_strategy,
                switch_buffer=switch_buffer,
                rebalance_buffer=rebalance_buffer,
                turnover_penalty=turnover_penalty,
                max_turnover=max_turnover,
                risk_penalty_scale=risk_penalty_scale,
                minimum_alpha=minimum_alpha,
                alpha_halflife=policy.alpha_halflife,
                alpha_min_history=policy.alpha_min_history,
                fallback=fallback,
            )
            path = service.save_policy(updated)
            st.success(f"Saved policy to {path}. Run a fresh candidate evaluation to rebuild the board.")
        except Exception as exc:
            st.error(str(exc))


def _render_candidate_evaluation(service: StrategySelectionService) -> None:
    st.subheader("Refresh today’s board")
    render_frontier_coverage(service, allow_enable=False)
    run_left, run_middle, run_right = st.columns(3)
    with run_left:
        evaluation_start = st.text_input("Evaluation start", value="2020-01-01", key="strategy_eval_start")
    with run_middle:
        evaluation_provider = st.selectbox(
            "Market-data provider",
            ["yf", "tasty"],
            help="Tasty requires configured credentials and available candle history.",
            key="strategy_eval_provider",
        )
    with run_right:
        force_evaluation = st.checkbox("Allow holiday/weekend evaluation", value=True, key="strategy_eval_force")
    evaluate_full_frontier = st.checkbox(
        "Evaluate the entire roster frontier",
        value=True,
        help="Enable every default strategy and chimera before running so the board covers the whole roster.",
        key="strategy_eval_full_frontier",
    )
    if st.button("Run fresh candidate evaluation", key="run_fresh_candidate_evaluation"):
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
