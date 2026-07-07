"""Offline API-runtime hardening regressions."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.dxlink import fetch_quote_token
from svyable.oauth import update_env_file


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_oauth_env_file_is_owner_read_write_only(tmp_path):
    env_path = tmp_path / "nested" / ".env"

    update_env_file(env_path, {"TASTY_REFRESH_TOKEN": "refresh", "TASTY_ACCOUNT_NUMBER": "ACCT123"})

    assert "TASTY_REFRESH_TOKEN=refresh" in env_path.read_text()
    assert _mode(env_path) == 0o600


def test_dxlink_quote_token_cache_is_owner_read_write_only(tmp_path):
    class FakeTastyClient:
        def __init__(self):
            self.calls = 0

        def request(self, method: str, path: str):
            self.calls += 1
            assert (method, path) == ("GET", "/api-quote-tokens")
            return {"token": "quote-token", "dxlink-url": "wss://example.invalid"}

    cache = tmp_path / "tokens" / "quote_token.json"
    client = FakeTastyClient()

    token, url = fetch_quote_token(client, cache)
    cached_token, cached_url = fetch_quote_token(client, cache)

    assert (token, url) == ("quote-token", "wss://example.invalid")
    assert (cached_token, cached_url) == (token, url)
    assert client.calls == 1
    assert _mode(cache) == 0o600


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        test_oauth_env_file_is_owner_read_write_only(root)
        test_dxlink_quote_token_cache_is_owner_read_write_only(root)
    print("API RUNTIME SAFETY TESTS PASSED")
