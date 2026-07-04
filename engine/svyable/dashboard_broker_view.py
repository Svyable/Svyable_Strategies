"""Deprecated compatibility wrapper for the old broker-only Streamlit view.

Broker account state, positions, target drift, quote lookup, order status,
cancellation, reconciliation, sandbox checks, and manual ticket workflow now live
in :mod:`svyable.dashboard_portfolio_ops`. Keeping this wrapper avoids breaking
older imports while preventing two divergent broker UIs from evolving.
"""

from __future__ import annotations

import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_portfolio_ops import render_portfolio_ops
from svyable.dashboard_service import DashboardService


def render_broker(service: DashboardService, settings: TastySettings) -> None:
    """Render the consolidated Portfolio Ops workspace instead of the legacy view."""
    st.warning(
        "This broker-only view is deprecated. Broker tools are consolidated under "
        "Portfolio Ops so account state, live quotes, drift, orders, and execution "
        "controls stay in one PM workflow."
    )
    render_portfolio_ops(service, settings)
