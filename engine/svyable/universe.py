"""NASDAQ universe from tastytrade instruments — snapshot-accumulation PIT.

tastytrade's GET /instruments/equities/active lists what is tradable TODAY;
there is no historical as-of query. So point-in-time membership is built the
honest way: snapshot the active list on a schedule (the daily loop), persist
each dated snapshot, and derive membership from the accumulated record.

Index membership changes announced before their effective date are handled as
small, explicit event records layered over the accumulated snapshots. This keeps
the workflow simple and audit-friendly: the broker snapshot says what is
tradable, while the event ledger says when an index constituent should enter or
leave the strategy universe.

Consequences, stated plainly:
- PIT coverage begins the day snapshots start accumulating — deep-history
  backtests remain survivorship-biased until enough snapshots exist (or a
  historical membership dataset is purchased later).
- From day one, though, the LIVE book's universe is exactly what is tradable
  at the broker — no symbol-mapping drift between data and execution.
- Scheduled index changes are deterministic and idempotent: staging the same
  official add/remove record repeatedly produces the same effective universe.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd


_VALID_INDEX_ACTIONS = {"add", "remove"}


@dataclass(frozen=True)
class IndexChange:
    """One official constituent change, effective before the market open."""

    effective_date: date
    action: str
    symbol: str
    index: str = "NASDAQ100"
    source: str = ""
    note: str = ""


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_index(index: str) -> str:
    return "".join(ch for ch in str(index or "").upper() if ch.isalnum())


def _coerce_date(value) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def read_symbols_file(path: str | Path) -> list[str]:
    """Read a one-symbol-per-line universe file with comments."""

    path = Path(path)
    syms = [
        _normalize_symbol(ln)
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    return sorted({s for s in syms if s})


def load_index_changes(path: str | Path | None,
                       index: str = "NASDAQ100") -> list[IndexChange]:
    """Load scheduled add/remove events from a small CSV manifest.

    Required columns: effective_date, action, symbol.
    Optional columns: index, source, note.

    The manifest is deliberately boring CSV so humans and agents can review it
    in diffs. Conflicting same-day instructions for one symbol are rejected.
    """

    if path is None:
        return []
    path = Path(path)
    if not path.exists():
        return []

    rows = [ln for ln in path.read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    if not rows:
        return []

    reader = csv.DictReader(rows)
    required = {"effective_date", "action", "symbol"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")

    wanted_index = _normalize_index(index)
    out: list[IndexChange] = []
    seen: dict[tuple[date, str, str], str] = {}
    for n, row in enumerate(reader, start=2):
        idx = _normalize_index(row.get("index") or index)
        if wanted_index and idx != wanted_index:
            continue

        action = str(row.get("action") or "").strip().lower()
        if action not in _VALID_INDEX_ACTIONS:
            raise ValueError(f"{path}:{n} invalid action {action!r}")

        sym = _normalize_symbol(row.get("symbol") or "")
        if not sym:
            raise ValueError(f"{path}:{n} blank symbol")

        eff = _coerce_date(row.get("effective_date"))
        key = (eff, idx, sym)
        prev = seen.get(key)
        if prev and prev != action:
            raise ValueError(
                f"{path}:{n} conflicting same-day actions for {sym} on {eff}: "
                f"{prev!r} vs {action!r}"
            )
        seen[key] = action

        out.append(IndexChange(
            effective_date=eff,
            action=action,
            symbol=sym,
            index=idx or wanted_index,
            source=str(row.get("source") or "").strip(),
            note=str(row.get("note") or "").strip(),
        ))

    return sorted(out, key=lambda e: (e.effective_date, e.symbol, e.action))


def apply_index_changes_to_symbols(symbols: Iterable[str],
                                   index_events: Iterable[IndexChange],
                                   as_of: date | str | None = None,
                                   index: str = "NASDAQ100") -> tuple[list[str], list[dict]]:
    """Apply scheduled constituent events to a base symbol set.

    Future-dated events are returned as ``pending`` in the audit trail but are
    not applied until ``as_of`` reaches their effective date.
    """

    as_of_date = _coerce_date(as_of or date.today())
    wanted_index = _normalize_index(index)
    current = {_normalize_symbol(s) for s in symbols if _normalize_symbol(s)}
    audit: list[dict] = []

    for event in sorted(index_events, key=lambda e: (e.effective_date, e.symbol, e.action)):
        if wanted_index and _normalize_index(event.index) != wanted_index:
            continue

        before = event.symbol in current
        status = "pending"
        if event.effective_date <= as_of_date:
            if event.action == "add":
                current.add(event.symbol)
                status = "applied" if not before else "noop_present"
            elif event.action == "remove":
                current.discard(event.symbol)
                status = "applied" if before else "noop_absent"
            else:  # defensive; load_index_changes already validates
                raise ValueError(f"invalid action {event.action!r}")

        audit.append({
            "effective_date": str(event.effective_date),
            "as_of": str(as_of_date),
            "index": _normalize_index(event.index),
            "action": event.action,
            "symbol": event.symbol,
            "status": status,
            "source": event.source,
            "note": event.note,
        })

    return sorted(current), audit


def _first_index_on_or_after(index: pd.Index, effective: date) -> pd.Timestamp | None:
    ts = pd.Timestamp(effective)
    pos = index.searchsorted(ts)
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def apply_index_changes_to_membership(membership: pd.DataFrame,
                                      index_events: Iterable[IndexChange],
                                      as_of: date | str | None = None,
                                      index: str = "NASDAQ100") -> pd.DataFrame:
    """Overlay scheduled constituent changes onto a daily membership matrix."""

    events = list(index_events)
    if membership.empty or not events:
        return membership

    as_of_date = _coerce_date(as_of or date.today())
    horizon = max(pd.Timestamp(as_of_date), pd.Timestamp(membership.index[-1]))
    daily = membership.reindex(pd.bdate_range(membership.index[0], horizon))
    daily = daily.astype("boolean").ffill().fillna(False).astype(bool)

    wanted_index = _normalize_index(index)
    for event in sorted(events, key=lambda e: (e.effective_date, e.symbol, e.action)):
        if event.effective_date > as_of_date:
            continue
        if wanted_index and _normalize_index(event.index) != wanted_index:
            continue

        eff = _first_index_on_or_after(daily.index, event.effective_date)
        if eff is None:
            continue
        if event.symbol not in daily.columns:
            daily[event.symbol] = False

        if event.action == "add":
            daily.loc[eff:, event.symbol] = True
        elif event.action == "remove":
            daily.loc[eff:, event.symbol] = False
        else:  # defensive; load_index_changes already validates
            raise ValueError(f"invalid action {event.action!r}")

    return daily.reindex(sorted(daily.columns), axis=1)


def write_effective_universe_file(seed_file: str | Path,
                                  index_events_file: str | Path | None,
                                  path: str | Path,
                                  as_of: date | str | None = None,
                                  index: str = "NASDAQ100") -> dict:
    """Materialize the universe used by providers for one deterministic run."""

    seed_file = Path(seed_file)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    as_of_date = _coerce_date(as_of or date.today())

    events = load_index_changes(index_events_file, index=index)
    symbols, audit = apply_index_changes_to_symbols(
        read_symbols_file(seed_file),
        events,
        as_of=as_of_date,
        index=index,
    )

    source = str(index_events_file) if index_events_file else ""
    path.write_text(
        "# generated by svyable.universe — base seed + scheduled index changes\n"
        f"# base: {seed_file}\n"
        f"# events: {source or 'none'}\n"
        f"# as_of: {as_of_date}\n"
        + "\n".join(symbols)
        + "\n"
    )
    return {
        "path": str(path),
        "symbols": len(symbols),
        "as_of": str(as_of_date),
        "applied_events": sum(1 for x in audit if x["status"] == "applied"),
        "pending_events": sum(1 for x in audit if x["status"] == "pending"),
        "audit": audit,
    }


def fetch_active_equities(broker_or_client, listed_market: str = "XNAS",
                          per_page: int = 1000, max_pages: int = 30) -> list[dict]:
    """All active equities on `listed_market` right now. Accepts a
    TastytradeClient — or anything exposing `.request` or `.c.request`."""
    c = getattr(broker_or_client, "c", broker_or_client)
    out: list[dict] = []
    for page in range(max_pages):
        d = c.request("GET", "/instruments/equities/active",
                      params={"per-page": per_page, "page-offset": page})
        items = d.get("items", [])
        out += items
        if len(items) < per_page:
            break
    keep = []
    for it in out:
        if listed_market and it.get("listed-market") not in (listed_market, None):
            continue
        if it.get("is-options-only") or it.get("is-etf"):
            continue
        keep.append({"symbol": it.get("symbol"),
                     "listed_market": it.get("listed-market"),
                     "is_index": it.get("is-index", False),
                     "streamer_symbol": it.get("streamer-symbol", it.get("symbol"))})
    return [k for k in keep if k["symbol"] and not k["is_index"]]


def take_snapshot(broker_or_client, out_dir: str | Path,
                  listed_market: str = "XNAS") -> dict:
    """Persist today's active-equity snapshot (idempotent per day)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = str(date.today())
    path = out_dir / f"{today}.json"
    if path.exists():
        return {"date": today, "symbols": len(json.loads(path.read_text())["symbols"]),
                "status": "exists"}
    eq = fetch_active_equities(broker_or_client, listed_market=listed_market)
    path.write_text(json.dumps({"date": today, "listed_market": listed_market,
                                "symbols": sorted(e["symbol"] for e in eq)}, indent=0))
    return {"date": today, "symbols": len(eq), "status": "written"}


