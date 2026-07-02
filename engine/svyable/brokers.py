"""Broker connectors (plan.md §B.3). One protocol; every broker is an adapter.

Ships with:
- LocalPaperBroker — JSON-state paper account, zero network. The CI/testing
  adapter and the default until real keys exist.
- AlpacaBroker — Alpaca Trading API v2 (paper by default). Keys via env
  ALPACA_KEY_ID / ALPACA_SECRET_KEY; never stored in code or config.

Safety invariants:
- default endpoint is the PAPER host; live requires alpaca_live=True explicitly
- this module only translates orders; sizing/caps happen in rebalancer.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol


class BrokerConnector(Protocol):
    def get_account(self) -> dict: ...                      # {"equity": float, "cash": float}
    def get_positions(self) -> dict[str, float]: ...        # symbol -> signed qty
    def submit_order(self, symbol: str, qty: float, side: str,
                     order_type: str = "market", tif: str = "day") -> dict: ...


# ---------------------------------------------------------------------------

class LocalPaperBroker:
    """Offline paper account persisted to JSON. Fills instantly at given prices."""

    def __init__(self, state_file: str | Path, starting_cash: float = 100_000.0):
        self.path = Path(state_file)
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {"cash": starting_cash, "positions": {}, "fills": []}
            self._save()
        self._prices: dict[str, float] = {}

    def set_prices(self, prices: dict[str, float]) -> None:
        self._prices = dict(prices)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2))

    def get_account(self) -> dict:
        pos_val = sum(q * self._prices.get(s, 0.0)
                      for s, q in self.state["positions"].items())
        return {"equity": self.state["cash"] + pos_val, "cash": self.state["cash"]}

    def get_positions(self) -> dict[str, float]:
        return {s: q for s, q in self.state["positions"].items() if abs(q) > 1e-9}

    def submit_order(self, symbol: str, qty: float, side: str,
                     order_type: str = "market", tif: str = "day") -> dict:
        px = self._prices.get(symbol)
        if px is None or px <= 0:
            return {"status": "rejected", "symbol": symbol, "reason": "no price"}
        signed = qty if side == "buy" else -qty
        cost = signed * px
        if side == "buy" and cost > self.state["cash"] + 1e-6:
            return {"status": "rejected", "symbol": symbol, "reason": "insufficient cash"}
        self.state["cash"] -= cost
        self.state["positions"][symbol] = self.state["positions"].get(symbol, 0.0) + signed
        if abs(self.state["positions"][symbol]) < 1e-9:
            del self.state["positions"][symbol]
        fill = {"symbol": symbol, "qty": qty, "side": side, "price": px,
                "ts": datetime.now().isoformat(timespec="seconds")}
        self.state["fills"].append(fill)
        self._save()
        return {"status": "filled", **fill}


# ---------------------------------------------------------------------------

class AlpacaBroker:
    """Alpaca Trading API v2. Paper host unless alpaca_live=True."""

    def __init__(self, alpaca_live: bool = False):
        self.base = ("https://api.alpaca.markets" if alpaca_live
                     else "https://paper-api.alpaca.markets")
        self.key = os.environ.get("ALPACA_KEY_ID", "")
        self.secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not self.key or not self.secret:
            raise RuntimeError("set ALPACA_KEY_ID and ALPACA_SECRET_KEY in the environment")

    def _req(self, method: str, path: str, body: dict | None = None) -> dict | list:
        import requests
        r = requests.request(
            method, f"{self.base}{path}",
            headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret},
            json=body, timeout=15,
        )
        r.raise_for_status()
        return r.json() if r.text else {}

    def get_account(self) -> dict:
        a = self._req("GET", "/v2/account")
        return {"equity": float(a["equity"]), "cash": float(a["cash"])}

    def get_positions(self) -> dict[str, float]:
        return {p["symbol"]: float(p["qty"]) for p in self._req("GET", "/v2/positions")}

    def submit_order(self, symbol: str, qty: float, side: str,
                     order_type: str = "market", tif: str = "day") -> dict:
        o = self._req("POST", "/v2/orders", {
            "symbol": symbol, "qty": str(qty), "side": side,
            "type": order_type, "time_in_force": tif,
        })
        return {"status": o.get("status", "submitted"), "id": o.get("id"),
                "symbol": symbol, "qty": qty, "side": side}
