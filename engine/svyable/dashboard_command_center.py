"""Default command-center view for the Svyable portfolio operation.

The goal of this page is to make the default `streamlit` launch feel like the PM's
morning cockpit: agent state, strategy artifact freshness, full-frontier coverage,
Tastytrade account/position state, and the next safe operating actions on one
screen. Deeper research and order submission still live behind the dedicated tabs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.broker_settings import TastySettings
from svyable.dashboard_data import clean_returns
from svyable.dashboard_positions import render_target_vs_actual
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import broker_ready, money, percent, render_figure, short_hash
from svyable.strategy_selection_service import StrategySelectionService


def _safe_ledger_snapshot(service: DashboardService) -> dict:
    try:
        return service.ledger_snapshot()
    except Exception as exc:
        st.warning(f"Ledger snapshot unavailable: {exc}")
        return {"health": {}, "runs": pd.DataFrame(), "warnings": pd.DataFrame(), "equity": pd.DataFrame()}


def _broker_snapshot_card(service: DashboardService, settings: TastySettings) -> dict | None:
    if not broker_ready(settings):
        st.info(
            "Tastytrade is not connected yet. Strategy, agent, and local artifact views still work; "
            "connect the broker from the sidebar to unlock account state, quotes, preflight, and execution."
        )
        return None

    cache_key = f"command_broker_snapshot::{settings.environment}::{service.output_root}"
    col_a, col_b = st.columns([1, 4])
    if col_a.button("Refresh broker", type="primary", use_container_width=True):
        st.session_state.pop(cache_key, None)
    if cache_key not in st.session_state:
        try:
            with st.spinner("Loading Tastytrade account, positions, and orders..."):
                st.session_state[cache_key] = {
                    "loaded_at": datetime.now().isoformat(timespec="seconds"),
                    "data": service.broker_snapshot(),
                }
        except Exception as exc:
            st.error(f"Broker unavailable: {exc}")
            return None

    cached = st.session_state[cache_key]
    snapshot = cached["data"]
    account = snapshot.get("account", {})
    positions = snapshot.get("positions", pd.DataFrame())
    orders = snapshot.get("orders", pd.DataFrame())
    number = str(snapshot.get("account_number", ""))
    masked = f"…{number[-4:]}" if number else "not configured"

    col_b.caption(f"Broker snapshot loaded {cached['loaded_at']} local time.")
    cols = st.columns(6)
    cols[0].metric("Environment", str(snapshot.get("environment", settings.environment)).upper())
    cols[1].metric("Account", masked)
    cols[2].metric("Net liq", money(account.get("equity")))
    cols[3].metric("Cash", money(account.get("cash")))
    cols[4].metric("Maintenance excess", money(account.get("maintenance_excess")))
    cols[5].metric("Open positions", 0 if positions.empty else len(positions))

    order_count = 0 if orders.empty else len(orders)
    st.caption(f"Orders returned for today: **{order_count}**. Full order controls are in Portfolio Ops.")
    return snapshot


def _strategy_artifact_card(service: DashboardService) -> dict:
    snapshot = service.strategy_snapshot()
    if snapshot["run_dir"] is None:
        st.info("No strategy artifacts yet. Run `svyable daily` or a fresh candidate evaluation.")
        return snapshot

    meta = snapshot.get("meta", {})
    weights = snapshot.get("weights", pd.DataFrame()).copy()
    pnl = snapshot.get("pnl", pd.DataFrame())
    budget = snapshot.get("budget", pd.DataFrame())
    data = meta.get("data") or {}
    config_hash = str(meta.get("config_hash", ""))

    long_gross = short_gross = net = gross = 0.0
    positions = 0
    if not weights.empty:
        column = "weight" if "weight" in weights.columns else weights.columns[0]
        series = pd.to_numeric(weights[column], errors="coerce").dropna()
        long_gross = float(series.clip(lower=0.0).sum())
        short_gross = float(series.clip(upper=0.0).abs().sum())
        net = float(series.sum())
        gross = float(series.abs().sum())
        positions = int((series.abs() > 1e-9).sum())

    cols = st.columns(6)
    cols[0].metric("Data status", data.get("status", "—"))
    cols[1].metric("Data date", data.get("last_date", "—"))
    cols[2].metric("Config", short_hash(config_hash), help=f"Full config hash: {config_hash or '—'}")
    cols[3].metric("Positions", positions)
    cols[4].metric("Long / short", f"{percent(long_gross)} / {percent(short_gross)}")
    budget_value = float(budget.iloc[-1, 0]) if not budget.empty else None
    cols[5].metric("Gross budget", f"{budget_value:.2f}x" if budget_value else percent(gross))

    if not pnl.empty:
        returns = clean_returns(pnl)
        if len(returns):
            st.caption(f"Latest canonical strategy artifact: `{snapshot['run_dir']}`")
            render_figure(charts.cumulative_return_chart(returns.tail(252), title="Recent shadow-NAV evidence"))
    return snapshot


def _frontier_card(strategy_service: StrategySelectionService) -> pd.DataFrame:
    status = strategy_service.frontier_status()
    board = strategy_service.latest_board()
    state = strategy_service.state()
    decision = strategy_service.latest_decision() or {}

    cols = st.columns(6)
    cols[0].metric("Registered strategies", status["registry_strategy_count"])
    cols[1].metric("Default strategies", status["default_strategy_count"])
    cols[2].metric("Policy frontier", status["expected_candidate_count"])
    cols[3].metric("Latest board", status["board_candidate_count"])
    cols[4].metric("Current strategy", state.get("selected_strategy_id", "not selected"))
    cols[5].metric("Decision source", decision.get("source", state.get("source", "—")))

    if status["is_incomplete_latest_board"]:
        st.warning(status["explanation"])
        if st.button("Enable every default strategy + chimera", key="command_enable_full_frontier"):
            path = strategy_service.save_full_frontier_policy()
            st.success(f"Saved full-frontier policy to `{path}`. Run a fresh candidate evaluation next.")
            st.rerun()
    elif board.empty:
        st.info("No candidate board yet. Use Agent Lab → Control surface to run a fresh evaluation.")
    else:
        best = board.sort_values("utility_bps", ascending=False).iloc[0] if "utility_bps" in board.columns else board.iloc[0]
        st.caption(
            f"Latest board covers the policy frontier. Top utility candidate: "
            f"**{best.get('candidate_id', '—')}**."
        )

    if not board.empty:
        cols = [c for c in ["candidate_id", "eligible", "utility_bps", "expected_alpha_bps", "one_way_turnover", "estimated_cost_bps", "family"] if c in board.columns]
        st.dataframe(
            board[cols].sort_values("utility_bps", ascending=False).head(12)
            if "utility_bps" in board.columns else board[cols].head(12),
            use_container_width=True,
            hide_index=True,
        )
    return board


def _quick_rebalance_preview(service: DashboardService, settings: TastySettings) -> None:
    st.subheader("Next PM action")
    if not broker_ready(settings):
        st.caption("Broker-dependent rebalance preview is unavailable until Tastytrade is connected.")
        return

    min_notional = st.number_input(
        "Quick plan minimum order notional",
        min_value=0.0,
        value=100.0,
        step=50.0,
        key="command_min_order_notional",
    )
    if st.button("Build quick rebalance preview", key="command_build_plan"):
        try:
            st.session_state["command_rebalance_plan"] = service.build_rebalance_plan(
                min_order_notional=float(min_notional)
            )
        except Exception as exc:
            st.error(str(exc))

    plan = st.session_state.get("command_rebalance_plan")
    if not plan:
        st.caption("Build a preview to see planned orders, stale inputs, ADV caps, and safety gates.")
        return

    cols = st.columns(5)
    cols[0].metric("Orders", len(plan.get("orders", [])))
    cols[1].metric("Safety", "PASS" if plan.get("safety_complete") else "BLOCKED")
    cols[2].metric("ADV capped", plan.get("adv_capped_orders", 0))
    cols[3].metric("Est. turnover", money(plan.get("estimated_turnover")))
    cols[4].metric("Inputs date", plan.get("execution_inputs_date") or "missing")

    if plan.get("inputs_stale"):
        st.error("Execution inputs are stale. Run `svyable daily` before proceeding.")
    for key, label in [
        ("missing_prices", "Missing execution prices"),
        ("missing_adv", "Missing ADV values"),
        ("non_liquid_targets", "Targets failing liquidity mask"),
    ]:
        values = plan.get(key) or []
        if values:
            st.error(f"{label}: " + ", ".join(values))

    orders = pd.DataFrame(plan.get("orders", []))
    if orders.empty:
        st.success("Portfolio is within the configured order threshold; no orders planned.")
    else:
        st.dataframe(orders, use_container_width=True, hide_index=True)
        st.caption("Use Portfolio Ops for broker preflight, typed confirmation, submission, cancellations, and quote lookup.")


def render_command_center(
    service: DashboardService,
    strategy_service: StrategySelectionService,
    settings: TastySettings,
    output_root: str | Path,
) -> None:
    st.subheader("🧠 Agentic portfolio command center")
    st.caption(
        "One-screen operating view: strategy artifacts, candidate frontier, Tastytrade account state, "
        "and the next safe PM actions. Research and execution details are one tab away."
    )

    ledger = _safe_ledger_snapshot(service)
    health = ledger.get("health", {})
    last_run = health.get("last_daily_run") or {}
    cols = st.columns(6)
    cols[0].metric("Last daily run", last_run.get("ts", "never"))
    cols[1].metric("Run status", last_run.get("status", "—"))
    cols[2].metric("Tracking days", health.get("tracking_days", 0))
    cols[3].metric("Warnings 7d", health.get("warnings_7d", 0))
    cols[4].metric("Critical 7d", health.get("critical_7d", 0))
    cols[5].metric("Output root", str(output_root).split("/")[-1] or str(output_root))

    st.divider()
    st.subheader("Strategy artifact and shadow NAV")
    strategy_snapshot = _strategy_artifact_card(service)

    st.divider()
    st.subheader("Agent frontier and PM selector state")
    _frontier_card(strategy_service)

    st.divider()
    st.subheader("Tastytrade account state")
    broker_snapshot = _broker_snapshot_card(service, settings)
    if broker_snapshot is not None:
        positions = broker_snapshot.get("positions", pd.DataFrame())
        account = broker_snapshot.get("account", {})
        try:
            targets = service.target_series()
        except Exception:
            targets = pd.Series(dtype=float)
        if not positions.empty and not targets.empty:
            with st.expander("Target vs actual drift", expanded=True):
                render_target_vs_actual(
                    positions,
                    targets,
                    float(account.get("equity")) if account.get("equity") else None,
                )

    st.divider()
    _quick_rebalance_preview(service, settings)

    with st.expander("Recent runs and warnings"):
        left, right = st.columns(2)
        with left:
            st.markdown("**Recent runs**")
            st.dataframe(ledger.get("runs", pd.DataFrame()), use_container_width=True, hide_index=True)
        with right:
            st.markdown("**Open warnings**")
            warnings = ledger.get("warnings", pd.DataFrame())
            if warnings.empty:
                st.success("No warnings in the selected window.")
            else:
                st.dataframe(warnings, use_container_width=True, hide_index=True)

    report = strategy_snapshot.get("report") if isinstance(strategy_snapshot, dict) else ""
    if report:
        with st.expander("Morning report"):
            st.markdown(report)
