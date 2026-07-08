"""Default Agentic PM view for the Svyable portfolio operation.

The first screen is intentionally decision-first: current Tastytrade holdings and
the proposed market-open transactions are above diagnostics. Strategy artifacts,
frontier details, quote boards, readiness gates, and audit trails remain one
scroll or expander away for review.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from svyable import dashboard_charts as charts
from svyable.broker_settings import TastySettings
from svyable.dashboard_data import clean_returns
from svyable.dashboard_live_market import render_live_market_monitor
from svyable.dashboard_positions import position_pnl, render_target_vs_actual, target_vs_actual
from svyable.dashboard_readiness import render_readiness_panel
from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import broker_ready, money, percent, render_figure, short_hash
from svyable.strategy_selection_service import StrategySelectionService


def _safe_ledger_snapshot(service: DashboardService) -> dict:
    try:
        return service.ledger_snapshot()
    except Exception as exc:
        st.warning(f"Ledger snapshot unavailable: {exc}")
        return {
            "health": {},
            "runs": pd.DataFrame(),
            "warnings": pd.DataFrame(),
            "equity": pd.DataFrame(),
        }


def _broker_snapshot_card(service: DashboardService, settings: TastySettings) -> dict | None:
    if not broker_ready(settings):
        st.info(
            "Broker connection is not configured yet. Strategy, agent, and local artifact views still work; "
            "connect credentials from the sidebar to unlock broker data, quotes, and planning."
        )
        return None

    cache_key = f"command_broker_snapshot::{settings.environment}::{service.output_root}"
    col_a, col_b = st.columns([1, 4])
    if col_a.button("Refresh broker", type="primary", use_container_width=True):
        st.session_state.pop(cache_key, None)
        st.session_state.pop("command_live_market_table", None)
        st.session_state.pop("command_rebalance_plan", None)
    if cache_key not in st.session_state:
        try:
            with st.spinner("Loading broker state..."):
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
    st.caption(f"Rows returned for today: **{order_count}**. Full broker workflow is in Portfolio Ops.")
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

    long_gross = short_gross = gross = 0.0
    positions = 0
    if not weights.empty:
        column = "weight" if "weight" in weights.columns else weights.columns[0]
        series = pd.to_numeric(weights[column], errors="coerce").dropna()
        long_gross = float(series.clip(lower=0.0).sum())
        short_gross = float(series.clip(upper=0.0).abs().sum())
        gross = float(series.abs().sum())
        positions = int((series.abs() > 1e-9).sum())

    cols = st.columns(6)
    cols[0].metric("Data status", data.get("status", "—"))
    cols[1].metric("Data date", data.get("last_date", "—"))
    cols[2].metric("Config", short_hash(config_hash), help=f"Full config hash: {config_hash or '—'}")
    cols[3].metric("Target names", positions)
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
        cols = [
            c
            for c in [
                "candidate_id",
                "eligible",
                "utility_bps",
                "expected_alpha_bps",
                "one_way_turnover",
                "estimated_cost_bps",
                "family",
            ]
            if c in board.columns
        ]
        st.dataframe(
            board[cols].sort_values("utility_bps", ascending=False).head(12)
            if "utility_bps" in board.columns else board[cols].head(12),
            use_container_width=True,
            hide_index=True,
        )
    return board


def _account_equity(account: dict[str, Any]) -> float | None:
    try:
        value = float(account.get("equity"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _target_series_or_empty(service: DashboardService) -> pd.Series:
    try:
        return service.target_series()
    except Exception as exc:
        st.caption(f"Latest target weights unavailable: {exc}")
        return pd.Series(dtype=float)


def _positions_display_frame(
    positions: pd.DataFrame,
    targets: pd.Series,
    net_liq: float | None,
) -> pd.DataFrame:
    frame = position_pnl(positions).copy()
    if frame.empty or "symbol" not in frame.columns:
        return frame

    frame["symbol"] = frame["symbol"].astype(str)
    if not targets.empty:
        drift = target_vs_actual(positions, targets, net_liq).reset_index()
        frame = frame.merge(drift, on="symbol", how="left")
    elif "book_weight" in frame.columns:
        frame["actual_weight"] = frame["book_weight"]

    if "market_value" in frame.columns:
        frame = frame.sort_values("market_value", key=lambda values: values.abs(), ascending=False)

    display_cols = [
        c
        for c in [
            "symbol",
            "quantity",
            "mark",
            "market_value",
            "actual_weight",
            "target_weight",
            "drift",
            "unrealized_pl",
            "unrealized_pct",
            "updated_at",
        ]
        if c in frame.columns
    ]
    return frame[display_cols]


def _render_current_positions(service: DashboardService, broker_snapshot: dict | None) -> pd.Series:
    st.subheader("Current portfolio positions")
    st.caption("Live Tastytrade holdings, matched to the latest target weights when available.")

    if broker_snapshot is None:
        st.info("Connect or refresh the broker to list the current portfolio.")
        return pd.Series(dtype=float)

    positions = broker_snapshot.get("positions", pd.DataFrame())
    account = broker_snapshot.get("account", {})
    targets = _target_series_or_empty(service)
    net_liq = _account_equity(account)

    if positions.empty:
        st.success("Broker reports no open positions.")
        if not targets.empty:
            target_preview = targets[targets.abs() > 1e-9].sort_values(ascending=False).rename("target_weight")
            st.caption("The strategy target book is available even though the live account is flat.")
            st.dataframe(target_preview.to_frame(), use_container_width=True)
        return targets

    display = _positions_display_frame(positions, targets, net_liq)
    stats = position_pnl(positions)
    gross_mv = float(stats.get("market_value", pd.Series(dtype=float)).abs().sum())
    net_mv = float(stats.get("market_value", pd.Series(dtype=float)).sum())
    tracking_error = (
        float(pd.to_numeric(display.get("drift", pd.Series(dtype=float)), errors="coerce").abs().sum())
        if "drift" in display.columns
        else None
    )

    cols = st.columns(4)
    cols[0].metric("Held positions", len(display))
    cols[1].metric("Gross market value", money(gross_mv))
    cols[2].metric("Net market value", money(net_mv))
    cols[3].metric("Total target drift", percent(tracking_error) if tracking_error is not None else "—")

    st.dataframe(display, use_container_width=True, hide_index=True)
    return targets


def _render_proposed_transactions(service: DashboardService, settings: TastySettings) -> dict | None:
    st.subheader("Proposed transactions for market open")
    st.caption(
        "Build the trade list from current Tastytrade positions versus the latest strategy targets. "
        "This is a preview; the existing submission gates remain in Portfolio Ops."
    )
    if not broker_ready(settings):
        st.caption("Broker-dependent transaction planning is unavailable until broker credentials are configured.")
        return None

    controls = st.columns([1.2, 1.0, 1.8])
    build = controls[0].button(
        "Build market-open plan",
        key="command_build_plan",
        type="primary",
        use_container_width=True,
    )
    min_notional = controls[1].number_input(
        "Min order $",
        min_value=0.0,
        value=100.0,
        step=50.0,
        key="command_min_order_notional",
        help="Orders below this estimated notional are treated as dust.",
    )
    controls[2].caption("Use this first each morning: it answers what the PM wants to hold on open.")

    if build:
        try:
            st.session_state["command_rebalance_plan"] = service.build_rebalance_plan(
                min_order_notional=float(min_notional)
            )
        except Exception as exc:
            st.session_state.pop("command_rebalance_plan", None)
            st.error(str(exc))

    plan = st.session_state.get("command_rebalance_plan")
    if not plan:
        st.info("No transaction preview has been built yet.")
        return None

    orders = pd.DataFrame(plan.get("orders", []))
    cols = st.columns(5)
    cols[0].metric("Proposed trades", len(orders))
    cols[1].metric("Safety", "PASS" if plan.get("safety_complete") else "BLOCKED")
    cols[2].metric("ADV capped", plan.get("adv_capped_orders", 0))
    cols[3].metric("Estimated turnover", money(plan.get("estimated_turnover")))
    cols[4].metric("Inputs date", plan.get("execution_inputs_date") or "missing")

    if plan.get("inputs_stale"):
        st.error(
            "Execution inputs are stale. Run `svyable daily` before using this plan."
        )
    for key, label in [
        ("missing_prices", "Missing execution prices"),
        ("missing_adv", "Missing ADV values"),
        ("non_liquid_targets", "Targets failing liquidity mask"),
    ]:
        values = plan.get(key) or []
        if values:
            st.error(f"{label}: " + ", ".join(values))

    if orders.empty:
        st.success("Portfolio is within the configured threshold; no transactions are planned.")
    else:
        order_cols = [
            c
            for c in [
                "symbol",
                "side",
                "qty",
                "est_price",
                "est_notional",
                "reason",
                "current_qty",
            ]
            if c in orders.columns
        ]
        st.dataframe(orders[order_cols], use_container_width=True, hide_index=True)
        st.caption("Submission remains gated. Open Portfolio Ops for preflight, confirmation, and audit actions.")

    return plan


def _render_equity_and_drift(ledger: dict) -> None:
    equity = ledger.get("equity", pd.DataFrame()).copy()
    if equity.empty or "d" not in equity.columns:
        st.caption("No paper-vs-shadow equity ledger yet.")
        return
    equity["d"] = pd.to_datetime(equity["d"], errors="coerce")
    equity = equity.dropna(subset=["d"]).set_index("d").sort_index()
    if equity.empty:
        st.caption("No valid equity timestamps in the ledger yet.")
        return

    columns = [col for col in ["shadow_nav", "paper_equity"] if col in equity.columns]
    if columns:
        st.markdown("**Shadow and paper equity**")
        st.line_chart(equity[columns])
    if "drift_bps" in equity.columns:
        st.markdown("**Paper vs shadow return drift**")
        st.line_chart(equity[["drift_bps"]])


def _render_run_health(ledger: dict, output_root: str | Path) -> None:
    health = ledger.get("health", {})
    last_run = health.get("last_daily_run") or {}
    root_label = Path(output_root).name or str(output_root)
    cols = st.columns(6)
    cols[0].metric("Last daily run", last_run.get("ts", "never"))
    cols[1].metric("Run status", last_run.get("status", "—"))
    cols[2].metric("Tracking days", health.get("tracking_days", 0))
    cols[3].metric("Warnings 7d", health.get("warnings_7d", 0))
    cols[4].metric("Critical 7d", health.get("critical_7d", 0))
    cols[5].metric("Output root", root_label)


def render_command_center(
    service: DashboardService,
    strategy_service: StrategySelectionService,
    settings: TastySettings,
    output_root: str | Path,
) -> None:
    st.subheader("🧠 Agentic PM")
    st.caption(
        "Decision-first cockpit: what we currently hold, what we want to hold on market open, "
        "and whether the agentic PM / Tastytrade path is ready."
    )

    ledger = _safe_ledger_snapshot(service)

    st.markdown("### PM decision deck")
    broker_snapshot = _broker_snapshot_card(service, settings)
    targets = _render_current_positions(service, broker_snapshot)

    st.divider()
    plan = _render_proposed_transactions(service, settings)

    st.divider()
    st.subheader("Readiness gates")
    market_frame = pd.DataFrame()
    if broker_snapshot is not None:
        with st.expander("Live target / position quote board", expanded=False):
            market_frame = render_live_market_monitor(
                service,
                broker_snapshot,
                key_prefix="command_live_market",
                max_symbols=25,
                compact=True,
            )
    render_readiness_panel(
        service,
        strategy_service,
        settings,
        broker_snapshot=broker_snapshot,
        market_frame=market_frame,
        ledger_snapshot=ledger,
    )

    with st.expander("Target-vs-actual drift detail", expanded=False):
        if broker_snapshot is None:
            st.caption("Broker snapshot unavailable.")
        else:
            positions = broker_snapshot.get("positions", pd.DataFrame())
            account = broker_snapshot.get("account", {})
            if positions.empty or targets.empty:
                st.caption("Need both broker positions and target weights to show drift.")
            else:
                render_target_vs_actual(
                    positions,
                    targets,
                    float(account.get("equity")) if account.get("equity") else None,
                )

    with st.expander("Strategy, frontier, and run diagnostics", expanded=False):
        _render_run_health(ledger, output_root)

        st.divider()
        st.subheader("Strategy artifact and shadow NAV")
        strategy_snapshot = _strategy_artifact_card(service)

        st.divider()
        st.subheader("Agent frontier and PM selector state")
        _frontier_card(strategy_service)

        with st.expander("Paper vs shadow ledger", expanded=False):
            _render_equity_and_drift(ledger)

    with st.expander("Recent runs and warnings", expanded=False):
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

    strategy_snapshot = service.strategy_snapshot()
    report = strategy_snapshot.get("report") if isinstance(strategy_snapshot, dict) else ""
    if report:
        with st.expander("Morning report", expanded=False):
            st.markdown(report)
