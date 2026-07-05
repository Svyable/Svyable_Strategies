"""Legacy tastytrade REST support.

``TastytradeClient`` remains the low-level REST client used by data/session paths
that still need quote tokens or DXLink candle support. New order-management code
must use ``svyable.tastytrade_sdk.TastySdkBroker``.

Environments (never mixed):
  sandbox     https://api.cert.tastyworks.com   (default — fake money)
  production  https://api.tastyworks.com        (requires TT_ENV=production explicitly)

Auth (auto-selected from env):
  OAuth2:  TT_CLIENT_ID + TT_CLIENT_SECRET + TT_REFRESH_TOKEN
           -> POST /oauth/token; access tokens live 15 min, refreshed with 60s margin;
           Authorization: Bearer <token>
  Session: TT_USERNAME + TT_PASSWORD (typical for sandbox)
           -> POST /sessions; Authorization: <session-token> (no Bearer prefix)

Optional: TT_ACCOUNT pins the account number (else first account is used).

API conventions honored: mandatory User-Agent, dasherized JSON keys, {"data": ...}
response envelope, query-array `key[]=` params, 429 backoff, one re-auth on 401.

Legacy order adapter note:
- ``TastytradeBroker`` is retained only for backwards compatibility.
- It is not used by the current CLI rebalance/tasty order paths.
- Do not extend its order lifecycle methods; migrate callers to ``TastySdkBroker``.
"""

from __future__ import annotations

import os
import time
import warnings
from datetime import datetime
from typing import Any

USER_AGENT = "svyable-engine/0.1"
SANDBOX_URL = "https://api.cert.tastyworks.com"
PRODUCTION_URL = "https://api.tastyworks.com"

# Order Status Definitions (tastytrade docs). Non-terminal statuses like
# Received/Routed/In Flight/Live/Cancel Requested/Replace Requested/Contingent
# still move; these do not.
TERMINAL_ORDER_STATUSES = frozenset({
    "Filled", "Cancelled", "Expired", "Rejected", "Removed", "Partially Removed",
})


