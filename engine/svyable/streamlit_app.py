"""Interactive Svyable Tastytrade operations console."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_audit import render_audit
from svyable.dashboard_broker_view import render_broker
from svyable.dashboard_overview import render_overview
from svyable.dashboard_rebalance import render_rebalance
from svyable.dashboard_service import DashboardService
from svyable.dashboard_strategy import render_strategy


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
        page_title="Svyable Tastytrade Operations", page_icon="📈", layout="wide"
    )
    settings = TastySettings.from_env(require_credentials=False)
    output_root = configured_output_root(settings)
    service = service_for(output_root)

    st.title("Svyable Tastytrade Operations")
    if settings.is_test:
        st.success("SANDBOX / TEST MODE — broker submissions use the sandbox session.")
    else:
        st.error("PRODUCTION / REAL ACCOUNT — observation is available; submission is gated.")

    with st.sidebar:
        st.header("Runtime")
        st.text_input("Environment", value=settings.environment.upper(), disabled=True)
        number = settings.account_number
        masked = f"…{number[-4:]}" if number else "not configured"
        st.text_input("Account", value=masked, disabled=True)
        st.text_input("Output root", value=output_root, disabled=True)
        st.checkbox("Live submission enabled", value=settings.live_enabled, disabled=True)
        if st.button("Clear dashboard cache"):
            st.cache_resource.clear()
            st.session_state.clear()
            st.rerun()
        st.caption("Secrets are read from environment variables and never displayed.")

    tabs = st.tabs(["Overview", "Strategy", "Broker", "Rebalance", "Audit"])
    with tabs[0]:
        render_overview(service)
    with tabs[1]:
        render_strategy(service)
    with tabs[2]:
        render_broker(service)
    with tabs[3]:
        render_rebalance(service, settings)
    with tabs[4]:
        render_audit(service)


if __name__ == "__main__":
    render()