def build_membership(snapshot_dir: str | Path,
                     index_events: Iterable[IndexChange] | str | Path | None = None,
                     as_of: date | str | None = None,
                     index: str = "NASDAQ100") -> pd.DataFrame:
    """Daily boolean membership from accumulated snapshots plus event ledger."""

    snapshot_dir = Path(snapshot_dir)
    snaps = sorted(snapshot_dir.glob("????-??-??.json"))
    if not snaps:
        raise FileNotFoundError(f"no snapshots in {snapshot_dir} — run take_snapshot first")
    rows = {}
    for p in snaps:
        js = json.loads(p.read_text())
        rows[pd.Timestamp(js["date"])] = set(js["symbols"])
    all_syms = sorted(set.union(*rows.values()))
    mem = pd.DataFrame(False, index=sorted(rows), columns=all_syms)
    for d, syms in rows.items():
        mem.loc[d, sorted(syms)] = True

    as_of_date = _coerce_date(as_of or date.today())
    horizon = max(pd.Timestamp(as_of_date), pd.Timestamp(date.today()))
    daily = mem.reindex(pd.bdate_range(mem.index[0], horizon))
    daily = daily.astype("boolean").ffill().fillna(False).astype(bool)

    events: list[IndexChange]
    if index_events is None:
        events = []
    elif isinstance(index_events, (str, Path)):
        events = load_index_changes(index_events, index=index)
    else:
        events = list(index_events)

    return apply_index_changes_to_membership(daily, events, as_of=as_of_date, index=index)


