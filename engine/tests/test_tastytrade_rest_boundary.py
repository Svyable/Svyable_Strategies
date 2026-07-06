"""Import-boundary regression for the low-level tastytrade REST module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import svyable.tastytrade as tastytrade
from svyable.broker_settings import TastySettings


_TASTY_ENV_NAMES = (
    "TASTY_CLIENT_SECRET",
    "TASTY_REFRESH_TOKEN",
    "TASTY_ACCOUNT_NUMBER",
    "TASTY_CLIENT_ID",
    "TASTY_REDIRECT_URI",
    "TASTY_USERNAME",
    "TASTY_PASSWORD",
    "TASTY_IS_TEST",
    "TT_CLIENT_SECRET",
    "TT_REFRESH_TOKEN",
    "TT_ACCOUNT",
    "TT_CLIENT_ID",
    "TT_REDIRECT_URI",
    "TT_USERNAME",
    "TT_PASSWORD",
    "TT_ENV",
    "SVYABLE_ENV",
    "SVYABLE_ENABLE_LIVE",
    "SVYABLE_TASTY_AUDIT_PATH",
    "SVYABLE_SLIPPAGE_WARN_BPS",
    "SVYABLE_SLIPPAGE_CRITICAL_BPS",
)


@pytest.fixture(autouse=True)
def clean_tasty_env(monkeypatch):
    # ``TastySettings.from_env`` calls ``load_dotenv``, which would otherwise
    # re-inject a developer's local ``engine/.env`` (e.g. production credentials)
    # right after we clear the process environment — defeating the point of these
    # hermetic boundary tests. Neutralize it so the tests assert on the env we set.
    monkeypatch.setattr("svyable.broker_settings.load_dotenv", lambda *args, **kwargs: False)
    for name in _TASTY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_tastytrade_rest_module_exports_only_transport_client():
    assert tastytrade.__all__ == ["TastytradeClient"]
    assert hasattr(tastytrade, "TastytradeClient")
    assert not hasattr(tastytrade, "TastytradeBroker")
    assert "Broker" not in tastytrade.__all__


def test_rest_client_uses_canonical_shared_oauth_settings(monkeypatch):
    monkeypatch.setenv("TASTY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TASTY_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("TASTY_ACCOUNT_NUMBER", "ACCT123")
    monkeypatch.setenv("TASTY_CLIENT_ID", "client-id")
    monkeypatch.setenv("TASTY_IS_TEST", "true")

    settings = TastySettings.from_env(require_credentials=False)
    client = tastytrade.TastytradeClient(settings=settings)

    assert client.settings is settings
    assert client.auth_mode == "oauth"
    assert client.env == "sandbox"
    assert client.base == settings.api_base
    assert settings.has_oauth_refresh_credentials
    assert not settings.has_session_credentials


def test_rest_client_uses_legacy_session_settings_without_direct_env_reads(monkeypatch):
    monkeypatch.setenv("TT_USERNAME", "legacy-user")
    monkeypatch.setenv("TT_PASSWORD", "legacy-pass")
    monkeypatch.setenv("TT_ENV", "sandbox")

    settings = TastySettings.from_env(require_credentials=False)
    client = tastytrade.TastytradeClient(settings=settings)

    assert settings.username == "legacy-user"
    assert settings.password == "legacy-pass"
    assert client.auth_mode == "session"
    assert client.env == "sandbox"


def test_rest_client_requires_transport_credentials():
    settings = TastySettings(
        client_secret="",
        refresh_token="",
        account_number="",
        username="",
        password="",
    )

    with pytest.raises(RuntimeError, match="TASTY_CLIENT_SECRET/TASTY_REFRESH_TOKEN"):
        tastytrade.TastytradeClient(settings=settings)


def test_rest_client_keeps_production_transport_guard():
    settings = TastySettings(
        client_secret="secret",
        refresh_token="refresh",
        account_number="ACCT123",
        is_test=False,
    )

    with pytest.raises(RuntimeError, match="production env requires"):
        tastytrade.TastytradeClient(settings=settings)

    client = tastytrade.TastytradeClient(settings=settings, allow_production=True)
    assert client.env == "production"
    assert client.base == settings.api_base


def test_rest_client_env_override_preserves_old_constructor_shape():
    settings = TastySettings(
        client_secret="secret",
        refresh_token="refresh",
        account_number="ACCT123",
        is_test=True,
    )

    client = tastytrade.TastytradeClient(settings=settings, env="sandbox")
    assert client.env == "sandbox"

    with pytest.raises(RuntimeError, match="production env requires"):
        tastytrade.TastytradeClient(settings=settings, env="production")


if __name__ == "__main__":
    test_tastytrade_rest_module_exports_only_transport_client()
    print("TASTY REST BOUNDARY TESTS PASSED")
