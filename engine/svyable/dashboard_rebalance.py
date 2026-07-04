"""Deprecated compatibility wrapper for the old rebalance-only Streamlit view.

Rebalance planning, safety checks, broker preflight, sandbox submission, live
quotes, manual tickets, orders, and reconciliation now live in the consolidated
Portfolio Ops workspace. Keeping this wrapper avoids breaking older imports while
preventing a duplicate execution UI from diverging.
"""

from __future__ import annotations

import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_portfolio_ops import render_portfolio_ops
from svyable.dashboard_service import DashboardService


def render_rebalance(service: DashboardService, settings: TastySettings) -> None:
    """Render the consolidated Portfolio Ops workspace instead of the legacy view."""
    st.warning(
        "This rebalance-only view is deprecated. Rebalance planning and execution "
        "controls are consolidated under Portfolio Ops so broker state, live quotes, "
        "preflight, and submission share one PM workflow."
    )
    render_portfolio_ops(service, settings)
