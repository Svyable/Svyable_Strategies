"""Factor maturity, IC reliability, and promotion/quarantine view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable.alpha_gui_model import alpha_dashboard_metrics, alpha_factor_table, alpha_strategy_cards
from svyable.dashboard_service import DashboardService
from svyable.factor_library import factor_metadata
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
                "regime_profile": spec.regime_profile,
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


def _catalog_with_fallback(catalog: pd.DataFrame) -> pd.DataFrame:
    """Use live registry metadata when no factor-health artifact exists yet."""
    if catalog is not None and not catalog.empty:
        return catalog.copy()
    return factor_metadata().copy()


def _strategy_coverage(strategy_usage: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    if strategy_usage.empty:
        return strategy_usage
    stage = catalog["stage"].to_dict() if "stage" in catalog.columns else {}
    coverage = strategy_usage.copy()
    coverage["proven_factors"] = [
        sum(1 for factor in factors_used if stage.get(factor) == "proven")
        for factors_used in coverage["factor_names"]
    ]
    coverage["shadow_factors"] = coverage["factors"] - coverage["proven_factors"]
    coverage["shadow_ratio"] = (coverage["shadow_factors"] / coverage["factors"].replace(0, pd.NA)).fillna(0.0).round(3)
    coverage["frontier_watch"] = coverage["shadow_ratio"] >= 0.40
    return coverage.drop(columns=["factor_names"])


def _render_alpha_spotlight(catalog: pd.DataFrame) -> None:
    st.subheader("Alpha Catalyst cockpit")
    st.caption(
        "New alpha-family watchlist: residual Alpha Catalyst plus Tape Acceleration. "
        "This surface is for factor/strategy review only; candidate selection still happens through the normal board and PM harness."
    )
    metrics = alpha_dashboard_metrics(catalog)
    cols = st.columns(5)
    cols[0].metric("Alpha factors", metrics["alpha_factor_count"])
    cols[1].metric("Alpha strategies", metrics["alpha_strategy_count"])
    cols[2].metric("Shadow factors", metrics["shadow_factors"])
    cols[3].metric("Proven factors", metrics["proven_factors"])
    cols[4].metric("Avg shadow ratio", f"{metrics['avg_shadow_ratio']:.0%}")

    strategies = alpha_strategy_cards(catalog)
    if not strategies.empty:
        st.markdown("**Alpha strategy cards**")
        st.dataframe(strategies, use_container_width=True, hide_index=True)
        chart = strategies.set_index("strategy_id")[["alpha_family_factors", "total_factors", "shadow_factors"]]
        st.bar_chart(chart, use_container_width=True)

    factors = alpha_factor_table(catalog)
    if not factors.empty:
        left, right = st.columns([2, 1])
        with left:
            st.markdown("**Alpha factor map**")
            st.dataframe(factors, use_container_width=True, hide_index=True)
        with right:
            counts = factors.groupby(["family", "stage"]).size().unstack(fill_value=0)
            st.markdown("**Family maturity mix**")
            st.bar_chart(counts, use_container_width=True)


def render_factor_governance(service: DashboardService) -> None:
    monitor = load_factor_monitor(service)
    catalog = _catalog_with_fallback(monitor["catalog"])
    sleeves = monitor["sleeves"]
    factors = monitor["factors"]
    usage, strategy_usage = _strategy_factor_usage()

    st.caption(
        "IC is purged, evaluated only on eligible pairwise observations, and "
        "adjusted for uncertainty, hit rate, and coverage. Shadow factors have no floor. "
        "Registry coverage shows which strategies actually depend on each factor, even before factor-health artifacts exist."
    )

    _render_alpha_spotlight(catalog)

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
        with st.expander("Strategy coverage", expanded=True):
            coverage = _strategy_coverage(strategy_usage, catalog)
            if not coverage.empty:
                st.caption("Frontier watch flags strategies whose factor pack is at least 40% shadow/incubation factors.")
                st.dataframe(coverage.sort_values(["frontier_watch", "shadow_ratio", "factors"], ascending=False), use_container_width=True)
            else:
                st.dataframe(strategy_usage.drop(columns=["factor_names"], errors="ignore"), use_container_width=True)

    if not sleeves.empty:
        st.subheader("Sleeve reliability")
        st.dataframe(sleeves, use_container_width=True)

    st.subheader("Factor health")
    if not factors:
        st.info("No factor-health artifacts yet. Registry and maturity coverage are shown from live metadata; run `svyable daily` for IC health.")
        return
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
