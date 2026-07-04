"""Consolidated Tastytrade portfolio-operations workspace.

This replaces the old top-level split between Broker and Rebalance with one PM
workspace. It keeps the safety gates intact while making the execution workflow
read left-to-right: account → positions/drift → rebalance plan → preflight/submit
→ order tools. It deliberately relies on the existing Tastytrade adapter methods
already exposed through DashboardService: account, positions, orders, quotes,
preflight, submit, cancel, and reconciliation.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_positions import render_position_analytics, render_target_vs_actual
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import (
    cancellation_confirmation,
    money,
    render_broker_gate,
    submission_confirmation,
)
from svyable.sandbox_check import run_sandbox_check


def _load_broker_snapshot(service: DashboardService, settings: TastySettings) -> dict | None:
    if not render_broker_gate(settings):
        return None
    cache_key = f"portfolio_ops_broker_snapshot::{settings.environment}::{service.output_root}"
    refresh = st.button("Refresh Tastytrade snapshot", type="primary")
    if refresh or cache_key not in st.session_state:
        try:
            with st.spinner("Loading Tastytrade account state..."):
                st.session_state[cache_key] = {
                    "loaded_at": datetime.now().isoformat(timespec="seconds"),
                    "data": service.broker_snapshot(),
                }
        except Exception as exc:
            st.error(f"Broker unavailable: {exc}")
            return None
    cached = st.session_state[cache_key]
    st.caption(f"Broker snapshot loaded {cached['loaded_at']} local time.")
    return cached["data"]


def _render_account_header(snapshot: dict, settings: TastySettings) -> None:
    account = snapshot.get("account", {})
    number = str(snapshot.get("account_number", ""))
    masked = f"…{number[-4:]}" if number else "not configured"
    positions = snapshot.get("positions", pd.DataFrame())
    orders = snapshot.get("orders", pd.DataFrame())
    cols = st.columns(6)
    cols[0].metric("Environment", str(snapshot.get("environment", settings.environment)).upper())
    cols[1].metric("Account", masked)
    cols[2].metric("Net liq", money(account.get("equity")))
    cols[3].metric("Cash", money(account.get("cash")))
    cols[4].metric("Maintenance excess", money(account.get("maintenance_excess")))
    cols[5].metric("Positions / orders", f"{0 if positions.empty else len(positions)} / {0 if orders.empty else len(orders)}")


def _render_positions_and_drift(service: DashboardService, snapshot: dict) -> None:
    positions = snapshot.get("positions", pd.DataFrame())
    account = snapshot.get("account", {})
    render_position_analytics(positions)
    if positions.empty:
        return
    try:
        targets = service.target_series()
    except FileNotFoundError:
        targets = pd.Series(dtype=float)
    if targets.empty:
        st.caption("Run `svyable daily` to generate strategy target weights and unlock target-vs-actual drift.")
        return
    render_target_vs_actual(
        positions,
        targets,
        float(account.get("equity")) if account.get("equity") else None,
    )


def _render_rebalance_planner(service: DashboardService, settings: TastySettings) -> None:
    st.caption(
        "The planner uses persisted daily prices, dollar ADV, liquidity masks, current broker positions, "
        "and fresh Tastytrade execution prices. Submission keeps the existing typed safety gates."
    )
    minimum = st.number_input(
        "Minimum order notional", min_value=0.0, value=100.0, step=50.0, key="portfolio_ops_min_order"
    )
    if st.button("Build strategy rebalance plan", type="primary", key="portfolio_ops_build_plan"):
        try:
            st.session_state["portfolio_ops_rebalance_plan"] = service.build_rebalance_plan(
                min_order_notional=float(minimum)
            )
            st.session_state.pop("portfolio_ops_rebalance_preflight", None)
        except Exception as exc:
            st.error(str(exc))

    plan = st.session_state.get("portfolio_ops_rebalance_plan")
    if not plan:
        st.info("Build a plan from latest targets and current Tastytrade positions.")
        return

    cols = st.columns(6)
    cols[0].metric("Orders", len(plan["orders"]))
    cols[1].metric("Safety", "PASS" if plan["safety_complete"] else "BLOCKED")
    cols[2].metric("ADV capped", plan["adv_capped_orders"])
    cols[3].metric("Estimated turnover", money(plan["estimated_turnover"]))
    cols[4].metric("Account equity", money(plan["account"].get("equity")))
    cols[5].metric("Input date", plan["execution_inputs_date"] or "missing")
    st.caption(
        f"ADV window: {plan['adv_window']} trading days | participation cap: "
        f"{plan['adv_participation_cap']:.1%} | expected input date: {plan['expected_inputs_date']}"
    )

    if plan["inputs_stale"]:
        st.error("Execution inputs are stale. Run `svyable daily` before proceeding.")
    for key, label in [
        ("missing_prices", "Missing execution prices"),
        ("missing_adv", "Missing ADV values"),
        ("non_liquid_targets", "Targets fail the liquidity mask"),
    ]:
        values = plan.get(key) or []
        if values:
            st.error(f"{label}: " + ", ".join(values))

    orders = pd.DataFrame(plan["orders"])
    st.dataframe(orders, use_container_width=True, hide_index=True)
    if not plan["orders"]:
        st.success("Portfolio is within the configured order threshold; no orders planned.")
        return
    if not plan["safety_complete"]:
        st.warning("Plan review is available, but broker preflight is disabled until safety checks pass.")
        return

    if st.button("Broker preflight all orders", key="portfolio_ops_preflight"):
        try:
            st.session_state["portfolio_ops_rebalance_preflight"] = service.preflight_plan(plan)
        except Exception as exc:
            st.error(str(exc))
    checks = st.session_state.get("portfolio_ops_rebalance_preflight")
    if not checks:
        return

    table = pd.DataFrame(
        {
            "symbol": [x["intent"]["symbol"] for x in checks],
            "side": [x["intent"]["side"] for x in checks],
            "quantity": [x["intent"]["quantity"] for x in checks],
            "status": [x["status"] for x in checks],
            "warnings": [len(x["warnings"]) for x in checks],
            "errors": [len(x["errors"]) for x in checks],
        }
    )
    st.subheader("Broker preflight")
    st.dataframe(table, use_container_width=True, hide_index=True)
    if any(x["warnings"] or x["errors"] for x in checks):
        st.error("At least one preflight is blocked. Submission is disabled.")
        return
    if not settings.is_test:
        st.info("Production mode remains plan-and-preflight only while the sandbox operating record is established.")
        return

    enabled, confirmation = submission_confirmation(settings, "SUBMIT")
    if st.button("Submit sandbox rebalance orders", disabled=not enabled, type="primary"):
        try:
            result = service.submit_plan(plan, confirmation=confirmation)
            st.success(f"Submission complete: {result['status']}")
            st.json(result)
            st.session_state.pop("portfolio_ops_rebalance_preflight", None)
        except Exception as exc:
            st.error(str(exc))


def _render_order_tools(service: DashboardService, settings: TastySettings, snapshot: dict) -> None:
    orders = snapshot.get("orders", pd.DataFrame())
    st.subheader("Orders today")
    if orders.empty:
        st.info("No orders returned for today.")
    else:
        st.dataframe(orders, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Order status")
        status_id = st.number_input("Order ID", min_value=1, step=1, key="portfolio_ops_status_order_id")
        if st.button("Refresh order status", key="portfolio_ops_refresh_order_status"):
            try:
                st.json(service.order_status(int(status_id)))
            except Exception as exc:
                st.error(str(exc))
    with right:
        st.subheader("Request cancellation")
        cancel_id = st.number_input("Order ID to cancel", min_value=1, step=1, key="portfolio_ops_cancel_order_id")
        enabled, confirmation = cancellation_confirmation(settings)
        if st.button("Request cancellation", disabled=not enabled, type="primary", key="portfolio_ops_cancel_order"):
            try:
                result = service.cancel_order(int(cancel_id), confirmation=confirmation)
                st.warning(f"Cancellation response: {result.get('status', 'requested')}")
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

    st.subheader("Quote lookup")
    symbol = st.text_input("Symbol", value="SPY", key="portfolio_ops_quote_symbol")
    if st.button("Fetch quote", key="portfolio_ops_quote_button"):
        try:
            st.dataframe(pd.DataFrame([service.quote(symbol)]), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))

    st.subheader("Portfolio reconciliation")
    tolerance = st.number_input(
        "Weight drift tolerance",
        min_value=0.001,
        max_value=0.10,
        value=0.01,
        step=0.001,
        format="%.3f",
        key="portfolio_ops_reconcile_tol",
    )
    if st.button("Reconcile broker positions to strategy targets", key="portfolio_ops_reconcile"):
        try:
            result = service.reconcile_now(tolerance_w=float(tolerance))
            if result["status"] == "ok":
                st.success("Broker positions are within tolerance.")
            else:
                st.warning(f"Detected {len(result['drifts'])} position drifts.")
            st.json(result)
        except Exception as exc:
            st.error(str(exc))


def render_portfolio_ops(service: DashboardService, settings: TastySettings) -> None:
    st.subheader("🏦 Tastytrade PM portfolio operations")
    st.caption(
        "Consolidated account, positions, target drift, rebalance planning, broker preflight, "
        "sandbox submission, orders, cancellation, quotes, and reconciliation."
    )
    snapshot = _load_broker_snapshot(service, settings)
    if snapshot is None:
        return

    _render_account_header(snapshot, settings)

    if settings.is_test:
        with st.expander("Sandbox connectivity check", expanded=False):
            st.caption(
                "Validates session, account, positions, quote path, and a one-share dry run. "
                "It never submits an order and refuses production credentials."
            )
            if st.button("Run non-submitting sandbox check", key="portfolio_ops_sandbox_check"):
                try:
                    check = run_sandbox_check(service.broker)
                    if check["status"] == "PASS":
                        st.success("Sandbox connectivity and broker preflight passed.")
                    else:
                        st.warning("Sandbox check returned a blocked result.")
                    st.json(check)
                except Exception as exc:
                    st.error(str(exc))

    positions_tab, rebalance_tab, order_tab = st.tabs(
        ["📍 Positions & drift", "⚖️ Rebalance plan", "🧾 Orders, quote & reconcile"]
    )
    with positions_tab:
        _render_positions_and_drift(service, snapshot)
    with rebalance_tab:
        _render_rebalance_planner(service, settings)
    with order_tab:
        _render_order_tools(service, settings, snapshot)
