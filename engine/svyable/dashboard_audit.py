"""Order, fill-quality, event, and append-only broker audit view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.dashboard_service import DashboardService
from svyable.ledger import Ledger


def render_audit(service: DashboardService) -> None:
    snapshot = service.ledger_snapshot()

    st.subheader("Ledger orders")
    st.dataframe(snapshot["orders"], use_container_width=True, hide_index=True)

    st.subheader("Delayed fill recovery")
    st.caption(
        "Recent broker order IDs are re-queried and transactions are inserted "
        "idempotently. This also captures later partial fills."
    )
    days = st.number_input(
        "Backfill lookback days",
        min_value=1,
        max_value=30,
        value=5,
        step=1,
    )
    if st.button("Backfill Tastytrade trade transactions"):
        try:
            result = service.backfill_execution_quality(int(days))
            st.session_state["fill_backfill_result"] = result
            if result["status"] == "no_orders":
                st.info("No recent broker-linked orders were found.")
            else:
                st.success(
                    f"Checked {result['orders_checked']} orders, found "
                    f"{result['fills_found']} transactions, and recorded "
                    f"{result['fills_recorded']} new rows."
                )
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("fill_backfill_result"):
        with st.expander("Latest backfill result"):
            st.json(st.session_state["fill_backfill_result"])

    ledger = Ledger(service.ledger_path)
    try:
        fills = ledger.execution_quality_frame(500)
    finally:
        ledger.close()

    st.subheader("Execution quality")
    st.caption(
        f"Signed slippage alert thresholds: warning "
        f"{service.settings.slippage_warn_bps:.1f} bps, critical "
        f"{service.settings.slippage_critical_bps:.1f} bps. Positive is worse."
    )
    if fills.empty:
        st.info("No broker fill transactions have been recorded yet.")
    else:
        scored = fills["slippage_bps"].dropna().astype(float)
        cols = st.columns(4)
        cols[0].metric("Fills", len(fills))
        cols[1].metric(
            "Notional",
            f"${(fills['qty'].fillna(0) * fills['fill_price'].fillna(0)).sum():,.2f}",
        )
        cols[2].metric(
            "Mean |slippage|",
            f"{scored.abs().mean():.2f} bps" if len(scored) else "—",
        )
        cols[3].metric(
            "Fees",
            f"${fills['fees'].fillna(0).sum():,.4f}",
        )
        st.dataframe(fills, use_container_width=True, hide_index=True)
        if len(scored):
            chart = fills.dropna(subset=["slippage_bps"]).copy()
            chart["ts"] = pd.to_datetime(chart["ts"])
            chart = chart.sort_values("ts").set_index("ts")
            st.line_chart(chart[["slippage_bps"]])

    st.subheader("Operational events")
    st.dataframe(snapshot["events"], use_container_width=True, hide_index=True)

    st.subheader("Append-only Tastytrade audit")
    audit = service.audit_tail(200)
    if audit.empty:
        st.info("No broker audit records yet.")
    else:
        st.dataframe(audit, use_container_width=True, hide_index=True)
