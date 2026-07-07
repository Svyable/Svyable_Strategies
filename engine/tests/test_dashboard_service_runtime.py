"""Tests for DashboardService broker/runtime boundary."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import svyable.dashboard_service as dashboard_service
from svyable.broker_settings import TastySettings
from svyable.dashboard_service import DashboardService


def _settings(**overrides) -> TastySettings:
    base = dict(
        client_secret="secret",
        refresh_token="refresh",
        account_number="ACC123",
    )
    base.update(overrides)
    return TastySettings(**base)


def test_broker_uses_injected_profile_settings(monkeypatch, tmp_path):
    captured = {}

    class FakeBroker:
        def __init__(self, *, settings):
            captured["settings"] = settings

    monkeypatch.setattr(dashboard_service, "TastySdkBroker", FakeBroker)
    settings = _settings(is_test=False, account_number="PROD123")
    service = DashboardService(output_root=tmp_path, settings=settings)

    broker = service.broker

    assert isinstance(broker, FakeBroker)
    assert captured["settings"].environment == "production"
    assert captured["settings"].account_number == "PROD123"
    assert captured["settings"].audit_path == tmp_path / "audit" / "tastytrade.jsonl"


def test_broker_missing_credentials_names_selected_profile(tmp_path):
    service = DashboardService(
        output_root=tmp_path,
        settings=_settings(
            is_test=False,
            client_secret="",
            refresh_token="",
            account_number="",
        ),
    )

    with pytest.raises(ValueError) as excinfo:
        _ = service.broker

    message = str(excinfo.value)
    assert "production" in message
    assert "TASTY_PROD_CLIENT_SECRET" in message
    assert "TASTY_PROD_REFRESH_TOKEN" in message
    assert "TASTY_PROD_ACCOUNT_NUMBER" in message
