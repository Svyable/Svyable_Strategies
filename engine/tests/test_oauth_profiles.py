"""Tests for profile-aware OAuth env-file writes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.broker_settings import TastySettings
from svyable.oauth import authorization_problem_names, token_update_keys, update_env_file


def _settings(**overrides) -> TastySettings:
    base = dict(
        client_secret="secret",
        refresh_token="",
        account_number="ACC123",
        client_id="client",
        redirect_uri="http://127.0.0.1:8182/callback",
    )
    base.update(overrides)
    return TastySettings(**base)


def test_authorization_problem_names_use_selected_profile():
    problems = authorization_problem_names(
        _settings(is_test=False, client_id="", client_secret="", redirect_uri="")
    )

    joined = " | ".join(problems)
    assert "TASTY_PROD_CLIENT_ID" in joined
    assert "TASTY_PROD_CLIENT_SECRET" in joined
    assert "TASTY_PROD_REDIRECT_URI" in joined
    assert "TASTY_CLIENT_ID" in joined
    assert "TASTY_CLIENT_SECRET" in joined
    assert "TASTY_REDIRECT_URI" in joined


def test_token_update_keys_are_profile_specific():
    updates = token_update_keys(_settings(is_test=True), "SANDBOX123")
    assert set(updates) == {"TASTY_SANDBOX_REFRESH_TOKEN", "TASTY_SANDBOX_ACCOUNT_NUMBER"}

    updates = token_update_keys(_settings(is_test=False), "PROD123")
    assert set(updates) == {"TASTY_PROD_REFRESH_TOKEN", "TASTY_PROD_ACCOUNT_NUMBER"}


def test_update_env_file_preserves_existing_lines_and_replaces_keys(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP_ME=1\nTASTY_SANDBOX_REFRESH_TOKEN=old\n", encoding="utf-8")

    update_env_file(
        env_path,
        {
            "TASTY_SANDBOX_REFRESH_TOKEN": "new",
            "TASTY_SANDBOX_ACCOUNT_NUMBER": "ACC123",
        },
    )

    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "KEEP_ME=1",
        "TASTY_SANDBOX_REFRESH_TOKEN=new",
        "TASTY_SANDBOX_ACCOUNT_NUMBER=ACC123",
    ]
