"""Low-level tastytrade REST client for data/session support.

``TastytradeClient`` remains for paths that still need direct REST transport,
quote-token retrieval, or DXLink candle support. Order management must use the
SDK adapter in ``svyable.tastytrade_sdk.TastySdkBroker``.

Settings are loaded through ``svyable.broker_settings.TastySettings`` so OAuth,
SDK execution, and REST data transport share one environment contract. Canonical
``TASTY_*`` names are preferred; legacy ``TT_*`` aliases remain accepted through
that settings layer.

API conventions honored: mandatory User-Agent, dasherized JSON keys, {"data": ...}
response envelope, query-array `key[]=` params, 429 backoff, one re-auth on 401.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from svyable.broker_settings import TastySettings

USER_AGENT = "svyable-engine/0.1"

__all__ = ["TastytradeClient"]


class TastytradeClient:
    """Low-level REST client with token lifecycle management.

    This client is intentionally transport-only. It is still used by data/session
    paths, including DXLink quote-token and candle workflows, but it is not a
    broker adapter. All order lifecycle code belongs in ``TastySdkBroker``.
    """

    def __init__(
        self,
        env: str | None = None,
        allow_production: bool = False,
        settings: TastySettings | None = None,
    ):
        base_settings = settings or TastySettings.from_env(require_credentials=False)
        if env is not None:
            requested = env.lower().strip()
            if requested not in {"sandbox", "production", "cert", "test"}:
                raise ValueError("env must be sandbox or production")
            base_settings = replace(base_settings, is_test=requested != "production")

        self.settings = base_settings
        self.env = self.settings.environment
        if self.env == "production" and not allow_production:
            raise RuntimeError("production env requires allow_production=True from the caller")
        self.base = self.settings.api_base

        # OAuth refresh-token transport is canonical. Username/password session
        # auth remains available for sandbox-only legacy setups.
        if self.settings.has_oauth_refresh_credentials:
            self.auth_mode = "oauth"
        elif self.settings.has_session_credentials:
            self.auth_mode = "session"
        else:
            raise RuntimeError(
                "set TASTY_CLIENT_SECRET/TASTY_REFRESH_TOKEN (OAuth) or "
                "TASTY_USERNAME/TASTY_PASSWORD (sandbox session) in the environment"
            )

        self._token: str = ""
        self._token_expiry: float = 0.0

    # ---- auth --------------------------------------------------------------

    def _authenticate(self) -> None:
        import requests
        if self.auth_mode == "oauth":
            r = requests.post(f"{self.base}/oauth/token", json={
                "grant_type": "refresh_token",
                "refresh_token": self.settings.refresh_token,
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
            }, headers={"User-Agent": USER_AGENT}, timeout=15)
            r.raise_for_status()
            js = r.json()
            self._token = js["access_token"]
            self._token_expiry = time.time() + float(js.get("expires_in", 900)) - 60
        else:
            r = requests.post(f"{self.base}/sessions", json={
                "login": self.settings.username, "password": self.settings.password,
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
