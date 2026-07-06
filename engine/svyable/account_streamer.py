"""tastytrade Account Streamer — push notifications for orders, balances,
positions over websocket. Replaces per-order-id polling with real-time state.

Protocol (per docs, order matters): open websocket -> send `connect` with
account list + auth-token -> heartbeat every 20s (allowed 2s-1m). All
notifications carry a full object in `data` keyed by `type` (Order, ...).
auth-token = "Bearer <access token>" for OAuth, raw session token otherwise.
"""

from __future__ import annotations

import json
import time

HOSTS = {"sandbox": "wss://streamer.cert.tastyworks.com",
         "production": "wss://streamer.tastyworks.com"}


def parse_notification(raw: str | dict) -> dict:
    """Normalize a streamer message -> {"type", "data", "timestamp"} or
    {"type": "control", ...} for status/heartbeat acks."""
    msg = json.loads(raw) if isinstance(raw, str) else raw
    if "type" in msg and "data" in msg:
        return {"type": msg["type"], "data": msg["data"],
                "timestamp": msg.get("timestamp")}
    return {"type": "control", "status": msg.get("status"),
            "action": msg.get("action"), "raw": msg}


class AccountStreamer:
    def __init__(self, tt_client, account_numbers: list[str] | None = None):
        self.tt = tt_client
        self.accounts = account_numbers

    def _auth_value(self) -> str:
        return self.tt._auth_header()          # already Bearer-prefixed for OAuth

    def _connect(self):
        import websocket
        ws = websocket.create_connection(
            HOSTS["production" if self.tt.env == "production" else "sandbox"],
            timeout=10)
        ws.send(json.dumps({"action": "connect", "value": self.accounts,
                            "auth-token": self._auth_value(), "request-id": 1}))
        ack = parse_notification(ws.recv())
        if ack.get("type") == "control" and ack.get("status") != "ok":
            ws.close()
            raise RuntimeError(f"account streamer connect failed: {ack}")
        return ws

    def watch_orders(self, order_ids: list[int], *, timeout_s: float = 300.0,
                     terminal: frozenset | None = None) -> dict[int, dict]:
        """Block until every order id reaches a terminal status (or timeout).
        Returns {order_id: last order json}. Push-based — zero REST polling."""
        from svyable.tastytrade_sdk import TERMINAL_ORDER_STATUSES
        terminal = terminal or TERMINAL_ORDER_STATUSES
        pending = set(order_ids)
        seen: dict[int, dict] = {}
        ws = self._connect()
        ws.settimeout(5.0)
        last_beat = time.time()
        t0 = time.time()
        try:
            while pending and time.time() - t0 < timeout_s:
                if time.time() - last_beat > 20:
                    ws.send(json.dumps({"action": "heartbeat",
                                        "auth-token": self._auth_value()}))
                    last_beat = time.time()
                try:
                    n = parse_notification(ws.recv())
                except Exception:  # noqa: BLE001 — recv timeout, keep beating
                    continue
                if n["type"] != "Order":
                    continue
                o = n["data"]
                oid = o.get("id")
                if oid in pending or oid in seen:
                    seen[oid] = o
                    if o.get("status") in terminal:
                        pending.discard(oid)
        finally:
            ws.close()
        return seen

    def stream(self, on_message, run_s: float = 3600.0) -> None:
        """Generic loop: call on_message(parsed) for every notification."""
        ws = self._connect()
        ws.settimeout(5.0)
        last_beat = time.time()
        t0 = time.time()
        try:
            while time.time() - t0 < run_s:
                if time.time() - last_beat > 20:
                    ws.send(json.dumps({"action": "heartbeat",
                                        "auth-token": self._auth_value()}))
                    last_beat = time.time()
                try:
                    on_message(parse_notification(ws.recv()))
                except Exception:  # noqa: BLE001 — recv timeout
                    continue
        finally:
            ws.close()
