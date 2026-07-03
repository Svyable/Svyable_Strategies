"""Factor maturity, IC reliability, and promotion/quarantine view."""

from __future__ import annotations

import streamlit as st

from svyable.dashboard_service import DashboardService
from svyable.factor_monitor import load_factor_monitor


def render_factor_governance(service: DashboardService) -> None:
    monitor = load_factor_monitor(service)
    catalog = monitor["catalog"]
    sleeves = monitor["sleeves"]
    factors = monitor["factors"]

    if catalog.empty and not factors:
        st.info("No factor-health artifacts yet. Run `svyable daily` first.")
        return

    st.caption(
        "IC is purged, evaluated only on eligible pairwise observations, and "
        "adjusted for uncertainty, hit rate, and coverage. Shadow factors have no floor."
    )

    if not catalog.empty:
        stages = catalog["stage"].value_counts()
        cols = st.columns(3)
        cols[0].metric("Catalog size", len(catalog))
        cols[1].metric("Proven", int(stages.get("proven", 0)))
        cols[2].metric("Shadow", int(stages.get("shadow", 0)))
        with st.expander("Factor catalog"):
            st.dataframe(catalog, use_container_width=True)

    if not sleeves.empty:
        st.subheader("Sleeve reliability")
        st.dataframe(sleeves, use_container_width=True)

    st.subheader("Factor health")
    for sleeve_name, frame in factors.items():
        st.markdown(f"**{sleeve_name.title()}**")
        if frame.empty:
            st.info("No factor-health artifact available.")
            continue
        state_counts = frame["pm_state"].value_counts().to_dict()
        st.caption(", ".join(f"{key}: {value}" for key, value in state_counts.items()))
        columns = [
            name
            for name in [
                "stage",
                "pm_state",
                "weight",
                "mean_ic",
                "ic_vol",
                "ic_ir",
                "hit_rate",
                "observations",
                "coverage",
                "lineage",
            ]
            if name in frame.columns
        ]
        table = frame[columns]
        if "weight" in table:
            table = table.sort_values("weight", ascending=False)
        st.dataframe(table, use_container_width=True)
