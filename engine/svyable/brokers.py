"""Broker connectors (plan.md §B.3). One protocol; every broker is an adapter.

Ships with:
- LocalPaperBroker — JSON-state paper account, zero network. The CI/testing
  adapter and the default until real keys exist.

Tastytrade is the canonical data + broker provider; its adapter lives in
tastytrade.py / tastytrade_sdk.py.

Safety invariants:
- Tastytrade defaults to the sandbox host; live requires an explicit opt-in
- this module only translates orders; sizing/caps happen in rebalancer.py
"""

from __future__ import annotations

import json
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
    """Offline paper account persisted to JSON. Fills instantly at given prices.

    The production strategy is long-only, so this adapter rejects oversells instead
    of silently creating short paper positions that the real order adapter would
    not intentionally open.
    """

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
        qty = float(qty)
        if qty <= 0:
            return {"status": "rejected", "symbol": symbol, "reason": "non-positive quantity"}
        current = float(self.state["positions"].get(symbol, 0.0))
        if side == "sell" and qty > current + 1e-9:
            return {
                "status": "rejected",
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "reason": "long-only paper broker refuses oversell",
            }
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
