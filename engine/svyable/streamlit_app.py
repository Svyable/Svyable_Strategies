"""Interactive Svyable Tastytrade operations console."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_agent import render_agent
from svyable.dashboard_analytics import render_analytics
from svyable.dashboard_audit import render_audit
from svyable.dashboard_auth import render_auth_controls
from svyable.dashboard_broker_view import render_broker
from svyable.dashboard_factors import render_factors
from svyable.dashboard_overview import render_overview
from svyable.dashboard_rebalance import render_rebalance
from svyable.dashboard_service import DashboardService
from svyable.dashboard_strategy import render_strategy
from svyable.dashboard_ui import broker_ready


def configured_output_root(settings: TastySettings) -> str:
    explicit = os.getenv("SVYABLE_OUTPUT_ROOT")
    if explicit:
        return explicit
    engine_root = Path(__file__).resolve().parents[1]
    return str(engine_root / ("outputs" if settings.is_test else "outputs-production"))


@st.cache_resource
def service_for(output_root: str) -> DashboardService:
    return DashboardService(output_root=output_root)


def render() -> None:
    st.set_page_config(
        page_title="Svyable Tastytrade Operations",
        page_icon="📈",
        layout="wide",
        menu_items={
            "about": (
                "Svyable Tastytrade operations console. Sandbox is the safe default; "
                "production is observation-first with gated submission."
            )
        },
    )
    settings = TastySettings.from_env(require_credentials=False)
    output_root = configured_output_root(settings)
    service = service_for(output_root)
    connected = broker_ready(settings)

    st.title("Svyable Tastytrade Operations")
    if settings.is_test:
        st.success("SANDBOX / TEST MODE — broker submissions use the sandbox session.")
    else:
        st.error("PRODUCTION / REAL ACCOUNT — observation is available; submission is gated.")

    # Glanceable status strip so state is obvious before opening any tab.
    number = settings.account_number
    masked = f"…{number[-4:]}" if number else "not configured"
    st.caption(
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} local"
        f"  ·  🔌 Broker: {'connected' if connected else 'not connected'}"
        f"  ·  🏦 Account {masked}"
        f"  ·  🚦 Live submission: {'ON' if settings.live_enabled else 'off'}"
    )

    with st.sidebar:
        st.header("Runtime")
        st.metric("Environment", settings.environment.upper())
        st.metric("Account", masked)
        st.metric(
            "Broker session",
            "Connected" if connected else "Not connected",
            help="A refresh token, account number, and client secret are all required.",
        )
        st.metric(
            "Live submission",
            "Enabled" if settings.live_enabled else "Disabled",
            help="Hard safety gate. Even when enabled, live orders require typed confirmation.",
        )
        st.caption(f"Output root: `{output_root}`")
        if st.button("Clear dashboard cache", use_container_width=True):
            st.cache_resource.clear()
            st.session_state.clear()
            st.rerun()
        st.caption("Secrets are read from environment variables and never displayed.")

        st.divider()
        render_auth_controls(settings)

    tabs = st.tabs(
        [
            "📊 Overview",
            "🎯 Strategy",
            "🤖 Agent",
            "📈 Analytics",
            "🧬 Factors",
            "🏦 Broker",
            "⚖️ Rebalance",
            "🧾 Audit",
        ]
    )
    with tabs[0]:
        render_overview(service)
    with tabs[1]:
        render_strategy(service)
    with tabs[2]:
        render_agent(output_root)
    with tabs[3]:
        render_analytics(service)
    with tabs[4]:
        render_factors(service)
    with tabs[5]:
        render_broker(service, settings)
    with tabs[6]:
        render_rebalance(service, settings)
    with tabs[7]:
        render_audit(service)


if __name__ == "__main__":
    render()
