"""Order ledger and append-only broker audit view."""

from __future__ import annotations

import streamlit as st

from svyable.dashboard_service import DashboardService


def render_audit(service: DashboardService) -> None:
    snapshot = service.ledger_snapshot()
    st.subheader("Ledger orders")
    st.dataframe(snapshot["orders"], use_container_width=True, hide_index=True)
    st.subheader("Operational events")
    st.dataframe(snapshot["events"], use_container_width=True, hide_index=True)
    st.subheader("Append-only Tastytrade audit")
    audit = service.audit_tail(200)
    if audit.empty:
        st.info("No broker audit records yet.")
    else:
        st.dataframe(audit, use_container_width=True, hide_index=True)
