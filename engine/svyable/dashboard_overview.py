"""Operations-health view for the Streamlit console."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.dashboard_service import DashboardService


def render_overview(service: DashboardService) -> None:
    snapshot = service.ledger_snapshot()
    health = snapshot["health"]
    last_run = health.get("last_daily_run") or {}
    cols = st.columns(6)
    cols[0].metric("Last daily run", last_run.get("ts", "never"))
    cols[1].metric("Run status", last_run.get("status", "—"))
    cols[2].metric("Tracking days", health.get("tracking_days", 0))
    cols[3].metric("Mean |drift|", f"{health.get('drift_bps_mean_abs', '—')} bps")
    cols[4].metric("Warnings 7d", health.get("warnings_7d", 0))
    cols[5].metric("Critical 7d", health.get("critical_7d", 0))

    equity = snapshot["equity"].copy()
    if not equity.empty:
        equity["d"] = pd.to_datetime(equity["d"])
        equity = equity.set_index("d")
        columns = [c for c in ["shadow_nav", "paper_equity"] if c in equity]
        if columns:
            st.subheader("Shadow and paper equity")
            st.line_chart(equity[columns])
        if "drift_bps" in equity:
            st.subheader("Paper vs shadow return drift")
            st.line_chart(equity[["drift_bps"]])

    left, right = st.columns(2)
    with left:
        st.subheader("Recent runs")
        st.dataframe(snapshot["runs"], use_container_width=True, hide_index=True)
    with right:
        st.subheader("Open warnings")
        warnings = snapshot["warnings"]
        if warnings.empty:
            st.success("No warnings in the selected window.")
        else:
            st.dataframe(warnings, use_container_width=True, hide_index=True)
