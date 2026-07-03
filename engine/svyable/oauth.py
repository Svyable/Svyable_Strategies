"""One-time Tastytrade OAuth2 authorization-code onboarding.

The daily loop authenticates silently with a stored ``refresh_token`` (the token
grant needs no 2FA). That refresh token is produced exactly once, interactively,
by this module:

    1. open the Tastytrade login page (the user completes Duo 2FA there);
    2. Tastytrade redirects back to ``redirect_uri`` with a short-lived ``code``;
    3. a tiny loopback HTTP server captures the code (no copy/paste);
    4. we exchange ``code`` -> ``refresh_token`` + ``access_token``;
    5. the refresh token and discovered account number are written to ``.env``.

Nothing here is ever logged in cleartext. Secrets are masked in all output.
"""

from __future__ import annotations

import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

from svyable.broker_settings import TastySettings

USER_AGENT = "svyable-engine/0.1"


def mask(value: str) -> str:
    """Show only enough of a secret to confirm identity, never the whole thing."""
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]} ({len(value)} chars)"


def build_authorize_url(settings: TastySettings, state: str, scope: str = "") -> str:
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if scope:
        params["scope"] = scope
    return f"{settings.authorize_url}?{urllib.parse.urlencode(params)}"


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = (query.get("code") or [None])[0]
        _CallbackHandler.state = (query.get("state") or [None])[0]
        _CallbackHandler.error = (query.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = _CallbackHandler.code and not _CallbackHandler.error
        body = (
            "<h2>Svyable &times; Tastytrade authorization "
            f"{'complete' if ok else 'failed'}.</h2>"
            "<p>You can close this tab and return to the terminal.</p>"
        )
        self.wfile.write(body.encode())

    def log_message(self, *_args) -> None:  # silence default request logging
        return


def capture_authorization_code(redirect_uri: str, timeout: float = 300.0) -> tuple[str, str | None]:
    """Serve the redirect_uri once and return (code, state). Raises on timeout."""
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _CallbackHandler.code = _CallbackHandler.state = _CallbackHandler.error = None

    server = HTTPServer((host, port), _CallbackHandler)
    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout)
    server.server_close()

    if _CallbackHandler.error:
        raise RuntimeError(f"authorization denied: {_CallbackHandler.error}")
    if not _CallbackHandler.code:
        raise TimeoutError(
            f"no authorization code received on {redirect_uri} within {timeout:.0f}s"
        )
    return _CallbackHandler.code, _CallbackHandler.state


def exchange_code_for_tokens(settings: TastySettings, code: str) -> dict:
    """Trade the one-time code for tokens. Returns the raw token payload."""
    resp = requests.post(
        f"{settings.api_base}/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "redirect_uri": settings.redirect_uri,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def discover_account_number(settings: TastySettings, access_token: str) -> str | None:
    """Return the first (or pinned) trading account number, or None if unavailable."""
    try:
        resp = requests.get(
            f"{settings.api_base}/customers/me/accounts",
            headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("items", [])
        numbers = [
            str(item.get("account", {}).get("account-number", "")).strip()
            for item in items
        ]
        numbers = [n for n in numbers if n]
        if settings.account_number and settings.account_number in numbers:
            return settings.account_number
        return numbers[0] if numbers else None
    except Exception:  # noqa: BLE001 — discovery is best-effort; never fatal
        return None


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Idempotently set KEY=value lines in an .env, preserving everything else."""
    env_path = Path(env_path)
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n")


def authorize(env_path: Path, *, open_browser: bool = True, scope: str = "") -> dict:
    """Full interactive onboarding. Writes refresh token + account to `env_path`.

    Returns a redacted summary dict — never the raw tokens.
    """
    settings = TastySettings.from_env(require_credentials=False)
    problems = []
    if not settings.client_id:
        problems.append("TASTY_CLIENT_ID")
    if not settings.client_secret:
        problems.append("TASTY_CLIENT_SECRET")
    if not settings.redirect_uri:
        problems.append("TASTY_REDIRECT_URI (must match the value registered on the OAuth app)")
    if problems:
        raise RuntimeError("Set these in engine/.env before authorizing: " + ", ".join(problems))

    state = secrets.token_urlsafe(16)
    url = build_authorize_url(settings, state, scope=scope)
    print(f"environment : {settings.environment}  ({settings.api_base})")
    print(f"redirect_uri: {settings.redirect_uri}")
    print(f"client_id   : {mask(settings.client_id)}")
    print("\nOpen this URL, sign in, and approve (Duo 2FA happens on Tastytrade's page):\n")
    print(url + "\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    print(f"Waiting for the redirect on {settings.redirect_uri} …")
    code, returned_state = capture_authorization_code(settings.redirect_uri)
    if returned_state != state:
        raise RuntimeError("state mismatch — possible CSRF; aborting without writing tokens")

    tokens = exchange_code_for_tokens(settings, code)
    refresh_token = tokens.get("refresh_token", "")
    access_token = tokens.get("access_token", "")
    if not refresh_token:
        raise RuntimeError("token endpoint returned no refresh_token")

    account = discover_account_number(settings, access_token) or settings.account_number
    updates = {"TASTY_REFRESH_TOKEN": refresh_token}
    if account:
        updates["TASTY_ACCOUNT_NUMBER"] = account
    update_env_file(env_path, updates)

    return {
        "environment": settings.environment,
        "refresh_token": mask(refresh_token),
        "account_number": account or "<none discovered — set TASTY_ACCOUNT_NUMBER manually>",
        "env_file": str(env_path),
        "wrote": sorted(updates),
    }
