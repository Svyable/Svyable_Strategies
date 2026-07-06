"""DXLink websocket client for tastytrade market data.

Two consumers share one spec-compliant protocol core:

* ``DXLinkCandles`` — blocking historical daily-candle backfill (one connection
  per call).
* ``DXLinkFeed`` — a persistent live streamer (Quote/Trade/Summary/Greeks) with
  auto-reconnect, used for real-time portfolio monitoring.

Protocol order (dxLink WebSocket 1.0.2): SETUP -> read server SETUP (negotiate
keepalive) -> AUTH(api-quote-token) -> wait AUTH_STATE:AUTHORIZED ->
CHANNEL_REQUEST(FEED) -> wait CHANNEL_OPENED -> FEED_SETUP(COMPACT) ->
FEED_SUBSCRIPTION -> FEED_CONFIG (server-authoritative field order) ->
FEED_DATA. The client beats KEEPALIVE on channel 0 at half the server's
negotiated ``keepaliveTimeout``. ERROR frames are surfaced as ``DxLinkError``
(notably UNAUTHORIZED when a 24h quote token has expired).

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
from pathlib import Path

import numpy as np
import pandas as pd

# Compact event field sets. "eventType"/"eventSymbol" first so a bare COMPACT
# row self-identifies. The server confirms the *actual* order in FEED_CONFIG;
# parsing always defers to that when present.
CANDLE_FIELDS = ["eventType", "eventSymbol", "time", "open", "high", "low",
                 "close", "volume"]
QUOTE_FIELDS = ["eventType", "eventSymbol", "bidPrice", "askPrice",
                "bidSize", "askSize"]
TRADE_FIELDS = ["eventType", "eventSymbol", "price", "size", "dayVolume"]
SUMMARY_FIELDS = ["eventType", "eventSymbol", "prevDayClosePrice",
                  "dayOpenPrice", "openInterest"]
GREEKS_FIELDS = ["eventType", "eventSymbol", "price", "volatility", "delta",
                 "gamma", "theta", "vega", "rho"]

_FIELD_SETS = {"Candle": CANDLE_FIELDS, "Quote": QUOTE_FIELDS,
               "Trade": TRADE_FIELDS, "Summary": SUMMARY_FIELDS,
               "Greeks": GREEKS_FIELDS}

DEFAULT_VERSION = "0.1-svyable/0.1"


# ---------------------------------------------------------------------------
# Protocol core (spec 1.0.2) — pure, socket-agnostic helpers.
# ---------------------------------------------------------------------------

class DxLinkError(RuntimeError):
    """A server ERROR frame (UNAUTHORIZED, TIMEOUT, BAD_ACTION, ...)."""

    def __init__(self, error: str, message: str = ""):
        self.error = error
        self.message = message
        super().__init__(f"{error}: {message}" if message else error)


def raise_for_error(msg: dict) -> None:
    """Raise ``DxLinkError`` if ``msg`` is an ERROR frame; else no-op."""
    if msg.get("type") == "ERROR":
        raise DxLinkError(msg.get("error", "UNKNOWN"), msg.get("message", ""))


def keepalive_interval(server_keepalive: float | None, *, floor: float = 5.0,
                       default: float = 30.0) -> float:
    """Client keepalive cadence: half the server's negotiated timeout, so a
    single missed beat never trips the server. Falls back to ``default`` when
    the server did not advertise one, clamped to ``floor``."""
    if not server_keepalive:
        return default
    return max(floor, float(server_keepalive) / 2.0)


def default_fields_for(subscriptions: list[dict]) -> dict[str, list[str]]:
    """Map the event types present in ``subscriptions`` to their field sets."""
    types = {s.get("type") for s in subscriptions}
    return {t: _FIELD_SETS[t] for t in types if t in _FIELD_SETS}


def parse_feed_data(msg: dict, fields) -> list[dict]:
    """Parse a COMPACT FEED_DATA message into event dicts.

    COMPACT payload: ``[type, [v1..vN, v1..vN, ...], type2, [...], ...]`` where
    each consecutive group of ``len(fields[type])`` values is one event.

    ``fields`` may be a flat ``list[str]`` (applied to every group — the legacy
    single-event-type form) or a ``dict[type -> list[str]]`` sourced from
    FEED_CONFIG, which is authoritative over the requested order.
    """
    if isinstance(fields, dict):
        fields_by_type: dict[str, list[str]] = fields
        fallback: list[str] | None = None
    else:
        fields_by_type = {}
        fallback = list(fields)

    out: list[dict] = []
    data = msg.get("data") or []
    for i in range(0, len(data) - 1, 2):
        etype, values = data[i], data[i + 1]
        if not isinstance(values, list):
            continue
        f = fields_by_type.get(etype, fallback)
        if not f:
            continue
        n = len(f)
        for j in range(0, len(values) - n + 1, n):
            ev = dict(zip(f, values[j:j + n]))
            if ev.get("eventType") in ("", None):
                ev["eventType"] = etype
            out.append(ev)
    return out


def _recv_json(ws) -> dict:
    return json.loads(ws.recv())


def handshake(ws, token: str, version: str = DEFAULT_VERSION, *,
              timeout_s: float = 15.0) -> float | None:
    """SETUP -> AUTH -> AUTHORIZED. Returns the server's negotiated
    ``keepaliveTimeout`` (or None). Raises ``DxLinkError`` on an ERROR frame and
    ``RuntimeError`` if authorization is not reached within ``timeout_s``."""
    ws.send(json.dumps({"type": "SETUP", "channel": 0, "version": version,
                        "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60}))
    server_keepalive: float | None = None
    auth_sent = False
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        msg = _recv_json(ws)
        raise_for_error(msg)
        mtype = msg.get("type")
        if mtype == "SETUP":
            server_keepalive = msg.get("keepaliveTimeout", server_keepalive)
        elif mtype == "AUTH_STATE":
            state = msg.get("state")
            if state == "AUTHORIZED":
                return server_keepalive
            if state == "UNAUTHORIZED" and not auth_sent:
                ws.send(json.dumps({"type": "AUTH", "channel": 0,
                                    "token": token}))
                auth_sent = True
    raise RuntimeError("DXLink authorization failed")


def open_feed_channel(ws, channel: int, fields_by_type: dict[str, list[str]], *,
                      aggregation_period: float | None = None,
                      timeout_s: float = 10.0) -> None:
    """CHANNEL_REQUEST(FEED) -> wait CHANNEL_OPENED -> FEED_SETUP(COMPACT).

    Waiting for CHANNEL_OPENED before configuring the channel avoids the
    BAD_ACTION the spec warns about when a channel is used before it opens.
    """
    ws.send(json.dumps({"type": "CHANNEL_REQUEST", "channel": channel,
                        "service": "FEED", "parameters": {"contract": "AUTO"}}))
    t0 = time.time()
    opened = False
    while time.time() - t0 < timeout_s:
        msg = _recv_json(ws)
        raise_for_error(msg)
        if msg.get("type") == "CHANNEL_OPENED" and msg.get("channel") == channel:
            opened = True
            break
    if not opened:
        raise RuntimeError(f"DXLink channel {channel} did not open")

    setup = {"type": "FEED_SETUP", "channel": channel,
             "acceptDataFormat": "COMPACT",
             "acceptEventFields": fields_by_type}
    if aggregation_period is not None:
        setup["acceptAggregationPeriod"] = aggregation_period
    ws.send(json.dumps(setup))


def fetch_quote_token(tt_client, token_cache: str | Path | None) -> tuple[str, str]:
    """Api quote token (24h) + dxlink url, cached on disk when a path is given."""
    cache = Path(token_cache) if token_cache else None
    if cache and cache.exists():
        js = json.loads(cache.read_text())
        if time.time() < js.get("expires_at", 0):
            return js["token"], js["url"]
    d = tt_client.request("GET", "/api-quote-tokens")
    token, url = d["token"], d["dxlink-url"]
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(
            {"token": token, "url": url, "expires_at": time.time() + 23 * 3600}))
    return token, url


def _f(x) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


# ---------------------------------------------------------------------------
# Historical candle backfill.
# ---------------------------------------------------------------------------

class DXLinkCandles:
    """Blocking candle fetcher over websocket-client. One connection per call."""

    def __init__(self, tt_client, token_cache: str | Path | None = None):
        self.tt = tt_client
        self.token_cache = Path(token_cache) if token_cache else None
        self._keepalive = 30.0

    def _quote_token(self) -> tuple[str, str]:
        return fetch_quote_token(self.tt, self.token_cache)

    def _connect(self):
        import websocket
        token, url = self._quote_token()
        ws = websocket.create_connection(url, timeout=10)
        server_keepalive = handshake(ws, token, DEFAULT_VERSION)
        self._keepalive = keepalive_interval(server_keepalive)
        open_feed_channel(ws, 3, {"Candle": CANDLE_FIELDS},
                          aggregation_period=1)
        return ws

    def fetch_daily(self, symbols: list[str], start: str, *,
                    chunk_size: int = 15, idle_s: float = 3.0,
                    hard_s: float = 120.0) -> dict[str, pd.DataFrame]:
        """Daily OHLCV per symbol from `start` (YYYY-MM-DD) to now."""
        from_ms = int(pd.Timestamp(start).timestamp() * 1000)
        ws = self._connect()
        ws.settimeout(idle_s)
        out: dict[str, list[dict]] = {s: [] for s in symbols}
        fields: dict[str, list[str]] = {"Candle": CANDLE_FIELDS}
        last_keepalive = time.time()
        beat_every = max(1.0, self._keepalive)

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
                    if time.time() - last_keepalive > beat_every:
                        ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
                        last_keepalive = time.time()
                    try:
                        msg = json.loads(ws.recv())
                    except Exception:      # noqa: BLE001 — idle timeout = chunk done
                        if got_any:
                            break
                        continue
                    raise_for_error(msg)
                    mtype = msg.get("type")
                    if mtype == "FEED_CONFIG":
                        ef = msg.get("eventFields")
                        if ef:
                            fields = ef
                        continue
                    if mtype != "FEED_DATA":
                        continue
                    got_any = True
                    for ev in parse_feed_data(msg, fields):
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


# ---------------------------------------------------------------------------
# Live streaming feed (real-time portfolio monitoring).
# ---------------------------------------------------------------------------

class DXLinkFeed:
    """Persistent live market-data streamer over a single dxLink connection.

    ``stream`` subscribes the requested symbols/event-types and invokes
    ``on_event(event_dict)`` for every event until ``run_s`` elapses. On a
    dropped connection or ERROR it reconnects with exponential backoff and
    resubscribes; an UNAUTHORIZED error invalidates the cached quote token so
    the next connect re-mints one.

    ``ws_factory`` is an injection seam for tests: a zero-arg callable returning
    ``(ws, token)``. In production it is None and the feed mints a quote token
    and opens a real websocket to the dxlink url.
    """

    def __init__(self, tt_client, token_cache: str | Path | None = None, *,
                 version: str = DEFAULT_VERSION, channel: int = 1,
                 ws_factory=None):
        self.tt = tt_client
        self.token_cache = Path(token_cache) if token_cache else None
        self.version = version
        self.channel = channel
        self._ws_factory = ws_factory
        self._keepalive = 30.0

    def _open(self):
        if self._ws_factory is not None:
            ws, token = self._ws_factory()
        else:
            import websocket
            token, url = fetch_quote_token(self.tt, self.token_cache)
            ws = websocket.create_connection(url, timeout=10)
        self._keepalive = keepalive_interval(handshake(ws, token, self.version))
        return ws

    def _invalidate_token(self) -> None:
        if self.token_cache and self.token_cache.exists():
            try:
                self.token_cache.unlink()
            except OSError:
                pass

    def stream(self, subscriptions: list[dict], on_event, *, run_s: float = 3600.0,
               fields: dict[str, list[str]] | None = None,
               aggregation_period: float | None = None,
               reconnect: bool = True, max_backoff: float = 30.0) -> None:
        fields = fields or default_fields_for(subscriptions)
        deadline = time.time() + run_s
        backoff = 0.5
        while time.time() < deadline:
            try:
                self._run_once(subscriptions, on_event, deadline, fields,
                               aggregation_period)
            except DxLinkError as exc:
                if exc.error == "UNAUTHORIZED":
                    self._invalidate_token()
                if not reconnect:
                    raise
            except Exception:  # noqa: BLE001 — socket drop / transient failure
                if not reconnect:
                    raise
            if not reconnect:
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            time.sleep(min(backoff, max_backoff, remaining))
            backoff = min(backoff * 2, max_backoff)

    def _run_once(self, subscriptions, on_event, deadline, fields,
                  aggregation_period) -> None:
        ws = self._open()
        active = dict(fields)
        try:
            # Channel open uses the connect-time (longer) socket timeout so a
            # slow CHANNEL_OPENED/FEED_CONFIG doesn't look like a drop; the tight
            # idle timeout only governs the steady-state streaming loop below.
            open_feed_channel(ws, self.channel, fields,
                              aggregation_period=aggregation_period)
            ws.send(json.dumps({"type": "FEED_SUBSCRIPTION",
                                "channel": self.channel, "reset": True,
                                "add": subscriptions}))
            ws.settimeout(1.0)
            last_beat = time.time()
            beat_every = max(1.0, self._keepalive)
            while time.time() < deadline:
                if time.time() - last_beat > beat_every:
                    ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
                    last_beat = time.time()
                try:
                    msg = _recv_json(ws)
                except Exception:  # noqa: BLE001 — idle read, keep beating
                    continue
                raise_for_error(msg)
                mtype = msg.get("type")
                if mtype == "FEED_CONFIG":
                    ef = msg.get("eventFields")
                    if ef:
                        active = ef
                elif mtype == "FEED_DATA":
                    for ev in parse_feed_data(msg, active):
                        on_event(ev)
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
