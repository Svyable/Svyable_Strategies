"""DXLink websocket client for tastytrade market data.

This module handles historical daily candles and streaming quote-token access
from tastytrade's market-data backbone. It is data-only; order management lives
in ``svyable.tastytrade_sdk.TastySdkBroker``.

Protocol order (per tastytrade docs): SETUP -> wait AUTH_STATE:UNAUTHORIZED ->
AUTH(api-quote-token) -> wait AUTHORIZED -> CHANNEL_REQUEST(FEED) -> FEED_SETUP
(COMPACT format) -> FEED_SUBSCRIPTION -> consume FEED_DATA -> KEEPALIVE every 30s.

Candle symbols: "AAPL{=1d}" with fromTime epoch-ms. DxLink streams from
fromTime to now, then keeps updating the live candle; completion is detected
by idle timeout per chunk (no end-time parameter exists).

Api quote tokens (GET /api-quote-tokens) live 24h and require a full tastytrade
customer account (sandbox username-only registrations get
quote_streamer.customer_not_found_error).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

CANDLE_FIELDS = ["eventType", "eventSymbol", "time", "open", "high", "low",
                 "close", "volume"]


def parse_feed_data(msg: dict, fields: list[str] = CANDLE_FIELDS) -> list[dict]:
    """Parse a COMPACT FEED_DATA message into event dicts.

    COMPACT payload: {"data": ["Candle", [v1..vN, v1..vN, ...]]} where each
    consecutive group of len(fields) values is one event in configured order.
    """
    out: list[dict] = []
    data = msg.get("data") or []
    i = 0
    while i + 1 < len(data) or (i == 0 and len(data) == 2):
        etype, values = data[i], data[i + 1]
        i += 2
        if not isinstance(values, list):
            continue
        n = len(fields)
        for j in range(0, len(values) - n + 1, n):
            ev = dict(zip(fields, values[j:j + n]))
            ev["eventType"] = etype if ev.get("eventType") in (etype, "", None) \
                else ev["eventType"]
            out.append(ev)
    return out


def _f(x) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


class DXLinkCandles:
    """Blocking candle fetcher over websocket-client. One connection per call."""

    def __init__(self, tt_client, token_cache: str | Path | None = None):
        self.tt = tt_client
        self.token_cache = Path(token_cache) if token_cache else None

    # ---- api quote token (24h, cached on disk) -----------------------------

    def _quote_token(self) -> tuple[str, str]:
        if self.token_cache and self.token_cache.exists():
            js = json.loads(self.token_cache.read_text())
            if time.time() < js.get("expires_at", 0):
                return js["token"], js["url"]
        d = self.tt.request("GET", "/api-quote-tokens")
        token, url = d["token"], d["dxlink-url"]
        if self.token_cache:
            self.token_cache.parent.mkdir(parents=True, exist_ok=True)
            self.token_cache.write_text(json.dumps(
                {"token": token, "url": url,
                 "expires_at": time.time() + 23 * 3600}))
        return token, url

    # ---- websocket session -------------------------------------------------

    def _connect(self):
        import websocket
        token, url = self._quote_token()
        ws = websocket.create_connection(url, timeout=10)
        ws.send(json.dumps({"type": "SETUP", "channel": 0,
                            "version": "0.1-svyable/0.1",
                            "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60}))
        authorized = False
        t0 = time.time()
        while time.time() - t0 < 15:
            msg = json.loads(ws.recv())
            if msg.get("type") == "AUTH_STATE":
                if msg.get("state") == "UNAUTHORIZED":
                    ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": token}))
                elif msg.get("state") == "AUTHORIZED":
                    authorized = True
                    break
        if not authorized:
            ws.close()
            raise RuntimeError("DXLink authorization failed")

        ws.send(json.dumps({"type": "CHANNEL_REQUEST", "channel": 3,
                            "service": "FEED", "parameters": {"contract": "AUTO"}}))
        ws.send(json.dumps({"type": "FEED_SETUP", "channel": 3,
                            "acceptAggregationPeriod": 1,
                            "acceptDataFormat": "COMPACT",
                            "acceptEventFields": {"Candle": CANDLE_FIELDS}}))
        return ws

    def fetch_daily(self, symbols: list[str], start: str, *,
                    chunk_size: int = 15, idle_s: float = 3.0,
                    hard_s: float = 120.0) -> dict[str, pd.DataFrame]:
        """Daily OHLCV per symbol from `start` (YYYY-MM-DD) to now."""
        from_ms = int(pd.Timestamp(start).timestamp() * 1000)
        ws = self._connect()
        ws.settimeout(idle_s)
        out: dict[str, list[dict]] = {s: [] for s in symbols}
        last_keepalive = time.time()

        try:
            for i in range(0, len(symbols), chunk_size):
                chunk = symbols[i:i + chunk_size]
                subs = [{"type": "Candle", "symbol": f"{s}{{=1d}}",
                         "fromTime": from_ms} for s in chunk]
                ws.send(json.dumps({"type": "FEED_SUBSCRIPTION", "channel": 3,
                                    "reset": True, "add": subs}))
                t0 = time.time()
                got_any = False
                while time.time() - t0 < hard_s:
                    if time.time() - last_keepalive > 25:
                        ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
                        last_keepalive = time.time()
                    try:
                        msg = json.loads(ws.recv())
                    except Exception:      # noqa: BLE001 — idle timeout = chunk done
                        if got_any:
                            break
                        continue
                    if msg.get("type") != "FEED_DATA":
                        continue
                    got_any = True
                    for ev in parse_feed_data(msg):
                        sym = str(ev.get("eventSymbol", "")).split("{")[0]
                        if sym in out:
                            out[sym].append(ev)
        finally:
            ws.close()

        frames: dict[str, pd.DataFrame] = {}
        for sym, evs in out.items():
            if not evs:
                continue
            df = pd.DataFrame(evs)
            df["date"] = pd.to_datetime(df["time"].map(_f), unit="ms").dt.normalize()
            df = df.dropna(subset=["date"]).drop_duplicates("date", keep="last")
            df = df.set_index("date").sort_index()
            frames[sym] = pd.DataFrame({
                "open": df["open"].map(_f), "high": df["high"].map(_f),
                "low": df["low"].map(_f), "close": df["close"].map(_f),
                "volume": df["volume"].map(_f),
            })
        return frames
