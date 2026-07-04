"""Live Tastytrade quote-board helpers for humans and agents.

Q23 was mostly offline research. Svyable now has broker connectivity, so the GUI
should continuously answer the practical PM questions: what are my live marks,
what names are missing quotes, where are spreads wide, and which target/actual
names would be expensive to trade right now.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from svyable.dashboard_service import DashboardService
from svyable.dashboard_ui import money, percent


def _positions_series(positions: pd.DataFrame) -> pd.Series:
    if positions is None or positions.empty or "symbol" not in positions.columns:
        return pd.Series(dtype=float)
    frame = positions.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    qty = pd.to_numeric(frame.get("quantity", 0.0), errors="coerce").fillna(0.0)
    return qty.groupby(frame["symbol"]).sum()


def _position_mark_series(positions: pd.DataFrame) -> pd.Series:
    if positions is None or positions.empty or "symbol" not in positions.columns or "mark" not in positions.columns:
        return pd.Series(dtype=float)
    frame = positions.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    mark = pd.to_numeric(frame["mark"], errors="coerce")
    return mark.groupby(frame["symbol"]).last()


def _quote_price(row: pd.Series) -> float | None:
    for key in ("mark", "mid", "last", "close", "prev_close"):
        value = row.get(key)
        if pd.notna(value) and float(value) > 0:
            return float(value)
    return None


def _market_table(
    service: DashboardService,
    snapshot: dict[str, Any] | None,
    *,
    max_symbols: int,
) -> pd.DataFrame:
    try:
        targets = service.target_series().astype(float)
        targets.index = targets.index.astype(str).str.upper()
    except Exception:
        targets = pd.Series(dtype=float)

    positions = pd.DataFrame() if snapshot is None else snapshot.get("positions", pd.DataFrame())
    pos_qty = _positions_series(positions)
    pos_mark = _position_mark_series(positions)
    equity = None
    if snapshot is not None:
        account = snapshot.get("account", {})
        try:
            equity = float(account.get("equity"))
        except (TypeError, ValueError):
            equity = None

    target_rank = targets.abs().sort_values(ascending=False)
    symbols = list(target_rank.head(max_symbols).index)
    for symbol in pos_qty.abs().sort_values(ascending=False).index:
        if symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= max_symbols:
            break
    symbols = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    if not symbols:
        return pd.DataFrame()

    quotes = service.broker.get_market_snapshot(symbols)
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        quote = quotes.get(symbol, {})
        row = {"symbol": symbol, **quote}
        row_series = pd.Series(row)
        price = _quote_price(row_series)
        bid = row.get("bid")
        ask = row.get("ask")
        prev_close = row.get("prev_close") or row.get("close")
        spread = float(ask) - float(bid) if bid is not None and ask is not None else None
        spread_bps = (spread / price * 10_000.0) if spread is not None and price else None
        change_pct = ((price / float(prev_close)) - 1.0) if price and prev_close else None
        qty = float(pos_qty.get(symbol, 0.0))
        mark = price or float(pos_mark.get(symbol, 0.0) or 0.0)
        target_w = float(targets.get(symbol, 0.0))
        target_notional = target_w * equity if equity is not None else None
        current_notional = qty * mark if mark else None
        delta_notional = (
            target_notional - current_notional
            if target_notional is not None and current_notional is not None
            else None
        )
        rows.append(
            {
                "symbol": symbol,
                "target_w": target_w,
                "broker_qty": qty,
                "price": price,
                "bid": bid,
                "ask": ask,
                "spread_bps": spread_bps,
                "change_pct": change_pct,
                "volume": row.get("volume"),
                "target_notional": target_notional,
                "current_notional": current_notional,
                "delta_notional": delta_notional,
                "updated_at": row.get("updated_at"),
                "quote_ok": bool(price),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.sort_values(["quote_ok", "target_w"], ascending=[False, False])
    return frame


def _format_live_table(frame: pd.DataFrame):
    formatters = {
        "target_w": "{:.2%}",
        "price": "${:,.2f}",
        "bid": "${:,.2f}",
        "ask": "${:,.2f}",
        "spread_bps": "{:.1f}",
        "change_pct": "{:.2%}",
        "target_notional": "${:,.0f}",
        "current_notional": "${:,.0f}",
        "delta_notional": "${:,.0f}",
        "volume": "{:,.0f}",
    }
    usable = {key: value for key, value in formatters.items() if key in frame.columns}
    return frame.style.format(usable, na_rep="—").background_gradient(
        subset=[col for col in ["change_pct", "delta_notional"] if col in frame.columns],
        cmap="RdYlGn",
    ).background_gradient(
        subset=[col for col in ["spread_bps"] if col in frame.columns],
        cmap="Reds",
    )


def render_live_market_monitor(
    service: DashboardService,
    snapshot: dict[str, Any] | None = None,
    *,
    key_prefix: str = "live_market",
    max_symbols: int = 40,
    compact: bool = False,
) -> pd.DataFrame:
    """Render a live quote board for the union of target and broker symbols."""
    st.caption(
        "Live quote board from Tastytrade for the active target/position universe. "
        "This is the human + agent market sanity check before preflight or rebalancing."
    )
    controls = st.columns([1, 1, 4])
    if controls[0].button("Refresh live quotes", key=f"{key_prefix}_refresh", type="primary"):
        st.session_state.pop(f"{key_prefix}_table", None)
    max_symbols = int(
        controls[1].number_input(
            "Symbols",
            min_value=5,
            max_value=150,
            value=max_symbols,
            step=5,
            key=f"{key_prefix}_max_symbols",
        )
    )
    if f"{key_prefix}_table" not in st.session_state:
        with st.spinner("Fetching live Tastytrade quotes..."):
            st.session_state[f"{key_prefix}_table"] = {
                "loaded_at": datetime.now().isoformat(timespec="seconds"),
                "frame": _market_table(service, snapshot, max_symbols=max_symbols),
            }

    cached = st.session_state[f"{key_prefix}_table"]
    frame = cached["frame"]
    if frame.empty:
        st.info("No target or broker symbols available for a live quote board yet.")
        return frame

    quote_count = int(frame["quote_ok"].sum()) if "quote_ok" in frame else 0
    missing = int(len(frame) - quote_count)
    avg_spread = pd.to_numeric(frame.get("spread_bps"), errors="coerce").dropna().mean()
    wide = pd.to_numeric(frame.get("spread_bps"), errors="coerce").dropna()
    wide_count = int((wide > 25.0).sum()) if len(wide) else 0
    gross_delta = pd.to_numeric(frame.get("delta_notional"), errors="coerce").abs().sum()

    cols = st.columns(5)
    cols[0].metric("Quoted", f"{quote_count}/{len(frame)}")
    cols[1].metric("Missing quotes", missing)
    cols[2].metric("Avg spread", f"{avg_spread:.1f} bps" if pd.notna(avg_spread) else "—")
    cols[3].metric("Wide spreads", wide_count, help="Symbols with quoted spread wider than 25 bps.")
    cols[4].metric("Gross drift notional", money(gross_delta) if gross_delta else "—")
    st.caption(f"Quote board loaded {cached['loaded_at']} local time.")

    columns = [
        "symbol",
        "target_w",
        "broker_qty",
        "price",
        "bid",
        "ask",
        "spread_bps",
        "change_pct",
        "delta_notional",
        "volume",
        "updated_at",
    ]
    display = frame[[col for col in columns if col in frame.columns]].copy()
    if compact:
        display = display.head(20)
    try:
        st.dataframe(_format_live_table(display), use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(display, use_container_width=True, hide_index=True)
    return frame
