"""Broker account, position, order, quote, and reconciliation view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import cancellation_confirmation, money
from svyable.sandbox_check import run_sandbox_check


def render_broker(service: DashboardService, settings: TastySettings) -> None:
    st.caption("Broker state and order controls use the typed `tastytrade>=12` adapter.")
    try:
        snapshot = service.broker_snapshot()
    except Exception as exc:
        st.error(f"Broker unavailable: {exc}")
        return
    account = snapshot["account"]
    number = str(snapshot["account_number"])
    masked = f"…{number[-4:]}" if number else "not configured"
    cols = st.columns(5)
    cols[0].metric("Environment", snapshot["environment"].upper())
    cols[1].metric("Account", masked)
    cols[2].metric("Net liq", money(account.get("equity")))
    cols[3].metric("Cash", money(account.get("cash")))
    cols[4].metric("Maintenance excess", money(account.get("maintenance_excess")))

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

    st.subheader("Positions")
    positions = snapshot["positions"]
    if positions.empty:
        st.info("No positions.")
    else:
        st.dataframe(positions, use_container_width=True, hide_index=True)

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
