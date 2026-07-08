"""Regression coverage for profile-aware Tastytrade settings."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import svyable.broker_settings as broker_settings
from svyable.broker_settings import TastySettings


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(("TASTY", "TT_", "SVYABLE")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(broker_settings, "load_dotenv", lambda *args, **kwargs: None)


def test_from_env_for_mode_prefers_sandbox_profile_names(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TASTY_CLIENT_SECRET", "generic-secret")
    monkeypatch.setenv("TASTY_REFRESH_TOKEN", "generic-refresh")
    monkeypatch.setenv("TASTY_ACCOUNT_NUMBER", "GENERIC")
    monkeypatch.setenv("TASTY_SANDBOX_CLIENT_SECRET", "sandbox-secret")
    monkeypatch.setenv("TASTY_SANDBOX_REFRESH_TOKEN", "sandbox-refresh")
    monkeypatch.setenv("TASTY_SANDBOX_ACCOUNT_NUMBER", "SANDBOX123")
    monkeypatch.setenv("TASTY_SANDBOX_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv("TASTY_SANDBOX_REDIRECT_URI", "http://127.0.0.1:8182/sandbox")

    settings = TastySettings.from_env_for_mode(is_test=True)

    assert settings.environment == "sandbox"
    assert settings.env_prefix == "TASTY_SANDBOX"
    assert settings.client_secret == "sandbox-secret"
    assert settings.refresh_token == "sandbox-refresh"
    assert settings.account_number == "SANDBOX123"
    assert settings.client_id == "sandbox-client"
    assert settings.redirect_uri.endswith("/sandbox")
    assert settings.audit_path == Path("outputs/audit/tastytrade.jsonl")


def test_from_env_for_mode_prefers_prod_profile_names(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TASTY_CLIENT_SECRET", "generic-secret")
    monkeypatch.setenv("TASTY_REFRESH_TOKEN", "generic-refresh")
    monkeypatch.setenv("TASTY_ACCOUNT_NUMBER", "GENERIC")
    monkeypatch.setenv("TASTY_PROD_CLIENT_SECRET", "prod-secret")
    monkeypatch.setenv("TASTY_PROD_REFRESH_TOKEN", "prod-refresh")
    monkeypatch.setenv("TASTY_PROD_ACCOUNT_NUMBER", "PROD123")
    monkeypatch.setenv("TASTY_PROD_CLIENT_ID", "prod-client")
    monkeypatch.setenv("TASTY_PROD_REDIRECT_URI", "http://127.0.0.1:8182/prod")
    monkeypatch.setenv("SVYABLE_PROD_TASTY_AUDIT_PATH", "prod-audit/tastytrade.jsonl")

    settings = TastySettings.from_env_for_mode(is_test=False)

    assert settings.environment == "production"
    assert settings.env_prefix == "TASTY_PROD"
    assert settings.client_secret == "prod-secret"
    assert settings.refresh_token == "prod-refresh"
    assert settings.account_number == "PROD123"
    assert settings.client_id == "prod-client"
    assert settings.redirect_uri.endswith("/prod")
    assert settings.audit_path == Path("prod-audit/tastytrade.jsonl")


def test_from_env_for_mode_falls_back_to_generic_names(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TASTY_CLIENT_SECRET", "generic-secret")
    monkeypatch.setenv("TASTY_REFRESH_TOKEN", "generic-refresh")
    monkeypatch.setenv("TASTY_ACCOUNT_NUMBER", "GENERIC")

    settings = TastySettings.from_env_for_mode(is_test=True)

    assert settings.client_secret == "generic-secret"
    assert settings.refresh_token == "generic-refresh"
    assert settings.account_number == "GENERIC"


def test_from_env_resolves_legacy_mode_to_explicit_profile(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TASTY_IS_TEST", "false")
    monkeypatch.setenv("TASTY_PROD_CLIENT_SECRET", "prod-secret")
    monkeypatch.setenv("TASTY_PROD_REFRESH_TOKEN", "prod-refresh")
    monkeypatch.setenv("TASTY_PROD_ACCOUNT_NUMBER", "PROD123")

    settings = TastySettings.from_env()

    assert settings.environment == "production"
    assert settings.client_secret == "prod-secret"
    assert settings.account_number == "PROD123"


def test_missing_credentials_error_names_selected_profile(monkeypatch):
    _clean_env(monkeypatch)

    with pytest.raises(ValueError) as excinfo:
        TastySettings.from_env_for_mode(is_test=False)

    message = str(excinfo.value)
    assert "production" in message
    assert "TASTY_PROD_CLIENT_SECRET (or TASTY_CLIENT_SECRET)" in message
    assert "TASTY_PROD_REFRESH_TOKEN (or TASTY_REFRESH_TOKEN)" in message
    assert "TASTY_PROD_ACCOUNT_NUMBER (or TASTY_ACCOUNT_NUMBER)" in message
