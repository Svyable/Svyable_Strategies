"""Strategy rebalance planning and sandbox execution view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import money, submission_confirmation


def render_rebalance(service: DashboardService, settings: TastySettings) -> None:
    st.caption(
        "The planner uses persisted daily prices, dollar ADV, and the liquidity mask, "
        "then refreshes execution prices from Tastytrade."
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

    cols = st.columns(6)
    cols[0].metric("Orders", len(plan["orders"]))
    cols[1].metric("ADV capped", plan["adv_capped_orders"])
    cols[2].metric("Estimated turnover", money(plan["estimated_turnover"]))
    cols[3].metric("Account equity", money(plan["account"].get("equity")))
    cols[4].metric("Input date", plan["execution_inputs_date"] or "missing")
    cols[5].metric("Safety", "PASS" if plan["safety_complete"] else "BLOCKED")
    st.caption(
        f"ADV window: {plan['adv_window']} trading days | "
        f"participation cap: {plan['adv_participation_cap']:.1%} | "
        f"expected input date: {plan['expected_inputs_date']}"
    )

    if plan["inputs_stale"]:
        st.error("Execution inputs are stale. Run `svyable daily` before proceeding.")
    if plan["missing_prices"]:
        st.error("Missing execution prices: " + ", ".join(plan["missing_prices"]))
    if plan["missing_adv"]:
        st.error("Missing ADV values: " + ", ".join(plan["missing_adv"]))
    if plan["non_liquid_targets"]:
        st.error(
            "Targets fail the liquidity mask: " + ", ".join(plan["non_liquid_targets"])
        )

    orders = pd.DataFrame(plan["orders"])
    st.dataframe(orders, use_container_width=True, hide_index=True)
    if not plan["orders"]:
        st.success("Portfolio is within the configured order threshold; no orders planned.")
        return
    if not plan["safety_complete"]:
        st.warning("Plan review is available, but broker preflight is disabled.")
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
    if not settings.is_test:
        st.info(
            "Production mode remains plan-and-preflight only in Streamlit while the "
            "sandbox operating record is established."
        )
        return

    enabled, confirmation = submission_confirmation(settings, "SUBMIT")
    if st.button("Submit sandbox rebalance orders", disabled=not enabled, type="primary"):
        try:
            result = service.submit_plan(plan, confirmation=confirmation)
            st.success(f"Submission complete: {result['status']}")
            st.json(result)
            st.session_state.pop("rebalance_preflight", None)
        except Exception as exc:
            st.error(str(exc))
