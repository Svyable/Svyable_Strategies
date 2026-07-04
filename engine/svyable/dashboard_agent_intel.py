"""Streamlit surface for selection meta diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from svyable.agent_pm_harness import render_agent_memo, write_agent_pm_pack
from svyable.dashboard_ui import percent


def _load_latest_context(output_root: str | Path) -> dict[str, Any]:
    path = Path(output_root) / "strategy_selection" / "latest_agent_context.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        st.warning(f"Latest context is malformed: {path}")
        return {}


def _num(value: Any, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if suffix == "%":
        return percent(number)
    return f"{number:.3f}{suffix}"


def _render_tree(trace: dict[str, Any]) -> None:
    score = trace.get("selected_score_breakdown", {}) or {}
    nodes = pd.DataFrame(trace.get("selected_decision_nodes", []))
    cols = st.columns(5)
    cols[0].metric("Focus", trace.get("selected_candidate_id", "—"))
    cols[1].metric("Expected alpha", _num(score.get("expected_alpha_bps"), " bps"))
    cols[2].metric("Cost", _num(score.get("estimated_cost_bps"), " bps"))
    cols[3].metric("Risk penalty", _num(score.get("risk_penalty_bps"), " bps"))
    cols[4].metric("Utility", _num(score.get("utility_bps"), " bps"))
    st.caption(score.get("formula", "expected alpha minus costs and penalties"))
    if nodes.empty:
        st.info("No gate table available yet.")
    else:
        st.dataframe(nodes, use_container_width=True, hide_index=True)


def _render_regime(trace: dict[str, Any]) -> None:
    regime = trace.get("visible_regime", {}) or {}
    probs = pd.Series(regime.get("probabilities", {}), dtype=float)
    cols = st.columns(2)
    cols[0].metric("Visible regime", regime.get("state", "unknown"))
    cols[1].metric("States", len(probs))
    if not probs.empty:
        st.bar_chart(probs)
    for item in regime.get("drivers", []):
        st.caption(f"• {item}")


def _render_weights(trace: dict[str, Any]) -> None:
    provenance = trace.get("weight_provenance", {}) or {}
    cols = st.columns(4)
    cols[0].metric("Status", provenance.get("status", "—"))
    cols[1].metric("Gross", _num(provenance.get("gross"), "%"))
    cols[2].metric("Net", _num(provenance.get("net"), "%"))
    cols[3].metric("Effective N", provenance.get("effective_n", "—"))
    st.caption(provenance.get("provenance", "Weights are read from the selected candidate artifact."))
    weights = pd.Series(provenance.get("top_weights", {}), dtype=float)
    if not weights.empty:
        st.dataframe(weights.rename("weight").to_frame().style.format({"weight": "{:.2%}"}), use_container_width=True)


def _render_ranked(trace: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for item in trace.get("ranked_candidate_trace", []):
        score = item.get("score_breakdown", {}) or {}
        rows.append({
            "candidate_id": item.get("candidate_id"),
            "strategy_id": item.get("strategy_id"),
            "action": item.get("action"),
            "eligible": item.get("eligible"),
            "expected_alpha_bps": score.get("expected_alpha_bps"),
            "cost_bps": score.get("estimated_cost_bps"),
            "turnover_penalty_bps": score.get("turnover_penalty_bps"),
            "risk_penalty_bps": score.get("risk_penalty_bps"),
            "utility_bps": score.get("utility_bps"),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("No ranked trace available.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)


def _render_context(context: dict[str, Any]) -> None:
    summary = context.get("summary", {})
    trace = context.get("meta_decision_trace", {})
    rails = context.get("rails", {})
    health = context.get("focus_candidate_artifact_health", {})
    factor_summary = health.get("factor_trend_summary", {}) or {}

    cols = st.columns(6)
    cols[0].metric("Board date", context.get("as_of", "—"))
    cols[1].metric("Mode", summary.get("mode", "—"))
    cols[2].metric("Candidates", summary.get("candidate_count", 0))
    cols[3].metric("Eligible", summary.get("eligible_count", 0))
    cols[4].metric("Focus", trace.get("selected_candidate_id", "—"))
    cols[5].metric("Factor review", factor_summary.get("headline", "—"))

    if health.get("inputs_stale") or health.get("missing_execution_columns"):
        st.warning(f"Artifact issue: stale={health.get('inputs_stale')}, missing={health.get('missing_execution_columns')}")

    tabs = st.tabs(["Decision tree", "Regime", "Candidate trace", "Weights", "Context JSON", "Memo"])
    with tabs[0]:
        _render_tree(trace)
        st.markdown("**Allowed candidate IDs**")
        st.write(rails.get("allowed_candidate_ids", []))
        blocked = pd.DataFrame(rails.get("blocked_candidates", []))
        if not blocked.empty:
            with st.expander("Blocked candidates"):
                st.dataframe(blocked, use_container_width=True, hide_index=True)
    with tabs[1]:
        _render_regime(trace)
    with tabs[2]:
        _render_ranked(trace)
    with tabs[3]:
        _render_weights(trace)
    with tabs[4]:
        st.json(context)
    with tabs[5]:
        st.markdown(render_agent_memo(context))


def render_agent_intel(output_root: str | Path) -> None:
    st.subheader("Selection meta harness")
    st.caption("Visible selection diagnostics for human review: legal candidates, regime proxy, score tree, gates, factor warnings, and weight provenance.")
    root = Path(output_root)
    left, right = st.columns([1, 3])
    if left.button("Regenerate latest context pack", type="primary", use_container_width=True):
        try:
            pack = write_agent_pm_pack(root)
            st.success(f"Wrote {pack.memo_path}")
        except Exception as exc:
            st.error(str(exc))
    right.caption(f"Output root: `{root}`")
    context = _load_latest_context(root)
    if not context:
        st.info("No latest context yet. Run `python -m svyable.strategy_daily --evaluate-only` or `python -m svyable.agent_pm_harness`.")
        return
    _render_context(context)
