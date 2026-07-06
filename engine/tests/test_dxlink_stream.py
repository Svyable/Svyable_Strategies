"""DXLink protocol + streaming tests — offline, via a fake websocket.

Covers the 1.0.2-compliance hardening (ERROR handling, server-negotiated
keepalive, CHANNEL_OPENED gating, FEED_CONFIG-driven parsing) and the
persistent ``DXLinkFeed`` streamer's message routing / resubscribe logic.
No network: a ``FakeWS`` replays a scripted server transcript.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeWS:
    """Scripted server: ``inbound`` is a queue of dicts to hand back on recv().

    A ``None`` entry simulates an idle read (recv raises, like a socket
    timeout). Everything the client sends is recorded in ``sent``.
    """

    class Timeout(Exception):
        pass

    def __init__(self, inbound):
        self.inbound = list(inbound)
        self.sent: list[dict] = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        if not self.inbound:
            raise FakeWS.Timeout("idle")
        item = self.inbound.pop(0)
        if item is None:
            raise FakeWS.Timeout("idle")
        return json.dumps(item)

    def settimeout(self, *_):
        pass

    def close(self):
        self.closed = True

    def sent_types(self):
        return [m.get("type") for m in self.sent]


# ---- pure protocol helpers -------------------------------------------------


def test_raise_for_error_surfaces_typed_error():
    from svyable.dxlink import DxLinkError, raise_for_error

    raise_for_error({"type": "FEED_DATA"})  # non-error is a no-op
    with pytest.raises(DxLinkError) as ei:
        raise_for_error({"type": "ERROR", "error": "UNAUTHORIZED",
                         "message": "token expired"})
    assert ei.value.error == "UNAUTHORIZED"
    assert "token expired" in str(ei.value)


def test_keepalive_interval_halves_server_timeout():
    from svyable.dxlink import keepalive_interval

    assert keepalive_interval(60) == 30.0          # beat at half
    assert keepalive_interval(None) == 30.0         # default when unknown
    assert keepalive_interval(4) == 5.0             # clamped to floor


def test_parse_feed_data_uses_per_type_fields_from_config():
    from svyable.dxlink import parse_feed_data

    fields = {
        "Quote": ["eventType", "eventSymbol", "bidPrice", "askPrice"],
        "Trade": ["eventType", "eventSymbol", "price", "size"],
    }
    msg = {"type": "FEED_DATA", "channel": 1, "data": [
        "Quote", ["Quote", "AAPL", 210.1, 210.2, "Quote", "MSFT", 400.0, 400.1],
        "Trade", ["Trade", "AAPL", 210.15, 100],
    ]}
    evs = parse_feed_data(msg, fields)
    assert len(evs) == 3
    assert evs[0] == {"eventType": "Quote", "eventSymbol": "AAPL",
                      "bidPrice": 210.1, "askPrice": 210.2}
    assert evs[1]["eventSymbol"] == "MSFT"
    assert evs[2] == {"eventType": "Trade", "eventSymbol": "AAPL",
                      "price": 210.15, "size": 100}


def test_parse_feed_data_list_form_is_backward_compatible():
    from svyable.dxlink import parse_feed_data, CANDLE_FIELDS

    msg = {"type": "FEED_DATA", "data": [
        "Candle",
        ["Candle", "AAPL{=1d}", 1719878400000, 210.0, 214.0, 208.5, 213.2, 5.1e7],
    ]}
    evs = parse_feed_data(msg, CANDLE_FIELDS)
    assert len(evs) == 1 and evs[0]["close"] == 213.2


def test_handshake_authorizes_and_returns_server_keepalive():
    from svyable.dxlink import handshake

    ws = FakeWS([
        {"type": "SETUP", "channel": 0, "keepaliveTimeout": 30},
        {"type": "AUTH_STATE", "channel": 0, "state": "UNAUTHORIZED"},
        {"type": "AUTH_STATE", "channel": 0, "state": "AUTHORIZED"},
    ])
    ka = handshake(ws, token="tok#1", version="0.1-svyable/0.1")
    assert ka == 30
    assert ws.sent_types()[0] == "SETUP"
    assert {"type": "AUTH", "channel": 0, "token": "tok#1"} in ws.sent


def test_handshake_raises_on_error_message():
    from svyable.dxlink import DxLinkError, handshake

    ws = FakeWS([{"type": "ERROR", "error": "UNSUPPORTED_PROTOCOL",
                  "message": "nope"}])
    with pytest.raises(DxLinkError):
        handshake(ws, token="t", version="v")


def test_open_feed_channel_waits_for_channel_opened():
    from svyable.dxlink import open_feed_channel, QUOTE_FIELDS

    ws = FakeWS([{"type": "CHANNEL_OPENED", "channel": 1, "service": "FEED"}])
    open_feed_channel(ws, 1, {"Quote": QUOTE_FIELDS})
    types = ws.sent_types()
    # CHANNEL_REQUEST must precede FEED_SETUP, and both must be sent.
    assert types == ["CHANNEL_REQUEST", "FEED_SETUP"]


# ---- streamer --------------------------------------------------------------


def _feed_transcript():
    """A full happy-path server transcript for one FEED session."""
    return [
        {"type": "SETUP", "channel": 0, "keepaliveTimeout": 60},
        {"type": "AUTH_STATE", "channel": 0, "state": "UNAUTHORIZED"},
        {"type": "AUTH_STATE", "channel": 0, "state": "AUTHORIZED"},
        {"type": "CHANNEL_OPENED", "channel": 1, "service": "FEED"},
        # Server reorders fields relative to what we requested — parser must obey.
        {"type": "FEED_CONFIG", "channel": 1, "dataFormat": "COMPACT",
         "eventFields": {"Quote": ["eventSymbol", "eventType", "bidPrice",
                                    "askPrice", "bidSize", "askSize"]}},
        {"type": "FEED_DATA", "channel": 1, "data": [
            "Quote", ["AAPL", "Quote", 210.1, 210.2, 100, 200]]},
        None,  # idle -> loop ends at deadline
    ]


def test_stream_routes_events_and_respects_feed_config_order():
    from svyable.dxlink import DXLinkFeed

    ws = FakeWS(_feed_transcript())
    feed = DXLinkFeed(tt_client=object(),
                      ws_factory=lambda: (ws, "tok#1"))
    events: list[dict] = []
    feed.stream([{"type": "Quote", "symbol": "AAPL"}],
                events.append, run_s=0.2, reconnect=False)

    assert len(events) == 1
    ev = events[0]
    # eventSymbol/eventType came from the *config* order, not the request order.
    assert ev["eventSymbol"] == "AAPL" and ev["eventType"] == "Quote"
    assert ev["bidPrice"] == 210.1 and ev["askSize"] == 200
    # Subscription was sent on the opened channel with reset+add.
    sub = next(m for m in ws.sent if m.get("type") == "FEED_SUBSCRIPTION")
    assert sub["channel"] == 1 and sub["reset"] is True
    assert sub["add"] == [{"type": "Quote", "symbol": "AAPL"}]
    assert ws.closed


def test_stream_reconnects_and_refreshes_token_on_unauthorized():
    from svyable.dxlink import DXLinkFeed

    # First session dies mid-stream with UNAUTHORIZED; second succeeds.
    session_a = [
        {"type": "SETUP", "channel": 0, "keepaliveTimeout": 60},
        {"type": "AUTH_STATE", "channel": 0, "state": "AUTHORIZED"},
        {"type": "CHANNEL_OPENED", "channel": 1, "service": "FEED"},
        {"type": "ERROR", "error": "UNAUTHORIZED", "message": "expired"},
    ]
    session_b = _feed_transcript()
    calls = {"n": 0}
    tokens: list[str] = []

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeWS(session_a), "stale-token"
        tokens.append("fresh-token")
        return FakeWS(session_b), "fresh-token"

    invalidations = {"n": 0}
    feed = DXLinkFeed(tt_client=object(), ws_factory=factory)
    feed._invalidate_token = lambda: invalidations.__setitem__("n", invalidations["n"] + 1)

    events: list[dict] = []
    feed.stream([{"type": "Quote", "symbol": "AAPL"}],
                events.append, run_s=1.0, reconnect=True, max_backoff=0.01)

    assert calls["n"] == 2                     # reconnected once
    assert invalidations["n"] == 1             # token invalidated on UNAUTHORIZED
    assert len(events) == 1                     # second session delivered data


def test_default_fields_cover_requested_types():
    from svyable.dxlink import default_fields_for

    fields = default_fields_for([
        {"type": "Quote", "symbol": "AAPL"},
        {"type": "Greeks", "symbol": ".AAPL240119C200"},
    ])
    assert set(fields) == {"Quote", "Greeks"}
    assert "delta" in fields["Greeks"]


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            # crude runner for the pytest.raises-free subset when run directly
            fn() if fn.__code__.co_argcount == 0 else None
        except Exception:  # noqa: BLE001
            failed += 1
            traceback.print_exc()
    print("DXLINK STREAM TESTS:", "FAIL" if failed else "OK")
