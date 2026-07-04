"""Factor maturity, IC reliability, and promotion/quarantine view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.dashboard_service import DashboardService
from svyable.factor_monitor import load_factor_monitor
from svyable.strategy_registry import list_strategies


def _strategy_factor_usage() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return factor-by-strategy usage and per-strategy coverage tables."""
    rows = []
    strategy_rows = []
    specs = list_strategies(include_experimental=True)
    for spec in specs:
        factor_names = tuple(spec.factor_names)
        strategy_rows.append(
            {
                "strategy_id": spec.strategy_id,
                "name": spec.display_name,
                "maturity": spec.maturity,
                "enabled_by_default": spec.enabled_by_default,
                "family": spec.family,
                "factors": len(factor_names),
                "factor_names": factor_names,
            }
        )
        for factor in factor_names:
            rows.append(
                {
                    "factor": factor,
                    "strategy_id": spec.strategy_id,
                    "strategy_name": spec.display_name,
                    "maturity": spec.maturity,
                    "enabled_by_default": spec.enabled_by_default,
                }
            )
    usage = pd.DataFrame(rows)
    strategies = pd.DataFrame(strategy_rows).set_index("strategy_id")
    return usage, strategies


def render_factor_governance(service: DashboardService) -> None:
    monitor = load_factor_monitor(service)
    catalog = monitor["catalog"]
    sleeves = monitor["sleeves"]
    factors = monitor["factors"]
    usage, strategy_usage = _strategy_factor_usage()

    if catalog.empty and not factors:
        st.info("No factor-health artifacts yet. Run `svyable daily` first.")
        return

    st.caption(
        "IC is purged, evaluated only on eligible pairwise observations, and "
        "adjusted for uncertainty, hit rate, and coverage. Shadow factors have no floor. "
        "Registry coverage now shows which strategies actually depend on each factor."
    )

    if not catalog.empty:
        catalog_view = catalog.copy()
        if not usage.empty:
            factor_counts = usage.groupby("factor")["strategy_id"].nunique()
            default_counts = (
                usage[usage["enabled_by_default"]]
                .groupby("factor")["strategy_id"]
                .nunique()
            )
            catalog_view["strategy_count"] = catalog_view.index.map(factor_counts).fillna(0).astype(int)
            catalog_view["default_strategy_count"] = (
                catalog_view.index.map(default_counts).fillna(0).astype(int)
            )
        else:
            catalog_view["strategy_count"] = 0
            catalog_view["default_strategy_count"] = 0

        stages = catalog_view["stage"].value_counts()
        used = int((catalog_view["strategy_count"] > 0).sum())
        cols = st.columns(5)
        cols[0].metric("Catalog size", len(catalog_view))
        cols[1].metric("Proven", int(stages.get("proven", 0)))
        cols[2].metric("Shadow", int(stages.get("shadow", 0)))
        cols[3].metric("Used by registry", used)
        cols[4].metric("Unused", int(len(catalog_view) - used))
        with st.expander("Factor catalog"):
            st.dataframe(catalog_view, use_container_width=True)

    if not usage.empty:
        st.subheader("Registry factor usage")
        factor_usage = (
            usage.groupby("factor")
            .agg(
                strategy_count=("strategy_id", "nunique"),
                default_strategy_count=("enabled_by_default", "sum"),
                strategies=("strategy_id", lambda values: ", ".join(sorted(set(values)))),
            )
            .sort_values(["default_strategy_count", "strategy_count"], ascending=False)
        )
        st.dataframe(factor_usage, use_container_width=True)
        with st.expander("Strategy coverage"):
            if not catalog.empty:
                stage = catalog["stage"].to_dict()
                coverage = strategy_usage.copy()
                coverage["proven_factors"] = [
                    sum(1 for factor in factors_used if stage.get(factor) == "proven")
                    for factors_used in coverage["factor_names"]
                ]
                coverage["shadow_factors"] = coverage["factors"] - coverage["proven_factors"]
                coverage = coverage.drop(columns=["factor_names"])
                st.dataframe(coverage, use_container_width=True)
            else:
                st.dataframe(strategy_usage.drop(columns=["factor_names"], errors="ignore"), use_container_width=True)

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
