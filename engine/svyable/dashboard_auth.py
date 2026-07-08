"""Streamlit controls for one-time Tastytrade OAuth onboarding.

The daily loop authenticates silently with a stored ``refresh_token``. That token
is minted exactly once by :func:`svyable.oauth.authorize`, which opens the
Tastytrade login page and captures the redirect on a local loopback server. This
module surfaces that same flow as a button in the operations console so the user
never has to drop to a terminal.

``auth_state`` is a pure function (no Streamlit, no I/O) so it can be unit tested.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from svyable.broker_settings import TastySettings


def default_env_path() -> Path:
    """The engine/.env that :func:`svyable.oauth.authorize` reads and updates."""
    return Path(__file__).resolve().parents[1] / ".env"


def auth_state(settings: TastySettings) -> tuple[bool, bool, str]:
    """Return ``(needs_auth, can_authorize, message)`` — pure, safe to unit test.

    * ``needs_auth`` — True when there is no usable refresh token yet.
    * ``can_authorize`` — True when the OAuth app credentials required to start the
      authorization-code flow (client id/secret + redirect uri) are all present.
    * ``message`` — a human explanation of the current state.
    """
    missing = [
        settings.env_var_help(suffix)
        for suffix, value in (
            ("CLIENT_ID", settings.client_id),
            ("CLIENT_SECRET", settings.client_secret),
            ("REDIRECT_URI", settings.redirect_uri),
        )
        if not value
    ]
    can_authorize = not missing
    mode = settings.environment.upper()

    if not settings.refresh_token:
        if missing:
            return True, can_authorize, (
                f"Cannot authorize {mode} yet — set "
                + ", ".join(missing)
                + " in engine/.env first."
            )
        return True, can_authorize, (
            f"No {mode} refresh token yet. Authorize once to connect this "
            "broker profile; the daily loop refreshes silently afterward."
        )

    return False, can_authorize, (
        f"Connected to {mode} — a refresh token is present for this broker "
        "profile. Re-authorize only if it was revoked or expired."
    )


def _run_authorization(settings: TastySettings, env_path: Path) -> None:
    """Drive the interactive OAuth flow, then reload the token into this process."""
    from dotenv import load_dotenv

    from svyable.oauth import authorize

    st.info(
        f"A browser window will open for Tastytrade {settings.environment} sign-in "
        "and Duo 2FA. Approve it, then return here. If no browser opens, the "
        "sign-in URL is printed in the terminal running the console. Waiting up "
        "to 5 minutes for the redirect…"
    )
    try:
        with st.spinner("Waiting for the Tastytrade authorization redirect…"):
            summary = authorize(env_path, open_browser=True, settings=settings)
    except Exception as exc:  # noqa: BLE001 — surface cleanly, never leak secrets
        st.error(f"Authorization failed: {exc}")
        return

    # The token was written to .env; pull it into this process (override the empty
    # value loaded at startup) and drop cached broker sessions so they reconnect.
    load_dotenv(env_path, override=True)
    st.cache_resource.clear()
    st.success(
        f"Authorized ✓  {summary.get('environment')} account "
        f"{summary.get('account_number')}  ·  refresh token "
        f"{summary.get('refresh_token')} written to {env_path.name} "
        f"as {', '.join(summary.get('wrote', []))}"
    )
    st.rerun()


def render_auth_controls(settings: TastySettings, env_path: Path | None = None) -> None:
    """Render the broker-authorization status and Authorize/Re-authorize button."""
    env_path = env_path or default_env_path()
    needs_auth, can_authorize, message = auth_state(settings)

    st.subheader("Broker authorization")
    (st.warning if needs_auth else st.success)(message)
    st.caption(
        f"Environment: **{settings.environment.upper()}**  ·  "
        f"redirect: `{settings.redirect_uri or 'not set'}`"
    )

    label = (
        f"🔐 Authorize Tastytrade {settings.environment}"
        if needs_auth
        else f"Re-authorize Tastytrade {settings.environment}"
    )
    if st.button(
        label,
        disabled=not can_authorize,
        type="primary" if needs_auth else "secondary",
        use_container_width=True,
        help=None if can_authorize else "Missing OAuth app credentials in engine/.env.",
    ):
        _run_authorization(settings, env_path)