class TastytradeClient:
    """Low-level REST client with token lifecycle management.

    This client is still used for REST-backed data/session support. It should not
    be used as the canonical live order adapter; use ``TastySdkBroker`` for that.
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


class TastytradeBroker:
    """Deprecated REST BrokerConnector adapter.

    This class is retained to avoid breaking old imports, but the canonical order
    adapter is ``svyable.tastytrade_sdk.TastySdkBroker``. Current CLI order paths
    use the SDK adapter because it has typed intents, redacted audit logging,
    account confirmation gates, and explicit open/close actions.
    """

    def __init__(self, env: str | None = None, allow_production: bool = False,
                 client: TastytradeClient | None = None):
        warnings.warn(
            "TastytradeBroker is deprecated for order management; use "
            "svyable.tastytrade_sdk.TastySdkBroker instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.c = client or TastytradeClient(env=env, allow_production=allow_production)
        self._account: str = os.environ.get("TT_ACCOUNT", "")

    # ---- account ------------------------------------------------------------

    @property
    def account(self) -> str:
        if not self._account:
            items = self.c.request("GET", "/customers/me/accounts").get("items", [])
            if not items:
                raise RuntimeError("no tastytrade accounts on this login")
            self._account = items[0]["account"]["account-number"]
        return self._account

    def get_account(self) -> dict:
        b = self.c.request("GET", f"/accounts/{self.account}/balances")
        return {"equity": float(b.get("net-liquidating-value", 0.0)),
                "cash": float(b.get("cash-balance", 0.0)),
                "buying_power": float(b.get("equity-buying-power",
                                            b.get("derivative-buying-power", 0.0)))}

    def get_positions(self) -> dict[str, float]:
        items = self.c.request("GET", f"/accounts/{self.account}/positions").get("items", [])
        out: dict[str, float] = {}
        for p in items:
            if p.get("instrument-type") != "Equity":
                continue
            qty = float(p.get("quantity", 0.0))
            if p.get("quantity-direction") == "Short":
                qty = -qty
            if abs(qty) > 1e-9:
                out[p["symbol"]] = out.get(p["symbol"], 0.0) + qty
        return out

    # ---- order construction ---------------------------------------------------

    @staticmethod
    def build_equity_order(symbol: str, qty: float, side: str, *,
                           order_type: str = "market", tif: str = "day",
                           price: float | None = None) -> dict:
        action = "Buy to Open" if side == "buy" else "Sell to Close"
        order: dict = {
            "time-in-force": {"day": "Day", "gtc": "GTC"}[tif.lower()],
            "order-type": {"market": "Market", "limit": "Limit"}[order_type.lower()],
            "legs": [{"instrument-type": "Equity", "symbol": symbol,
                      "quantity": int(qty), "action": action}],
        }
        if order_type.lower() == "limit":
            if price is None:
                raise ValueError("limit order requires price")
            order["price"] = round(float(price), 2)
            order["price-effect"] = "Debit" if side == "buy" else "Credit"
        return order

    # ---- order lifecycle --------------------------------------------------------

    def dry_run(self, order: dict) -> dict:
        d = self.c.request("POST", f"/accounts/{self.account}/orders/dry-run", body=order)
        bp = d.get("buying-power-effect", {})
        fees = d.get("fee-calculation", {})
        return {"warnings": d.get("warnings", []),
                "buying_power_impact": bp.get("impact"),
                "new_buying_power": bp.get("new-buying-power"),
                "total_fees": fees.get("total-fees")}

    def submit_order(self, symbol: str, qty: float, side: str,
                     order_type: str = "market", tif: str = "day",
                     price: float | None = None) -> dict:
        warnings.warn(
            "TastytradeBroker.submit_order is deprecated; use "
            "TastySdkBroker.submit_intent with confirmation-aware gates.",
            DeprecationWarning,
            stacklevel=2,
        )
        order = self.build_equity_order(symbol, qty, side, order_type=order_type,
                                        tif=tif, price=price)
        check = self.dry_run(order)
        if check["warnings"]:
            return {"status": "rejected_dry_run", "symbol": symbol, "qty": qty,
                    "side": side, "warnings": check["warnings"]}
        d = self.c.request("POST", f"/accounts/{self.account}/orders", body=order)
        o = d.get("order", {})
        return {"status": o.get("status", "submitted"), "id": o.get("id"),
                "symbol": symbol, "qty": qty, "side": side,
                "fees": check["total_fees"], "bp_impact": check["buying_power_impact"]}

    def get_order(self, order_id: int) -> dict:
        return self.c.request("GET", f"/accounts/{self.account}/orders/{order_id}")

    def search_orders(self, *, start_date: str | None = None,
                      status: list[str] | None = None, per_page: int = 50) -> list[dict]:
        params: dict = {"per-page": per_page, "sort": "Desc"}
        if start_date:
            params["start-date"] = start_date
        if status:
            params["status[]"] = status
        return self.c.request("GET", f"/accounts/{self.account}/orders",
                              params=params).get("items", [])

    def cancel_order(self, order_id: int) -> dict:
        warnings.warn(
            "TastytradeBroker.cancel_order is deprecated; use "
            "TastySdkBroker.cancel_order with confirmation-aware gates.",
            DeprecationWarning,
            stacklevel=2,
        )
        d = self.c.request("DELETE", f"/accounts/{self.account}/orders/{order_id}")
        return {"id": order_id, "status": d.get("status", "Cancel Requested")}

    def cancel_replace(self, order_id: int, original_order: dict, *,
                       price: float | None = None, order_type: str | None = None,
                       tif: str | None = None) -> dict:
        warnings.warn(
            "TastytradeBroker.cancel_replace is deprecated; use the SDK adapter "
            "for future order lifecycle work.",
            DeprecationWarning,
            stacklevel=2,
        )
        body = dict(original_order)
        if price is not None:
            body["price"] = round(float(price), 2)
        if order_type:
            body["order-type"] = order_type
        if tif:
            body["time-in-force"] = tif
        return self.c.request("PUT", f"/accounts/{self.account}/orders/{order_id}",
                              body=body)

    def poll_order(self, order_id: int, *, timeout_s: float = 120.0,
                   interval_s: float = 5.0) -> dict:
        """Poll a single order id to a terminal state (NOT the /orders/live list —
        tastytrade explicitly forbids polling that endpoint)."""
        t0 = time.time()
        while True:
            o = self.get_order(order_id)
            if o.get("status") in TERMINAL_ORDER_STATUSES or time.time() - t0 > timeout_s:
                return o
            time.sleep(interval_s)

    # ---- market data (synchronous REST snapshot) --------------------------------

    def get_market_snapshot(self, symbols: list[str]) -> dict[str, dict]:
        """Spot quotes via GET /market-data/by-type (batched). Returns per symbol:
        last/close/prev_close/bid/ask/mid as floats where present. Used for
        execution pricing and cross-provider close checks — no websocket needed."""
        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None

        out: dict[str, dict] = {}
        for i in range(0, len(symbols), 90):
            batch = symbols[i:i + 90]
            # per docs: comma-delimited symbol list keyed by security type
            d = self.c.request("GET", "/market-data/by-type",
                               params={"equity": ",".join(batch)})
            for q in d.get("items", []):
                sym = q.get("symbol")
                if not sym:
                    continue
                bid, ask = _f(q.get("bid")), _f(q.get("ask"))
                out[sym] = {
                    "mark": _f(q.get("mark")),
                    "mid": _f(q.get("mid")) or ((bid + ask) / 2 if bid and ask else None),
                    "last": _f(q.get("last")),
                    "close": _f(q.get("close")),
                    "prev_close": _f(q.get("prev-close")),
                    "bid": bid, "ask": ask,
                    "open": _f(q.get("open")),
                    "volume": _f(q.get("volume")),
                    "beta": _f(q.get("beta")),
                    "year_high": _f(q.get("year-high-price")),
                    "year_low": _f(q.get("year-low-price")),
                    "halted": bool(q.get("is-trading-halted", False)),
                }
        return out

    def pnl_report(self) -> dict:
        """Position + account P/L per the tastytrade formulas:
        unrealized = (mark - average-open-price) * qty * multiplier * dir
        day P/L    = (mark - average-daily-market-close-price) * qty * mult * dir
                     + realized-day-gain (if dated today)
        value      = mark * qty * mult * dir
        net liq    = sum(values) + cash-balance + pending-cash (signed by effect)
        """
        items = self.c.request("GET", f"/accounts/{self.account}/positions").get("items", [])
        marks = self.execution_prices(sorted({p["symbol"] for p in items
                                              if p.get("instrument-type") == "Equity"}))
        today = datetime.now().strftime("%Y-%m-%d")

        def _f(x, d=0.0):
            try:
                return float(x)
            except (TypeError, ValueError):
                return d

        positions, total_value, total_unreal, total_day = [], 0.0, 0.0, 0.0
        for p in items:
            if p.get("instrument-type") != "Equity":
                continue
            qty, mult = _f(p.get("quantity")), _f(p.get("multiplier"), 1.0)
            if qty == 0:
                continue
            d = -1.0 if p.get("quantity-direction") == "Short" else 1.0
            sym = p["symbol"]
            mark = marks.get(sym) or _f(p.get("close-price"))
            avg_open = _f(p.get("average-open-price"))
            day_basis = _f(p.get("average-daily-market-close-price"), avg_open)
            unreal = (mark - avg_open) * qty * mult * d
            day_unreal = (mark - day_basis) * qty * mult * d
            r_day = _f(p.get("realized-day-gain"))
            if p.get("realized-day-gain-date") != today:
                r_day = 0.0
            elif p.get("realized-day-gain-effect") == "Debit":
                r_day = -r_day
            value = mark * qty * mult * d
            positions.append({"symbol": sym, "qty": qty * d, "mark": mark,
                              "avg_open": avg_open,
                              "unrealized": round(unreal, 2),
                              "pl_day": round(day_unreal + r_day, 2),
                              "value": round(value, 2)})
            total_value += value
            total_unreal += unreal
            total_day += day_unreal + r_day

        b = self.c.request("GET", f"/accounts/{self.account}/balances")
        cash = _f(b.get("cash-balance"))
        pending = _f(b.get("pending-cash"))
        if b.get("pending-cash-effect") == "Debit":
            pending = -pending
        return {"account": self.account,
                "positions": sorted(positions, key=lambda x: -abs(x["value"])),
                "total_position_value": round(total_value, 2),
                "cash_balance": round(cash, 2), "pending_cash": round(pending, 2),
                "net_liq": round(total_value + cash + pending, 2),
                "total_unrealized": round(total_unreal, 2),
                "total_pl_day": round(total_day, 2)}

    def execution_prices(self, symbols: list[str],
                         skip_halted: bool = True) -> dict[str, float]:
        """Best price per symbol: mark > mid > last > close > prev_close.
        Halted names are excluded by default — never price an order in a halt."""
        snap = self.get_market_snapshot(symbols)
        out: dict[str, float] = {}
        for sym, q in snap.items():
            if skip_halted and q.get("halted"):
                continue
            px = q.get("mark") or q.get("mid") or q.get("last") \
                or q.get("close") or q.get("prev_close")
            if px and px > 0:
                out[sym] = float(px)
        return out

    def status_snapshot(self) -> dict:
        """One-call health view for the CLI / Claude loop."""
        acct = self.get_account()
        pos = self.get_positions()
        today = datetime.now().strftime("%Y-%m-%d")
        orders = self.search_orders(start_date=today)
        return {"env": self.c.env, "auth_mode": self.c.auth_mode,
                "account": self.account, "balances": acct,
                "positions": pos, "orders_today": [
                    {"id": o.get("id"), "status": o.get("status"),
                     "symbol": o.get("underlying-symbol"),
                     "type": o.get("order-type"), "size": o.get("size")}
                    for o in orders]}
