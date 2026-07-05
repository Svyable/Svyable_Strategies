"""Streamlit surface for selection meta diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from svyable.agent_decision_guard import validate_agent_decision, write_guard_report
from svyable.agent_decision_writer import write_agent_decision_from_context
from svyable.agent_gui_model import artifact_inventory, issue_summary, recommended_next_step, status_icon, workflow_steps
from svyable.agent_pm_harness import render_agent_memo, write_agent_pm_pack
from svyable.agent_review_audit import audit_review_receipt, write_review_audit
from svyable.agent_review_receipt import write_review_receipt
from svyable.dashboard_ui import percent


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        st.warning(f"JSON is malformed: {path}")
        return {}


def _load_latest_context(output_root: str | Path) -> dict[str, Any]:
    return _read_json(Path(output_root) / "strategy_selection" / "latest_agent_context.json")


def _load_latest_receipt(output_root: str | Path) -> dict[str, Any]:
    return _read_json(Path(output_root) / "strategy_selection" / "latest_agent_review_receipt.json")


def _load_latest_audit(output_root: str | Path) -> dict[str, Any]:
    return _read_json(Path(output_root) / "strategy_selection" / "latest_agent_review_audit.json")


def _num(value: Any, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if suffix == "%":
        return percent(number)
    return f"{number:.3f}{suffix}"


def _download_file(path: Path, label: str) -> None:
    if path.exists():
        st.download_button(
            label,
            data=path.read_text(),
            file_name=path.name,
            mime="text/plain",
            use_container_width=True,
        )


def _status_markdown(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    if "status" in frame.columns:
        frame.insert(0, "", frame["status"].map(status_icon))
    return frame


def _render_overview(context: dict[str, Any], output_root: str | Path) -> None:
    root = Path(output_root)
    guard = validate_agent_decision(root)
    receipt = _load_latest_receipt(root)
    audit = _load_latest_audit(root) or audit_review_receipt(root)
    steps = workflow_steps(context, guard, receipt, audit)
    issues = issue_summary(context, guard, receipt, audit)

    top = st.columns(4)
    top[0].metric("Workflow", f"{status_icon(issues['status'])} {issues['status']}")
    top[1].metric("Next action", recommended_next_step(steps))
    top[2].metric("Blockers", len(issues["blockers"]))
    top[3].metric("Warnings", len(issues["warnings"]))

    st.markdown("### Operator stepper")
    st.dataframe(_status_markdown(steps), use_container_width=True, hide_index=True)

    with st.expander("Blockers and warnings", expanded=bool(issues["blockers"])):
        if not issues["blockers"] and not issues["warnings"]:
            st.success("No current blockers or warnings across context, guard, receipt, and audit.")
        for item in issues["blockers"]:
            st.error(item)
        for item in issues["warnings"]:
            st.warning(item)

    st.markdown("### One-click review actions")
    actions = st.columns(4)
    if actions[0].button("Regenerate context", type="primary", use_container_width=True):
        try:
            pack = write_agent_pm_pack(root)
            st.success(f"Wrote {pack.memo_path}")
        except Exception as exc:
            st.error(str(exc))
    if actions[1].button("Write guard", use_container_width=True):
        try:
            report = write_guard_report(root)
            st.success(f"Wrote {report.get('report_path')}")
        except Exception as exc:
            st.error(str(exc))
    if actions[2].button("Write receipt", use_container_width=True):
        try:
            receipt = write_review_receipt(root)
            st.success(f"Wrote {receipt.get('receipt_md')}")
        except Exception as exc:
            st.error(str(exc))
    if actions[3].button("Write audit", use_container_width=True):
        try:
            report = write_review_audit(root)
            st.success(f"Wrote {report.get('report_path')}")
        except Exception as exc:
            st.error(str(exc))

    st.markdown("### Artifact inventory")
    artifacts = pd.DataFrame(artifact_inventory(root))
    st.dataframe(artifacts, use_container_width=True, hide_index=True)

    dl = st.columns(4)
    with dl[0]:
        _download_file(root / "strategy_selection" / "latest_agent_pm_memo.md", "Download memo")
    with dl[1]:
        _download_file(root / "strategy_selection" / "latest_agent_context.json", "Download context")
    with dl[2]:
        _download_file(root / "strategy_selection" / "latest_agent_review_receipt.md", "Download receipt")
    with dl[3]:
        _download_file(root / "strategy_selection" / "latest_agent_review_audit.json", "Download audit")


def _render_decision_writer(context: dict[str, Any], output_root: str | Path) -> None:
    root = Path(output_root)
    rails = context.get("rails", {}) or {}
    allowed = [str(item) for item in rails.get("allowed_candidate_ids", [])]
    explanation = context.get("selection_explanation", {}) or {}
    default_candidate = str(context.get("summary", {}).get("top_eligible_candidate") or (allowed[0] if allowed else ""))
    default_index = allowed.index(default_candidate) if default_candidate in allowed else 0
    if not allowed:
        st.error("No allowed candidates are available. Refresh the board/context before writing a decision.")
        return

    st.markdown("### Guarded decision writer")
    st.caption(
        "Writes only `strategy_selection/agent_decision.json` using the latest context date/hash. "
        "It cannot write weights, quantities, or orders, and it immediately runs the decision guard."
    )
    with st.form("agent_decision_writer_form"):
        candidate = st.selectbox("Allowed candidate", allowed, index=default_index)
        confidence = st.slider("Confidence", 0.0, 1.0, 0.50, 0.01)
        operator = st.text_input("Operator", value="human_pm")
        reason = st.text_area(
            "Reason",
            value=explanation.get("summary") or "Selected after reviewing readiness, decision tree, counterfactuals, and weight provenance.",
            height=130,
        )
        submit = st.form_submit_button("Write guarded decision", type="primary", use_container_width=True)
    if submit:
        try:
            result = write_agent_decision_from_context(
                root,
                candidate_id=candidate,
                confidence=confidence,
                reason=reason,
                operator=operator,
            )
            if result.get("status") == "PASS":
                st.success(f"Decision written and guard passed: {result.get('decision_path')}")
            else:
                st.warning(f"Decision written but guard returned {result.get('status')}")
            st.json(result)
        except Exception as exc:
            st.error(str(exc))

    if "hold_current" in allowed:
        if st.button("Safe fallback: write hold_current decision", use_container_width=True):
            try:
                result = write_agent_decision_from_context(
                    root,
                    candidate_id="hold_current",
                    confidence=0.35,
                    reason="Human PM selected hold_current as a safe fallback after reviewing the current context.",
                    operator="human_pm",
                )
                st.success(f"Hold decision written: {result.get('decision_path')}")
                st.json(result)
            except Exception as exc:
                st.error(str(exc))


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
        st.dataframe(_status_markdown(nodes.to_dict(orient="records")), use_container_width=True, hide_index=True)


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


def _render_counterfactuals(context: dict[str, Any]) -> None:
    explanation = context.get("selection_explanation", {}) or {}
    readiness = context.get("decision_readiness", {}) or {}
    cols = st.columns(4)
    cols[0].metric("Decision readiness", readiness.get("status", "—"))
    cols[1].metric("Allowed candidates", readiness.get("allowed_candidate_count", 0))
    cols[2].metric("Focus", explanation.get("focus_candidate_id", "—"))
    cols[3].metric("Action", explanation.get("focus_action", "—"))
    issues = readiness.get("issues", []) or []
    if issues:
        st.warning("; ".join(str(item) for item in issues))
    st.markdown("**Why this candidate?**")
    st.write(explanation.get("summary", "No explanation available."))
    focus_blockers = explanation.get("focus_blockers", []) or []
    if focus_blockers:
        st.caption("Focus status: " + "; ".join(str(item) for item in focus_blockers))
    alternatives = pd.DataFrame(explanation.get("alternatives", []))
    if alternatives.empty:
        st.info("No counterfactual alternatives available.")
    else:
        st.markdown("**Counterfactual alternatives**")
        st.dataframe(alternatives, use_container_width=True, hide_index=True)


def _render_decision_guard(output_root: str | Path) -> None:
    root = Path(output_root)
    left, right = st.columns([1, 3])
    if left.button("Write guard report", use_container_width=True):
        try:
            report = write_guard_report(root)
            st.success(f"Wrote {report.get('report_path')}")
        except Exception as exc:
            st.error(str(exc))
            return
    right.caption("Validates `strategy_selection/agent_decision.json` against the latest context before activation.")
    report = validate_agent_decision(root)
    cols = st.columns(5)
    cols[0].metric("Guard", f"{status_icon(report.get('status'))} {report.get('status', '—')}")
    cols[1].metric("Candidate", report.get("candidate_id", "—"))
    cols[2].metric("Confidence", _num(report.get("confidence")))
    cols[3].metric("Blockers", len(report.get("blockers", []) or []))
    cols[4].metric("Warnings", len(report.get("warnings", []) or []))
    blockers = report.get("blockers", []) or []
    warnings = report.get("warnings", []) or []
    if blockers:
        st.error("; ".join(str(item) for item in blockers))
    if warnings:
        st.warning("; ".join(str(item) for item in warnings))
    st.json(report)


def _render_receipt(output_root: str | Path) -> None:
    root = Path(output_root)
    left, right = st.columns([1, 3])
    if left.button("Write review receipt", use_container_width=True):
        try:
            receipt = write_review_receipt(root)
            st.success(f"Wrote {receipt.get('receipt_md')}")
        except Exception as exc:
            st.error(str(exc))
            return
    right.caption("Freezes the current context, decision, guard status, and file hashes for review/audit.")
    receipt = _load_latest_receipt(root)
    if not receipt:
        st.info("No receipt yet. Write a review receipt after the guard report is ready.")
        return
    cols = st.columns(5)
    cols[0].metric("Receipt", f"{status_icon(receipt.get('status'))} {receipt.get('status', '—')}")
    cols[1].metric("Candidate", receipt.get("candidate_id", "—"))
    cols[2].metric("Confidence", _num(receipt.get("confidence")))
    cols[3].metric("Blockers", len(receipt.get("blockers", []) or []))
    cols[4].metric("Warnings", len(receipt.get("warnings", []) or []))
    st.json(receipt)


def _render_review_audit(output_root: str | Path) -> None:
    root = Path(output_root)
    left, right = st.columns([1, 3])
    if left.button("Write integrity audit", use_container_width=True):
        try:
            report = write_review_audit(root)
            st.success(f"Wrote {report.get('report_path')}")
        except Exception as exc:
            st.error(str(exc))
            return
    right.caption("Checks that context, memo, decision, and guard files still match the review receipt hashes.")
    report = audit_review_receipt(root)
    cols = st.columns(5)
    cols[0].metric("Audit", f"{status_icon(report.get('status'))} {report.get('status', '—')}")
    cols[1].metric("Candidate", report.get("candidate_id", "—"))
    cols[2].metric("Checks", len(report.get("file_checks", []) or []))
    cols[3].metric("Blockers", len(report.get("blockers", []) or []))
    cols[4].metric("Warnings", len(report.get("warnings", []) or []))
    if report.get("blockers"):
        st.error("; ".join(str(item) for item in report.get("blockers", [])))
    if report.get("warnings"):
        st.warning("; ".join(str(item) for item in report.get("warnings", [])))
    checks = pd.DataFrame(report.get("file_checks", []))
    if not checks.empty:
        st.dataframe(_status_markdown(checks.to_dict(orient="records")), use_container_width=True, hide_index=True)
    st.json(report)


def _render_context(context: dict[str, Any], output_root: str | Path) -> None:
    summary = context.get("summary", {})
    trace = context.get("meta_decision_trace", {})
    rails = context.get("rails", {})
    health = context.get("focus_candidate_artifact_health", {})
    readiness = context.get("decision_readiness", {})
    factor_summary = health.get("factor_trend_summary", {}) or {}

    cols = st.columns(6)
    cols[0].metric("Board date", context.get("as_of", "—"))
    cols[1].metric("Mode", summary.get("mode", "—"))
    cols[2].metric("Candidates", summary.get("candidate_count", 0))
    cols[3].metric("Eligible", summary.get("eligible_count", 0))
    cols[4].metric("Readiness", f"{status_icon(readiness.get('status'))} {readiness.get('status', '—')}")
    cols[5].metric("Factor review", factor_summary.get("headline", "—"))

    if health.get("inputs_stale") or health.get("missing_execution_columns"):
        st.warning(f"Artifact issue: stale={health.get('inputs_stale')}, missing={health.get('missing_execution_columns')}")

    tabs = st.tabs(["Overview", "Decision writer", "Decision tree", "Decision guard", "Receipt", "Integrity audit", "Counterfactuals", "Regime", "Candidate trace", "Weights", "Context JSON", "Memo"])
    with tabs[0]:
        _render_overview(context, output_root)
    with tabs[1]:
        _render_decision_writer(context, output_root)
    with tabs[2]:
        _render_tree(trace)
        st.markdown("**Allowed candidate IDs**")
        st.write(rails.get("allowed_candidate_ids", []))
        blocked = pd.DataFrame(rails.get("blocked_candidates", []))
        if not blocked.empty:
            with st.expander("Blocked candidates"):
                st.dataframe(blocked, use_container_width=True, hide_index=True)
    with tabs[3]:
        _render_decision_guard(output_root)
    with tabs[4]:
        _render_receipt(output_root)
    with tabs[5]:
        _render_review_audit(output_root)
    with tabs[6]:
        _render_counterfactuals(context)
    with tabs[7]:
        _render_regime(trace)
    with tabs[8]:
        _render_ranked(trace)
    with tabs[9]:
        _render_weights(trace)
    with tabs[10]:
        st.json(context)
    with tabs[11]:
        st.markdown(render_agent_memo(context))


def render_agent_intel(output_root: str | Path) -> None:
    st.subheader("Selection meta harness")
    st.caption("Visible selection diagnostics for human review: stepper, guarded decision writer, artifact inventory, legal candidates, regime proxy, score tree, gates, counterfactual alternatives, guard validation, review receipt, integrity audit, and weight provenance.")
    root = Path(output_root)
    context = _load_latest_context(root)
    if not context:
        st.info("No latest context yet. Run `python -m svyable.strategy_daily --evaluate-only` or `python -m svyable.agent_pm_harness`.")
        if st.button("Try to generate context pack", type="primary"):
            try:
                pack = write_agent_pm_pack(root)
                st.success(f"Wrote {pack.memo_path}")
            except Exception as exc:
                st.error(str(exc))
        return
    _render_context(context, root)
