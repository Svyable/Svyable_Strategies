"""Broker account, position, order, quote, and reconciliation view."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_positions import (
    render_position_analytics,
    render_target_vs_actual,
)
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import cancellation_confirmation, money, render_broker_gate
from svyable.sandbox_check import run_sandbox_check


def render_broker(service: DashboardService, settings: TastySettings) -> None:
    if not render_broker_gate(settings):
        return
    st.caption("Broker state and order controls use the typed `tastytrade>=12` adapter.")
    cache_key = f"broker_snapshot::{settings.environment}::{service.output_root}"
    refresh = st.button("Refresh broker account snapshot", type="primary")
    if refresh or cache_key not in st.session_state:
        try:
            with st.spinner("Loading Tastytrade account state..."):
                st.session_state[cache_key] = {
                    "loaded_at": datetime.now().isoformat(timespec="seconds"),
                    "data": service.broker_snapshot(),
                }
        except Exception as exc:
            st.error(f"Broker unavailable: {exc}")
            return

    cached = st.session_state[cache_key]
    snapshot = cached["data"]
    st.caption(f"Snapshot loaded {cached['loaded_at']} local time.")
    account = snapshot["account"]
    number = str(snapshot["account_number"])
    masked = f"…{number[-4:]}" if number else "not configured"
    cols = st.columns(5)
    cols[0].metric("Environment", snapshot["environment"].upper())
    cols[1].metric("Account", masked)
    cols[2].metric(
        "Net liq",
        money(account.get("equity")),
        help="Net liquidating value — total account value if all positions closed now.",
    )
    cols[3].metric("Cash", money(account.get("cash")), help="Settled cash balance.")
    cols[4].metric(
        "Maintenance excess",
        money(account.get("maintenance_excess")),
        help="Buying power above the maintenance-margin requirement; negative risks a call.",
    )

    st.subheader("Sandbox connectivity check")
    st.caption(
        "Validates the session, account, positions, quote path, and a one-share broker "
        "dry run. It never submits an order and refuses production credentials."
    )
    if not settings.is_test:
        st.info("Disabled because the configured session is not a sandbox session.")
    elif st.button("Run non-submitting sandbox check"):
        try:
            check = run_sandbox_check(service.broker)
            if check["status"] == "PASS":
                st.success("Sandbox connectivity and broker preflight passed.")
            else:
                st.warning("Sandbox check returned a blocked result.")
            st.json(check)
        except Exception as exc:
            st.error(str(exc))

    positions = snapshot["positions"]
    render_position_analytics(positions)

    if not positions.empty:
        try:
            targets = service.target_series()
        except FileNotFoundError:
            targets = None
        if targets is not None and not targets.empty:
            net_liq = account.get("equity")
            render_target_vs_actual(
                positions, targets, float(net_liq) if net_liq else None
            )
        else:
            st.caption(
                "Run `svyable daily` to generate strategy target weights and unlock the "
                "target-vs-actual drift view here."
            )

    st.subheader("Orders today")
    orders = snapshot["orders"]
    if orders.empty:
        st.info("No orders returned for today.")
    else:
        st.dataframe(orders, use_container_width=True, hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Order status")
        status_id = st.number_input(
            "Order ID", min_value=1, step=1, key="broker_status_order_id"
        )
        if st.button("Refresh order status"):
            try:
                st.json(service.order_status(int(status_id)))
            except Exception as exc:
                st.error(str(exc))
    with right:
        st.subheader("Request cancellation")
        cancel_id = st.number_input(
            "Order ID to cancel", min_value=1, step=1, key="broker_cancel_order_id"
        )
        enabled, confirmation = cancellation_confirmation(settings)
        if st.button("Request cancellation", disabled=not enabled, type="primary"):
            try:
                result = service.cancel_order(int(cancel_id), confirmation=confirmation)
                st.session_state.pop(cache_key, None)
                st.warning(f"Cancellation response: {result.get('status', 'requested')}")
                st.json(result)
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
    )
    if st.button("Reconcile broker positions to strategy targets"):
        try:
            result = service.reconcile_now(tolerance_w=float(tolerance))
            if result["status"] == "ok":
                st.success("Broker positions are within tolerance.")
            else:
                st.warning(f"Detected {len(result['drifts'])} position drifts.")
            st.json(result)
        except Exception as exc:
            st.error(str(exc))

    st.subheader("Quote lookup")
    symbol = st.text_input("Symbol", value="SPY", key="broker_quote_symbol")
    if st.button("Fetch quote", key="broker_quote_button"):
        try:
            st.dataframe(
                pd.DataFrame([service.quote(symbol)]),
                use_container_width=True,
                hide_index=True,
            )
        except Exception as exc:
            st.error(str(exc))
