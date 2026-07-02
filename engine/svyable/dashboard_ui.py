"""Shared Streamlit helpers for the Svyable operations console."""

from __future__ import annotations

import streamlit as st

from svyable.broker_settings import TastySettings


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
