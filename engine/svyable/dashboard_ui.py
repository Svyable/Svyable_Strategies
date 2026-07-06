"""Shared Streamlit helpers for the Svyable operations console."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import streamlit as st
from matplotlib.figure import Figure

from svyable.broker_settings import TastySettings


def render_figure(fig: Figure) -> None:
    """Render a matplotlib figure full-width and close it.

    Closing after render keeps Streamlit reruns from leaking pyplot figures — the
    single place every dashboard view routes matplotlib output through.
    """
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def render_plotly(fig: Any) -> None:
    """Render a Plotly figure with Streamlit's full-width container."""
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displaylogo": False,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )


def money(value: object) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def percent(value: object) -> str:
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "—"


def short_hash(value: object, keep: int = 8) -> str:
    """Truncate a long hash for a metric card, e.g. ``84d90231…`` (full in tooltip)."""
    text = str(value or "").strip()
    if not text or text == "—":
        return "—"
    return f"{text[:keep]}…" if len(text) > keep else text


def broker_ready(settings: TastySettings) -> bool:
    """True when the credentials needed for a live broker session are all present.

    Mirrors what ``TastySettings.from_env(require_credentials=True)`` demands, so the
    UI can gate the Broker/Rebalance tabs *before* they raise a raw ValueError.
    """
    return bool(
        settings.refresh_token and settings.account_number and settings.client_secret
    )


def render_broker_gate(settings: TastySettings) -> bool:
    """Return True if the broker is usable; otherwise render guidance and return False."""
    if broker_ready(settings):
        return True
    missing_token = not settings.refresh_token
    st.info(
        "🔌 **Broker not connected.** "
        + (
            "No Tastytrade refresh token is configured yet, so live account data and "
            "order controls are unavailable."
            if missing_token
            else "Broker credentials are incomplete (client secret or account number)."
        )
    )
    if missing_token:
        st.caption(
            "Connect it from the **sidebar → Broker authorization → Authorize Tastytrade**. "
            "The Overview, Strategy, and Audit tabs read local artifacts and work without it."
        )
    return False


def submission_confirmation(
    settings: TastySettings, prefix: str
) -> tuple[bool, str]:
    """Require deliberate, environment-specific confirmation before submission."""
    key = prefix.lower().replace(" ", "_")
    if settings.is_test:
        phrase = st.text_input(
            f"Type `{prefix} SANDBOX` to enable submission",
            key=f"{key}_sandbox_confirmation",
        )
        acknowledged = st.checkbox(
            "I reviewed the broker preflight and understand this creates sandbox orders.",
            key=f"{key}_sandbox_ack",
        )
        return acknowledged and phrase == f"{prefix} SANDBOX", ""

    st.error("PRODUCTION SESSION — real capital may be affected.")
    if not settings.live_enabled:
        st.warning(
            "Live submission is disabled. Observation and broker preflight remain available."
        )
        return False, ""

    account = st.text_input(
        "Type the configured account number to confirm live submission",
        type="password",
        key=f"{key}_live_account",
    )
    phrase = st.text_input(f"Type `{prefix} LIVE`", key=f"{key}_live_phrase")
    acknowledged = st.checkbox(
        "I reviewed the order, positions, buying-power impact, and warnings.",
        key=f"{key}_live_ack",
    )
    enabled = acknowledged and account == settings.account_number and phrase == f"{prefix} LIVE"
    return enabled, account


def cancellation_confirmation(settings: TastySettings) -> tuple[bool, str]:
    """Cancellation is risk-reducing but still requires explicit account context."""
    if settings.is_test:
        phrase = st.text_input(
            "Type `CANCEL SANDBOX`",
            key="cancel_sandbox_confirmation",
        )
        acknowledged = st.checkbox(
            "I verified the order ID and want to request cancellation.",
            key="cancel_sandbox_ack",
        )
        return acknowledged and phrase == "CANCEL SANDBOX", ""

    st.error("PRODUCTION CANCELLATION — verify the exact order before continuing.")
    account = st.text_input(
        "Type the configured account number",
        type="password",
        key="cancel_live_account",
    )
    phrase = st.text_input("Type `CANCEL LIVE`", key="cancel_live_phrase")
    acknowledged = st.checkbox(
        "I verified the live order ID and understand this requests broker cancellation.",
        key="cancel_live_ack",
    )
    enabled = acknowledged and account == settings.account_number and phrase == "CANCEL LIVE"
    return enabled, account