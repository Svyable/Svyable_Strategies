"""Strategy-artifact view for the Streamlit console."""

from __future__ import annotations

import streamlit as st

from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import percent


def render_strategy(service: DashboardService) -> None:
    snapshot = service.strategy_snapshot()
    if snapshot["run_dir"] is None:
        st.info("No strategy artifacts yet. Run `svyable daily` first.")
        return
    meta, weights = snapshot["meta"], snapshot["weights"].copy()
    budget, pnl = snapshot["budget"], snapshot["pnl"]
    st.caption(f"Latest artifact directory: `{snapshot['run_dir']}`")
    cols = st.columns(5)
    cols[0].metric("Config", meta.get("config_hash", "—"))
    cols[1].metric("Data status", (meta.get("data") or {}).get("status", "—"))
    cols[2].metric("Data date", (meta.get("data") or {}).get("last_date", "—"))
    cols[3].metric("Positions", len(weights))
    gross = float(budget.iloc[-1, 0]) if not budget.empty else None
    cols[4].metric("Gross budget", f"{gross:.2f}x" if gross else "—")

    if not weights.empty:
        column = "weight" if "weight" in weights.columns else weights.columns[0]
        weights = weights.rename(columns={column: "weight"}).sort_values("weight", ascending=False)
        weights["weight_pct"] = weights["weight"].map(percent)
        st.subheader("Current target portfolio")
        st.dataframe(weights[["weight", "weight_pct"]], use_container_width=True)
        st.bar_chart(weights[["weight"]].head(30))

    left, right = st.columns(2)
    with left:
        sleeve = snapshot["sleeve_weights"]
        st.subheader("Sleeve trust")
        if not sleeve.empty:
            latest = sleeve.iloc[-1].sort_values(ascending=False).rename("weight")
            st.dataframe(latest.to_frame(), use_container_width=True)
            st.bar_chart(latest)
    with right:
        ic = snapshot["ic_health"]
        st.subheader("IC health")
        if not ic.empty:
            latest = ic.iloc[-1].sort_values(ascending=False).rename("smoothed_ic")
            st.dataframe(latest.to_frame(), use_container_width=True)
            st.bar_chart(latest)

    if not pnl.empty and "net_ret" in pnl:
        st.subheader("Recent shadow NAV")
        st.line_chart((1.0 + pnl["net_ret"].fillna(0.0)).cumprod())
    with st.expander("Factor weights"):
        for name, frame in snapshot["factor_weights"].items():
            st.markdown(f"**{name}**")
            st.dataframe(frame.tail(10), use_container_width=True)
    with st.expander("Morning report", expanded=True):
        st.markdown(snapshot["report"] or "_No morning report found._")
    with st.expander("Run metadata"):
        st.json(meta)
