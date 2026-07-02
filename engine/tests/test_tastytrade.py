"""tastytrade adapter tests — offline, via a fake client transport.

Verifies the wire format (dasherized keys, legs, actions, price-effect),
the dry-run gate, position sign handling, and order lifecycle paths.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.tastytrade import TastytradeBroker, TastytradeClient


class FakeClient:
    """Records requests; returns canned tastytrade-shaped responses."""
    env, auth_mode = "sandbox", "session"

    def __init__(self, dry_run_warnings=None):
        self.calls: list[tuple] = []
        self.dry_run_warnings = dry_run_warnings or []

    def request(self, method, path, *, params=None, body=None, _retried=False):
        self.calls.append((method, path, params, body))
        if path.endswith("/customers/me/accounts"):
            return {"items": [{"account": {"account-number": "5WT00001"}}]}
        if path.endswith("/balances"):
            return {"net-liquidating-value": "100000.0", "cash-balance": "40000.0",
                    "equity-buying-power": "200000.0"}
        if path.endswith("/positions"):
            return {"items": [
                {"instrument-type": "Equity", "symbol": "MRVL",
                 "quantity": "22", "quantity-direction": "Long",
                 "average-open-price": "90.0", "multiplier": 1,
                 "average-daily-market-close-price": "98.0",
                 "close-price": "98.0", "realized-day-gain": "0.0",
                 "realized-day-gain-date": "2020-01-01"},
                {"instrument-type": "Equity", "symbol": "XYZ",
                 "quantity": "5", "quantity-direction": "Short"},
                {"instrument-type": "Equity Option", "symbol": "SPY 25...",
                 "quantity": "1", "quantity-direction": "Long"},
            ]}
        if path.endswith("/orders/dry-run"):
            return {"warnings": self.dry_run_warnings,
                    "buying-power-effect": {"impact": "5985.0",
                                            "new-buying-power": "194015.0"},
                    "fee-calculation": {"total-fees": "0.08"}}
        if method == "POST" and path.endswith("/orders"):
            return {"order": {"id": 771043, "status": "Routed"}}
        if method == "GET" and "/orders/" in path:
            return {"id": 771043, "status": "Filled"}
        if method == "GET" and path.endswith("/orders"):
            return {"items": [{"id": 771043, "status": "Filled",
                               "underlying-symbol": "MRVL",
                               "order-type": "Market", "size": 22}]}
        if method == "DELETE":
            return {"status": "Cancel Requested"}
        if path.endswith("/market-data/by-type"):
            syms = params["equity"].split(",")        # comma-delimited per docs
            return {"items": [{"symbol": s, "bid": "99.9", "ask": "100.1",
                               "mid": "100.0", "mark": "100.0",
                               "last": "100.0", "close": "99.5",
                               "prev-close": "98.0", "beta": "1.2",
                               "is-trading-halted": s == "HALT"}
                              for s in syms]}
        if path.endswith("/instruments/equities/active"):
            return {"items": [
                {"symbol": "AAPL", "listed-market": "XNAS"},
                {"symbol": "NVDA", "listed-market": "XNAS"},
                {"symbol": "IBM", "listed-market": "XNYS"},
                {"symbol": "QQQ", "listed-market": "XNAS", "is-etf": True},
            ]}
        return {}


def _broker(**kw) -> TastytradeBroker:
    return TastytradeBroker(client=FakeClient(**kw))


def test_order_wire_format():
    o = TastytradeBroker.build_equity_order("MRVL", 22, "buy")
    assert o == {"time-in-force": "Day", "order-type": "Market",
                 "legs": [{"instrument-type": "Equity", "symbol": "MRVL",
                           "quantity": 22, "action": "Buy to Open"}]}
    lo = TastytradeBroker.build_equity_order("MRVL", 22, "sell",
                                             order_type="limit", price=271.559)
    assert lo["price"] == 271.56 and lo["price-effect"] == "Credit"
    assert lo["legs"][0]["action"] == "Sell to Close"


def test_positions_signs_and_equity_filter():
    b = _broker()
    pos = b.get_positions()
    assert pos == {"MRVL": 22.0, "XYZ": -5.0}       # option position excluded
    acct = b.get_account()
    assert acct["equity"] == 100000.0 and acct["cash"] == 40000.0


def test_submit_is_dry_run_gated():
    b = _broker()
    r = b.submit_order("MRVL", 22, "buy")
    assert r["status"] == "Routed" and r["id"] == 771043
    paths = [p for _, p, _, _ in b.c.calls]
    i_dry = next(i for i, p in enumerate(paths) if p.endswith("/orders/dry-run"))
    i_sub = next(i for i, p in enumerate(paths)
                 if p.endswith("/orders") and b.c.calls[i][0] == "POST"
                 and not p.endswith("dry-run"))
    assert i_dry < i_sub                              # dry-run strictly first

    warned = _broker(dry_run_warnings=[{"code": "margin", "message": "nope"}])
    r2 = warned.submit_order("MRVL", 22, "buy")
    assert r2["status"] == "rejected_dry_run"
    assert not any(m == "POST" and p.endswith("/orders") and "dry-run" not in p
                   for m, p, _, _ in warned.c.calls)  # nothing submitted


def test_lifecycle_calls():
    b = _broker()
    assert b.poll_order(771043, timeout_s=1, interval_s=0)["status"] == "Filled"
    assert b.cancel_order(771043)["status"] == "Cancel Requested"
    orders = b.search_orders(start_date="2026-07-01", status=["Filled"])
    assert orders[0]["id"] == 771043
    # array param format: status[]=...
    _, _, params, _ = b.c.calls[-1]
    assert params["status[]"] == ["Filled"]
    snap = b.status_snapshot()
    assert snap["account"] == "5WT00001" and snap["orders_today"][0]["id"] == 771043


def test_production_guard():
    import os
    os.environ.setdefault("TT_USERNAME", "x")
    os.environ.setdefault("TT_PASSWORD", "y")
    try:
        TastytradeClient(env="production", allow_production=False)
        raise AssertionError("production guard failed")
    except RuntimeError as e:
        assert "allow_production" in str(e)


def test_market_snapshot_and_execution_prices():
    b = _broker()
    snap = b.get_market_snapshot(["MRVL", "AMD"])
    assert snap["MRVL"]["mark"] == 100.0 and snap["AMD"]["beta"] == 1.2
    px = b.execution_prices(["MRVL", "HALT"])
    assert px["MRVL"] == 100.0                      # mark preferred
    assert "HALT" not in px                          # halted names never priced


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
    eq = fetch_active_equities(_broker(), listed_market="XNAS")
    syms = sorted(e["symbol"] for e in eq)
    assert syms == ["AAPL", "NVDA"]                 # NYSE + ETF filtered out


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


def test_pnl_report_formulas():
    b = _broker()
    rep = b.pnl_report()
    mrvl = next(p for p in rep["positions"] if p["symbol"] == "MRVL")
    # mark = mid 100.0; unrealized = (100-90)*22 = 220; day = (100-98)*22 = 44
    assert mrvl["unrealized"] == 220.0 and mrvl["pl_day"] == 44.0
    assert mrvl["value"] == 2200.0
    # net liq = MRVL value (2200) + short XYZ value (-500, direction -1 per docs)
    # + cash (40k) + pending (0)
    xyz = next(p for p in rep["positions"] if p["symbol"] == "XYZ")
    assert xyz["value"] == -500.0
    assert abs(rep["net_liq"] - (2200.0 - 500.0 + 40000.0)) < 1e-6


def test_terminal_statuses():
    from svyable.tastytrade import TERMINAL_ORDER_STATUSES
    assert "Partially Removed" in TERMINAL_ORDER_STATUSES
    assert "Cancel Requested" not in TERMINAL_ORDER_STATUSES
    assert "Live" not in TERMINAL_ORDER_STATUSES


if __name__ == "__main__":
    test_order_wire_format()
    test_positions_signs_and_equity_filter()
    test_submit_is_dry_run_gated()
    test_lifecycle_calls()
    test_production_guard()
    test_market_snapshot_and_execution_prices()
    test_account_streamer_parsing()
    test_universe_snapshot_filtering()
    test_dxlink_compact_parsing()
    test_pnl_report_formulas()
    test_terminal_statuses()
    print("ALL TASTYTRADE TESTS PASSED")
