"""Factor & sleeve intelligence view for the Streamlit console.

Ports the highest-value ideas from the Q23 factor pages onto Svyable's own
sleeve/factor artifacts (`sleeve_health.csv`, `factor_health_*.csv`,
`ic_health.csv`, `sleeve_weights.csv`, `factor_catalog.csv`). It answers three
questions the agentic book turns on: which *sleeves* the system currently
trusts, which *factors* are actually earning their weight, and how sleeve signal
quality has evolved.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import render_figure

_HEALTH_COLS = ["horizon", "mean_ic", "ic_vol", "ic_ir", "hit_rate", "observations", "weight", "stage"]


def _combined_factor_health(factor_health: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Flatten per-sleeve factor-health frames into one labelled table.

    Each sleeve frame is indexed by factor and may carry multiple horizons; we
    keep the shortest horizon per factor so one row means one live signal.
    """
    frames = []
    for sleeve, frame in factor_health.items():
        if frame.empty:
            continue
        block = frame.copy()
        block.insert(0, "sleeve", sleeve)
        block["factor"] = block.index.astype(str)
        frames.append(block.reset_index(drop=True))
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "horizon" in combined.columns:
        combined = combined.sort_values("horizon").drop_duplicates(["sleeve", "factor"], keep="first")
    return combined


def _render_sleeve_intelligence(snapshot: dict) -> None:
    sleeve_health = snapshot["sleeve_health"]
    if sleeve_health.empty:
        st.info("No sleeve health yet. Run `svyable daily` to populate `sleeve_health.csv`.")
        return

    health = sleeve_health.copy()
    if "sleeve" not in health.columns:
        health = health.reset_index().rename(columns={health.index.name or "index": "sleeve"})

    best = health.sort_values("ic_ir", ascending=False).iloc[0]
    cols = st.columns(4)
    cols[0].metric("Sleeves live", len(health))
    cols[1].metric("Top sleeve", str(best["sleeve"]), help="Highest information ratio this window.")
    cols[2].metric("Top IC-IR", f"{float(best['ic_ir']):.2f}")
    trusted = health.loc[health["weight"].astype(float).idxmax(), "sleeve"]
    cols[3].metric("Most-trusted sleeve", str(trusted), help="Largest current trust weight.")

    st.subheader("Sleeve health")
    st.caption(
        "IC-IR is mean IC / IC volatility — signal quality per unit of noise. The "
        "stress multiplier scales a sleeve's risk budget when its regime turns hostile."
    )
    st.dataframe(
        health.set_index("sleeve").style.background_gradient(
            subset=[c for c in ["ic_ir", "hit_rate", "weight"] if c in health.columns],
            cmap="RdYlGn",
        ),
        use_container_width=True,
    )

    ic_ir = health.set_index("sleeve")["ic_ir"].astype(float)
    render_figure(charts.signed_bar_chart(ic_ir, title="Sleeve information ratio", xlabel="IC-IR"))

    sleeve_weights = snapshot["sleeve_weights"]
    if not sleeve_weights.empty:
        render_figure(charts.sleeve_trust_area_chart(sleeve_weights))

    ic_health = snapshot["ic_health"]
    if not ic_health.empty:
        st.subheader("Sleeve smoothed IC over time")
        frame = ic_health.copy()
        frame.index = pd.to_datetime(frame.index, errors="coerce")
        st.line_chart(frame[~frame.index.isna()].tail(252))


def _render_factor_library(snapshot: dict) -> None:
    combined = _combined_factor_health(snapshot["factor_health"])
    if combined.empty:
        st.info("No per-factor health yet. Run `svyable daily` to populate `factor_health_*.csv`.")
        return

    top = st.columns(4)
    top[0].metric("Factors live", combined["factor"].nunique())
    if "ic_ir" in combined.columns:
        strongest = combined.loc[combined["ic_ir"].astype(float).idxmax()]
        weakest = combined.loc[combined["ic_ir"].astype(float).idxmin()]
        top[1].metric("Strongest factor", str(strongest["factor"]), f"{float(strongest['ic_ir']):.2f} IC-IR")
        top[2].metric("Weakest factor", str(weakest["factor"]), f"{float(weakest['ic_ir']):.2f} IC-IR")
    if "stage" in combined.columns:
        top[3].metric("Proven", int((combined["stage"] == "proven").sum()))

    st.subheader("Factor library health")
    display_cols = ["sleeve", "factor"] + [c for c in _HEALTH_COLS if c in combined.columns and c != "horizon"]
    ordered = combined.sort_values("ic_ir", ascending=False) if "ic_ir" in combined.columns else combined
    st.dataframe(ordered[display_cols], use_container_width=True, hide_index=True)

    if "ic_ir" in combined.columns:
        ranked = combined.set_index("factor")["ic_ir"].astype(float).sort_values()
        n = st.slider("Factors to show (by |IC-IR| extremes)", 6, min(30, len(ranked)), min(15, len(ranked)))
        half = n // 2
        extremes = pd.concat([ranked.head(half), ranked.tail(n - half)])
        render_figure(charts.signed_bar_chart(extremes, title="Factor information ratio (best & worst)", xlabel="IC-IR"))


def _render_sleeve_factor_weights(snapshot: dict) -> None:
    factor_weights = snapshot["factor_weights"]
    if not factor_weights:
        st.info("No per-sleeve factor weights yet.")
        return
    sleeve = st.selectbox("Sleeve", sorted(factor_weights.keys()))
    frame = factor_weights.get(sleeve, pd.DataFrame())
    if frame.empty:
        st.caption("No weights for this sleeve.")
        return
    latest = frame.iloc[-1].astype(float)
    latest = latest[latest.abs() > 1e-9].sort_values(ascending=False)
    st.caption(f"Current within-sleeve factor allocation for **{sleeve}** ({len(latest)} active factors).")
    st.bar_chart(latest.rename("weight"))


def render_factors(service: DashboardService) -> None:
    snapshot = service.strategy_snapshot()
    if snapshot["run_dir"] is None:
        st.info("No strategy artifacts yet. Run `svyable daily` first.")
        return

    st.caption(
        "Sleeves are factor families; each sleeve's trust weight is earned by its "
        "recent information ratio, and each factor's weight is earned within its "
        "sleeve. This is where alpha decay shows up first."
    )

    sleeve_tab, library_tab, weights_tab, catalog_tab = st.tabs(
        ["🧭 Sleeves", "🔬 Factor library", "⚖️ Sleeve weights", "📚 Catalog"]
    )
    with sleeve_tab:
        _render_sleeve_intelligence(snapshot)
    with library_tab:
        _render_factor_library(snapshot)
    with weights_tab:
        _render_sleeve_factor_weights(snapshot)
    with catalog_tab:
        catalog = snapshot["factor_catalog"]
        if catalog.empty:
            st.info("No factor catalog found.")
        else:
            frame = catalog.reset_index() if catalog.index.name else catalog
            summary = (
                frame.groupby(["sleeve", "stage"]).size().rename("count").reset_index()
                if {"sleeve", "stage"} <= set(frame.columns)
                else pd.DataFrame()
            )
            if not summary.empty:
                st.caption("Registered factor lineage by sleeve and maturity stage.")
                st.dataframe(
                    summary.pivot(index="sleeve", columns="stage", values="count").fillna(0).astype(int),
                    use_container_width=True,
                )
            st.dataframe(frame, use_container_width=True, hide_index=True)
