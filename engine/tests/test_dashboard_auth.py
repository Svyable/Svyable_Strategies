"""Unit tests for the broker-authorization state helper behind the GUI button."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.dashboard_auth import auth_state


def _settings(**overrides) -> TastySettings:
    base = dict(
        client_secret="secret",
        refresh_token="refresh",
        account_number="ACC123",
        client_id="client",
        redirect_uri="http://127.0.0.1:8182/callback",
    )
    base.update(overrides)
    return TastySettings(**base)


def test_connected_when_refresh_token_present():
    needs_auth, can_authorize, message = auth_state(_settings())
    assert needs_auth is False
    assert can_authorize is True
    assert "Connected" in message
    assert "SANDBOX" in message


def test_needs_auth_when_refresh_token_missing_but_app_creds_present():
    needs_auth, can_authorize, message = auth_state(_settings(refresh_token=""))
    assert needs_auth is True
    assert can_authorize is True
    assert "Authorize once" in message
    assert "SANDBOX" in message


def test_cannot_authorize_when_app_creds_missing():
    needs_auth, can_authorize, message = auth_state(
        _settings(refresh_token="", client_secret="", redirect_uri="")
    )
    assert needs_auth is True
    assert can_authorize is False
    assert "TASTY_SANDBOX_CLIENT_SECRET" in message
    assert "TASTY_CLIENT_SECRET" in message
    assert "TASTY_SANDBOX_REDIRECT_URI" in message
    assert "TASTY_REDIRECT_URI" in message


def test_production_auth_state_names_prod_profile_variables():
    needs_auth, can_authorize, message = auth_state(
        _settings(
            is_test=False,
            refresh_token="",
            client_secret="",
            redirect_uri="",
        )
    )
    assert needs_auth is True
    assert can_authorize is False
    assert "PRODUCTION" in message
    assert "TASTY_PROD_CLIENT_SECRET" in message
    assert "TASTY_PROD_REDIRECT_URI" in message
