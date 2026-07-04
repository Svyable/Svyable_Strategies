"""Unit tests for the pure display/gate helpers behind the console creature comforts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.dashboard_ui import broker_ready, short_hash


def _settings(**overrides) -> TastySettings:
    base = dict(
        client_secret="secret",
        refresh_token="refresh",
        account_number="ACC123",
    )
    base.update(overrides)
    return TastySettings(**base)


def test_short_hash_truncates_long_values():
    assert short_hash("84d90231abcdef0123456789") == "84d90231…"


def test_short_hash_leaves_short_values_untouched():
    assert short_hash("abc123") == "abc123"
    assert short_hash("") == "—"
    assert short_hash(None) == "—"
    assert short_hash("—") == "—"


def test_short_hash_respects_keep_length():
    assert short_hash("0123456789", keep=4) == "0123…"


def test_broker_ready_true_when_all_credentials_present():
    assert broker_ready(_settings()) is True


def test_broker_ready_false_when_refresh_token_missing():
    assert broker_ready(_settings(refresh_token="")) is False


def test_broker_ready_false_when_account_missing():
    assert broker_ready(_settings(account_number="")) is False


def test_broker_ready_false_when_secret_missing():
    assert broker_ready(_settings(client_secret="")) is False
