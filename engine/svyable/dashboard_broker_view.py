"""Read-only broker account, position, order, and quote view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import money


def render_broker(service: DashboardService) -> None:
    st.caption("Read-only broker state from the typed `tastytrade>=12` SDK adapter.")
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
