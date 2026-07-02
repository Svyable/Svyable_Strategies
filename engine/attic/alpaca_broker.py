"""RETIRED: Alpaca adapter, moved out of the active surface (tastytrade is
primary). Kept for reference; restore by moving back into svyable/ and
re-adding the CLI branch."""

import os


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
