"""tastytrade data-plane helper tests — offline, via a fake transport.

Order management moved to the SDK adapter (``svyable.tastytrade_sdk.TastySdkBroker``,
covered by ``test_tastytrade_sdk_preflight.py``); the legacy REST broker adapter
was removed. What remains here are the transport-agnostic data-plane helpers that
still ship: account-streamer notification parsing, DXLink compact candle parsing,
and the active-equities universe filter.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeClient:
    """Minimal fake transport: records requests, returns canned responses.

    ``fetch_active_equities`` accepts anything exposing ``.request`` (or ``.c.request``),
    so the universe filter can be exercised without a broker adapter.
    """

    def __init__(self):
        self.calls: list[tuple] = []

    def request(self, method, path, *, params=None, body=None, _retried=False):
        self.calls.append((method, path, params, body))
        if path.endswith("/instruments/equities/active"):
            return {"items": [
                {"symbol": "AAPL", "listed-market": "XNAS"},
                {"symbol": "NVDA", "listed-market": "XNAS"},
                {"symbol": "IBM", "listed-market": "XNYS"},
                {"symbol": "QQQ", "listed-market": "XNAS", "is-etf": True},
            ]}
        return {}


def test_account_streamer_parsing():
    from svyable.account_streamer import parse_notification
    order = parse_notification('{"type":"Order","data":{"id":1,"status":"Filled"},'
                               '"timestamp":1688595114405}')
    assert order["type"] == "Order" and order["data"]["status"] == "Filled"
    ack = parse_notification('{"status":"ok","action":"connect",'
                             '"web-socket-session-id":"5b6e2799"}')
    assert ack["type"] == "control" and ack["status"] == "ok"


def test_universe_snapshot_filtering():
    from svyable.universe import fetch_active_equities
    eq = fetch_active_equities(FakeClient(), listed_market="XNAS")
    syms = sorted(e["symbol"] for e in eq)
    assert syms == ["AAPL", "NVDA"]                 # NYSE + ETF filtered out


def test_watch_orders_resolves_terminal_statuses_from_sdk(monkeypatch):
    # Regression: watch_orders lazily imports TERMINAL_ORDER_STATUSES, which was
    # moved from svyable.tastytrade to svyable.tastytrade_sdk. Exercise the import
    # path (empty id set skips the wait loop but still runs the default resolve).
    from svyable.account_streamer import AccountStreamer

    class _FakeWS:
        def settimeout(self, *_):
            pass

        def close(self):
            pass

    streamer = AccountStreamer(tt_client=object(), account_numbers=["ACCT"])
    monkeypatch.setattr(streamer, "_connect", lambda: _FakeWS())

    assert streamer.watch_orders([], timeout_s=0.0) == {}


def test_dxlink_compact_parsing():
    from svyable.dxlink import parse_feed_data, CANDLE_FIELDS
    msg = {"type": "FEED_DATA", "channel": 3, "data": [
        "Candle",
        ["Candle", "AAPL{=1d}", 1719878400000, 210.0, 214.0, 208.5, 213.2, 5.1e7,
         "Candle", "AAPL{=1d}", 1719964800000, 213.5, 215.0, 211.0, 214.8, 4.4e7],
    ]}
    evs = parse_feed_data(msg, CANDLE_FIELDS)
    assert len(evs) == 2
    assert evs[0]["eventSymbol"] == "AAPL{=1d}" and evs[0]["close"] == 213.2
    assert evs[1]["open"] == 213.5


if __name__ == "__main__":
    test_account_streamer_parsing()
    test_universe_snapshot_filtering()
    test_dxlink_compact_parsing()
    print("ALL TASTYTRADE DATA-PLANE TESTS PASSED")
