"""Low-level tastytrade REST client for data/session support.

``TastytradeClient`` remains for paths that still need direct REST transport,
quote-token retrieval, or DXLink candle support. Order management must use the
SDK adapter in ``svyable.tastytrade_sdk.TastySdkBroker``.

Environments (never mixed):
  sandbox     https://api.cert.tastyworks.com   (default — fake money)
  production  https://api.tastyworks.com        (requires TT_ENV=production explicitly)

Auth (auto-selected from env):
  OAuth2:  TT_CLIENT_ID + TT_CLIENT_SECRET + TT_REFRESH_TOKEN
           -> POST /oauth/token; access tokens live 15 min, refreshed with 60s margin;
           Authorization: Bearer <token>
  Session: TT_USERNAME + TT_PASSWORD (typical for sandbox)
           -> POST /sessions; Authorization: <session-token> (no Bearer prefix)

Optional: TT_ACCOUNT pins the account number for callers that resolve account
metadata through REST.

API conventions honored: mandatory User-Agent, dasherized JSON keys, {"data": ...}
response envelope, query-array `key[]=` params, 429 backoff, one re-auth on 401.
"""

from __future__ import annotations

import os
import time
from typing import Any

USER_AGENT = "svyable-engine/0.1"
SANDBOX_URL = "https://api.cert.tastyworks.com"
PRODUCTION_URL = "https://api.tastyworks.com"

__all__ = ["TastytradeClient"]


class TastytradeClient:
    """Low-level REST client with token lifecycle management.

    This client is intentionally transport-only. It is still used by data/session
    paths, including DXLink quote-token and candle workflows, but it is not a
    broker adapter. All order lifecycle code belongs in ``TastySdkBroker``.
    """

    def __init__(self, env: str | None = None, allow_production: bool = False):
        self.env = (env or os.environ.get("TT_ENV", "sandbox")).lower()
        if self.env == "production" and not allow_production:
            raise RuntimeError("production env requires allow_production=True from the caller")
        self.base = PRODUCTION_URL if self.env == "production" else SANDBOX_URL

        self._client_id = os.environ.get("TT_CLIENT_ID", "")
        self._client_secret = os.environ.get("TT_CLIENT_SECRET", "")
        self._refresh_token = os.environ.get("TT_REFRESH_TOKEN", "")
        self._username = os.environ.get("TT_USERNAME", "")
        self._password = os.environ.get("TT_PASSWORD", "")

        # per docs, the refresh grant requires refresh_token + client_secret
        # (client_id is included when present; harmless per RFC 6749)
        if self._refresh_token and self._client_secret:
            self.auth_mode = "oauth"
        elif self._username and self._password:
            self.auth_mode = "session"
        else:
            raise RuntimeError(
                "set TT_CLIENT_ID/TT_CLIENT_SECRET/TT_REFRESH_TOKEN (OAuth) or "
                "TT_USERNAME/TT_PASSWORD (sandbox session) in the environment")

        self._token: str = ""
        self._token_expiry: float = 0.0

    # ---- auth --------------------------------------------------------------

    def _authenticate(self) -> None:
        import requests
        if self.auth_mode == "oauth":
            r = requests.post(f"{self.base}/oauth/token", json={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }, headers={"User-Agent": USER_AGENT}, timeout=15)
            r.raise_for_status()
            js = r.json()
            self._token = js["access_token"]
            self._token_expiry = time.time() + float(js.get("expires_in", 900)) - 60
        else:
            r = requests.post(f"{self.base}/sessions", json={
                "login": self._username, "password": self._password,
                "remember-me": True,
            }, headers={"User-Agent": USER_AGENT}, timeout=15)
            r.raise_for_status()
            self._token = r.json()["data"]["session-token"]
            self._token_expiry = time.time() + 23 * 3600   # session tokens ~24h

    def _auth_header(self) -> str:
        if not self._token or time.time() >= self._token_expiry:
            self._authenticate()
        return f"Bearer {self._token}" if self.auth_mode == "oauth" else self._token

    # ---- transport ----------------------------------------------------------

    def request(self, method: str, path: str, *, params: dict | None = None,
                body: dict | None = None, _retried: bool = False) -> Any:
        import requests
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": self._auth_header(),
        }
        for attempt in range(4):
            r = requests.request(method, f"{self.base}{path}", params=params,
                                 json=body, headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 401 and not _retried:
                self._token = ""                       # force re-auth, retry once
                return self.request(method, path, params=params, body=body, _retried=True)
            if r.status_code >= 400:
                try:
                    err = r.json().get("error", {})
                except Exception:  # noqa: BLE001
                    err = {}
                raise RuntimeError(f"tastytrade {r.status_code} "
                                   f"{err.get('code', '')}: {err.get('message', r.text[:200])}")
            return r.json().get("data", {}) if r.text else {}
        raise RuntimeError(f"rate-limited after retries: {path}")
