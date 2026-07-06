"""Runtime settings for Tastytrade connectivity and dashboard safety.

Secrets are loaded from the environment (optionally via ``engine/.env``). The
new ``TASTY_*`` names are canonical; legacy ``TT_*`` aliases remain accepted so
existing local automation does not break during migration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_float(value: str | None, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return default


@dataclass(frozen=True)
class TastySettings:
    client_secret: str
    refresh_token: str
    account_number: str
    is_test: bool = True
    live_enabled: bool = False
    audit_path: Path = Path("outputs/audit/tastytrade.jsonl")
    slippage_warn_bps: float = 15.0
    slippage_critical_bps: float = 30.0
    # Used only by the one-time OAuth authorization-code exchange (`svyable auth`),
    # not by the daily refresh-token grant — so they are never required credentials.
    client_id: str = ""
    redirect_uri: str = ""
    # Optional fallback for sandbox/session-token transport paths. The SDK broker
    # and production execution path use OAuth refresh-token credentials instead.
    username: str = ""
    password: str = ""

    @property
    def environment(self) -> str:
        return "sandbox" if self.is_test else "production"

    @property
    def api_base(self) -> str:
        """REST + token host for the selected environment."""
        return (
            "https://api.cert.tastyworks.com"
            if self.is_test
            else "https://api.tastyworks.com"
        )

    @property
    def authorize_url(self) -> str:
        """Human login page where the user grants the app (Duo 2FA happens here)."""
        return (
            "https://cert-my.staging-tasty.works/auth.html"
            if self.is_test
            else "https://my.tastytrade.com/auth.html"
        )

    @property
    def has_oauth_refresh_credentials(self) -> bool:
        return bool(self.client_secret and self.refresh_token)

    @property
    def has_session_credentials(self) -> bool:
        return bool(self.username and self.password)

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> "TastySettings":
        load_dotenv()

        client_secret = _first_env("TASTY_CLIENT_SECRET", "TT_CLIENT_SECRET")
        refresh_token = _first_env("TASTY_REFRESH_TOKEN", "TT_REFRESH_TOKEN")
        account_number = _first_env("TASTY_ACCOUNT_NUMBER", "TT_ACCOUNT")
        client_id = _first_env("TASTY_CLIENT_ID", "TT_CLIENT_ID")
        redirect_uri = _first_env("TASTY_REDIRECT_URI", "TT_REDIRECT_URI")
        username = _first_env("TASTY_USERNAME", "TT_USERNAME")
        password = _first_env("TASTY_PASSWORD", "TT_PASSWORD")

        explicit_test = os.getenv("TASTY_IS_TEST")
        if explicit_test is None:
            legacy_env = _first_env("SVYABLE_ENV", "TT_ENV", default="sandbox").lower()
            is_test = legacy_env != "production"
        else:
            is_test = _as_bool(explicit_test, default=True)

        live_enabled = _as_bool(os.getenv("SVYABLE_ENABLE_LIVE"), default=False)
        default_out = "outputs" if is_test else "outputs-production"
        audit_path = Path(
            os.getenv("SVYABLE_TASTY_AUDIT_PATH", f"{default_out}/audit/tastytrade.jsonl")
        )
        warn_bps = _as_float(os.getenv("SVYABLE_SLIPPAGE_WARN_BPS"), 15.0)
        critical_bps = _as_float(os.getenv("SVYABLE_SLIPPAGE_CRITICAL_BPS"), 30.0)
        if warn_bps <= 0 or critical_bps <= 0 or critical_bps < warn_bps:
            raise ValueError(
                "Slippage thresholds must be positive and critical must be >= warning."
            )

        missing = [
            name
            for name, value in {
                "TASTY_CLIENT_SECRET": client_secret,
                "TASTY_REFRESH_TOKEN": refresh_token,
                "TASTY_ACCOUNT_NUMBER": account_number,
            }.items()
            if not value
        ]
        if require_credentials and missing:
            raise ValueError(
                "Missing Tastytrade environment variables: " + ", ".join(missing)
            )

        return cls(
            client_secret=client_secret,
            refresh_token=refresh_token,
            account_number=account_number,
            is_test=is_test,
            live_enabled=live_enabled,
            audit_path=audit_path,
            slippage_warn_bps=warn_bps,
            slippage_critical_bps=critical_bps,
            client_id=client_id,
            redirect_uri=redirect_uri,
            username=username,
            password=password,
        )
