"""Strategy rebalance planning and sandbox execution view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import money, submission_confirmation


def render_rebalance(service: DashboardService, settings: TastySettings) -> None:
    st.warning(
        "The UI planner omits ADV caps. Production bulk submission is disabled; "
        "use the CLI rebalancer as the ADV-capped reference path."
    )
    minimum = st.number_input(
        "Minimum order notional", min_value=0.0, value=100.0, step=50.0
    )
    if st.button("Build strategy rebalance plan", type="primary"):
        try:
            st.session_state["rebalance_plan"] = service.build_rebalance_plan(
                min_order_notional=float(minimum)
            )
            st.session_state.pop("rebalance_preflight", None)
        except Exception as exc:
            st.error(str(exc))

    plan = st.session_state.get("rebalance_plan")
    if not plan:
        st.info("Build a plan from the latest targets and current broker positions.")
        return
    cols = st.columns(4)
    cols[0].metric("Orders", len(plan["orders"]))
    cols[1].metric("Estimated turnover", money(plan["estimated_turnover"]))
    cols[2].metric("Account equity", money(plan["account"].get("equity")))
    cols[3].metric("Missing quotes", len(plan["missing_prices"]))
    st.dataframe(pd.DataFrame(plan["orders"]), use_container_width=True, hide_index=True)
    if plan["missing_prices"]:
        st.error("Missing execution prices: " + ", ".join(plan["missing_prices"]))
        return

    if st.button("Broker preflight all orders"):
        try:
            st.session_state["rebalance_preflight"] = service.preflight_plan(plan)
        except Exception as exc:
            st.error(str(exc))
    checks = st.session_state.get("rebalance_preflight")
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
    enabled, confirmation = submission_confirmation(settings, "SUBMIT")
    if st.button("Submit sandbox rebalance orders", disabled=not enabled, type="primary"):
        try:
            result = service.submit_plan(plan, confirmation=confirmation)
            st.success(f"Submission complete: {result['status']}")
            st.json(result)
        except Exception as exc:
            st.error(str(exc))