def write_symbols_file(membership: pd.DataFrame, path: str | Path,
                       min_days_listed: int = 1) -> int:
    """Union of names ever seen (delisted history included once accumulated)."""
    days = membership.sum()
    keep = sorted(days[days >= min_days_listed].index)
    Path(path).write_text(
        "# generated by svyable.universe — tastytrade snapshot accumulation\n"
        + "\n".join(keep) + "\n")
    return len(keep)


def apply_membership(panel_close: pd.DataFrame,
                     membership: pd.DataFrame) -> pd.DataFrame:
    """Boolean mask aligned to a panel: tradable only while a member."""
    m = membership.reindex(index=panel_close.index, columns=panel_close.columns)
    return m.ffill().fillna(False)


def _parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="python -m svyable.universe",
        description="Materialize a deterministic universe from a seed file and index events.",
    )
    p.add_argument("--seed", default=str(Path(__file__).resolve().parents[1]
                                         / "universe_nasdaq_seed.txt"))
    p.add_argument("--events", default=str(Path(__file__).resolve().parents[1]
                                           / "universe_index_events.csv"))
    p.add_argument("--out", default=str(Path(__file__).resolve().parents[1]
                                        / "outputs" / "universe"
                                        / "effective_universe.txt"))
    p.add_argument("--as-of", default=None,
                   help="as-of date for staged events; defaults to today")
    p.add_argument("--index", default="NASDAQ100")
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    info = write_effective_universe_file(
        args.seed,
        args.events,
        args.out,
        as_of=args.as_of,
        index=args.index,
    )
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
