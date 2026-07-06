"""Svyable CLI.

  svyable fetch                      refresh the data cache
  svyable daily                      full daily run: fetch -> pipeline -> morning report
  svyable backtest --start 2020-01-01 [--end ...] [--trials 20]
  svyable smoke                      synthetic end-to-end sanity run (no network)

Paths default to the repo layout: engine/data-cache, engine/outputs,
engine/universe_nasdaq_seed.txt; override with flags.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _provider(args):
    if getattr(args, "provider", "yf") == "tasty":
        from svyable.providers import TastytradeProvider
        return TastytradeProvider(cache_dir=Path(args.cache).parent / "data-cache-tasty",
                                  universe_file=args.universe)
    from svyable.providers import YFinanceProvider
    return YFinanceProvider(cache_dir=args.cache, universe_file=args.universe)


def _ledger(args):
    from svyable.ledger import Ledger
    return Ledger(Path(args.out) / "ledger.db")


def _tasty_sdk_broker(*, require_credentials: bool = True):
    from svyable.broker_settings import TastySettings
    from svyable.tastytrade_sdk import TastySdkBroker

    settings = TastySettings.from_env(require_credentials=require_credentials)
    if require_credentials:
        return TastySdkBroker(settings=settings)
    if settings.client_secret and settings.refresh_token and settings.account_number:
        return TastySdkBroker(settings=settings)
    return None


def _execution_inputs(run_dir: Path, provider, args, cfg):
    import pandas as pd

    path = run_dir / "execution_inputs.csv"
    if path.exists():
        data = pd.read_csv(path, index_col=0)
        prices = data.get("price", pd.Series(dtype=float)).dropna().astype(float).to_dict()
        adv = data.get("adv_dollars", pd.Series(dtype=float)).dropna().astype(float).to_dict()
        date = None
        meta_path = run_dir / "meta.json"
        if meta_path.exists():
            try:
                date = json.loads(meta_path.read_text()).get("execution_inputs", {}).get("date")
            except Exception:  # noqa: BLE001
                date = None
        return prices, adv, date

    panel = provider.get_panel(start=args.start)
    prices = panel.close.iloc[-1].dropna().to_dict()
    adv = panel.adv(cfg.adv_win).iloc[-1].dropna().to_dict()
    return prices, adv, str(panel.close.index[-1].date())


def _run_status_from_execution(status: str, dry_run: bool) -> str:
    status = str(status or "ok").lower()
    if dry_run and status in {"planned", "dry_run"}:
        return "ok"
    if status in {"failed", "degraded"}:
        return status
    return "ok"


def cmd_fetch(args) -> int:
    info = _provider(args).refresh(start=args.start)
    print(json.dumps(info, indent=2))
    return 0


def cmd_daily(args) -> int:
    from datetime import date
    from svyable.calendar import is_trading_day, expected_last_close
    from svyable.config import nasdaq_lo_config
    from svyable.pipeline import run_pipeline

    led = _ledger(args)

    if not is_trading_day(date.today()) and not args.force:
        print("market holiday/weekend — skipping (use --force to override)")
        led.record_run(kind="daily", strategy="svyable_nasdaq_lo",
                       status="ok", metrics={"skipped": "holiday"})
        return 0

    prov = _provider(args)
    try:
        info = prov.refresh(start=args.start)
        print(f"data refresh: {info}")
        if info.get("mode") == "full_restatement":
            led.record_event("warning", "data",
                             f"restatement full-refetch: {info.get('restated')}")
    except Exception as e:  # noqa: BLE001 — a failed refresh must not kill the run silently
        print(f"WARNING: data refresh failed ({e}); using cache", file=sys.stderr)
        led.record_event("warning", "data", f"refresh failed: {e}")

    panel = prov.get_panel(start=args.start)
    report = panel.validate()

    want = expected_last_close(date.today())
    have = panel.close.index[-1].date()
    if have < want:
        report["status"] = "degraded"
        report.setdefault("issues", []).append(f"stale: have {have}, expected {want}")

    try:
        broker = _tasty_sdk_broker(require_credentials=False)
        if broker is not None:
            sample = list(panel.close.iloc[-1].dropna().sort_values().index[-25:])
            snap = broker.get_market_snapshot(sample)
            diffs = []
            for sym in sample:
                ref = (snap.get(sym) or {}).get("prev_close") or \
                      (snap.get(sym) or {}).get("close")
                own = float(panel.close.iloc[-1].get(sym, float("nan")))
                if ref and own == own:
                    diffs.append(abs(own / ref - 1.0) * 1e4)
            if diffs:
                import statistics
                med = float(statistics.median(diffs))
                print(f"cross-provider close check: median {med:.1f} bps over {len(diffs)} names")
                if med > 25:
                    report["status"] = "degraded"
                    report.setdefault("issues", []).append(
                        f"cross-provider divergence {med:.0f} bps vs tastytrade")
    except Exception as e:  # noqa: BLE001 — the check must never block the run
        print(f"cross-provider check skipped: {e}", file=sys.stderr)

    if report["status"] != "ok":
        print(f"DATA DEGRADED: {report['issues']}", file=sys.stderr)
        led.record_event("warning", "data", f"degraded: {report['issues']}")
        if args.strict:
            led.record_run(kind="daily", strategy="svyable_nasdaq_lo",
                           status="failed", data_status="degraded",
                           metrics={"issues": report["issues"]})
            print("strict mode: refusing to emit weights on degraded data", file=sys.stderr)
            return 2

    cfg = nasdaq_lo_config()
    res = run_pipeline(panel, cfg, output_root=args.out, write_artifacts=True)

    shadow_nav = float((1.0 + res.pnl["net_ret"].fillna(0.0)).cumprod().iloc[-1])
    led.record_equity(str(have), shadow_nav=shadow_nav)
    led.record_run(
        kind="daily", strategy=cfg.strategy_id, status=report["status"],
        config_hash=cfg.config_hash(), data_last_date=str(have),
        data_status=report["status"],
        metrics={"budget": float(res.budget.iloc[-1]),
                 "positions": int((res.weights.iloc[-1] > 0).sum()),
                 "shadow_nav": shadow_nav,
                 "provider": panel.meta.get("provider"),
                 "adjustment": panel.meta.get("adjustment")},
        output_dir=str(res.output_dir))

    print(f"weights written: {res.output_dir}")
    print(f"budget: {float(res.budget.iloc[-1]):.2f}x, "
          f"positions: {int((res.weights.iloc[-1] > 0).sum())}")
    print(f"morning report: {res.output_dir / 'morning_report.md'}")

    try:
        from svyable.dashboard import generate
        print(f"dashboard: {generate(args.out, env=args.env)}")
    except Exception as e:  # noqa: BLE001 — dashboard is never worth failing a run
        print(f"WARNING: dashboard generation failed ({e})", file=sys.stderr)
    return 0


def cmd_backtest(args) -> int:
    from svyable.config import nasdaq_lo_config
    from svyable.pipeline import run_pipeline, backtest_report

    panel = _provider(args).get_panel(start=args.start, end=args.end)
    cfg = nasdaq_lo_config()
    res = run_pipeline(panel, cfg, output_root=args.out, write_artifacts=args.write)
    print(json.dumps(backtest_report(res, panel, cfg, n_trials=args.trials), indent=2))
    return 0


def cmd_factors(args) -> int:
    from svyable.config import nasdaq_lo_config
    from svyable.analysis import factor_report, report_markdown

    panel = _provider(args).get_panel(start=args.start)
    df = factor_report(panel, nasdaq_lo_config())
    md = report_markdown(df, title=f"Factor tearsheet — {panel.meta.get('provider')} "
                                   f"to {panel.close.index[-1].date()}")
    out = Path(args.out) / "factor_tearsheet.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(df.to_string())
    print(f"\ntearsheet: {out}")
    return 0


def cmd_walkforward(args) -> int:
    from svyable.config import nasdaq_lo_config
    from svyable.walkforward import walkforward_report

    panel = _provider(args).get_panel(start=args.start, end=args.end)
    rep = walkforward_report(panel, nasdaq_lo_config(), n_trials=args.trials,
                             run_sensitivity=not args.no_sensitivity)
    out = Path(args.out) / "walkforward.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str))
    slim = {k: rep[k] for k in ("aggregate", "deflated_sharpe", "consistency", "fragility")
            if k in rep}
    slim["by_year"] = rep.get("by_year")
    print(json.dumps(slim, indent=2, default=str))
    print(f"\nfull report: {out}")
    return 0


def cmd_rebalance(args) -> int:
    import pandas as pd
    from svyable.config import nasdaq_lo_config
    from svyable.brokers import LocalPaperBroker
    from svyable.rebalancer import plan_orders, execute_plan, reconcile

    cfg = nasdaq_lo_config()
    strat_dir = Path(args.out) / cfg.strategy_id

    runs = sorted(d for d in strat_dir.iterdir()
                  if d.is_dir() and (d / "weights_today.csv").exists())
    if not runs:
        print("no weights found — run `svyable daily` first", file=sys.stderr)
        return 2
    latest_run = runs[-1]
    wt = pd.read_csv(latest_run / "weights_today.csv", index_col=0)["weight"]
    print(f"using weights from {latest_run.name} ({len(wt)} positions)")

    prov = _provider(args)
    prices, adv, input_date = _execution_inputs(latest_run, prov, args, cfg)

    if args.broker == "tasty":
        broker = _tasty_sdk_broker(require_credentials=True)
        try:
            live = broker.execution_prices(sorted(set(wt.index) | set(broker.get_positions())))
            prices.update(live)
            print(f"live execution prices for {len(live)} symbols (tastytrade sdk snapshot)")
        except Exception as e:  # noqa: BLE001 — stale closes are an acceptable fallback
            print(f"WARNING: live quote snapshot failed ({e}); using execution inputs",
                  file=sys.stderr)
    else:
        broker = LocalPaperBroker(strat_dir / "paper_account.json",
                                  starting_cash=args.equity)
        broker.set_prices(prices)

    acct = broker.get_account()
    positions = broker.get_positions()
    orders = plan_orders(wt, acct["equity"], prices, positions, cfg, adv=adv)

    for o in orders:
        print(f"  {o.side.upper():4} {o.qty:>6} {o.symbol:<6} ~${o.est_notional:>10,.0f}  "
              f"({o.reason}; {o.order_action})")
    print(f"{len(orders)} orders | equity ${acct['equity']:,.0f}")

    rec = execute_plan(
        orders,
        broker,
        strat_dir / "orders",
        dry_run=not args.execute,
        fail_fast=not args.continue_on_error,
        confirmation=args.confirmation,
    )
    print(f"{'DRY RUN — nothing submitted' if not args.execute else rec['status'].upper()} "
          f"| log: {rec['log_file']}")

    rc = None
    ledger_status = _run_status_from_execution(rec.get("status"), not args.execute)
    if args.execute:
        eq = broker.get_account()["equity"]
        broker_positions = broker.get_positions()
        rc = reconcile(wt, eq, prices, broker_positions)
        print(f"reconcile: {rc['status']} ({len(rc['drifts'])} drifts)")
        if rc["status"] != "ok" and ledger_status != "failed":
            ledger_status = "degraded"

    led = _ledger(args)
    run_id = led.record_run(
        kind="rebalance",
        strategy=cfg.strategy_id,
        status=ledger_status,
        metrics={
            "orders": len(orders),
            "dry_run": not args.execute,
            "broker": args.broker,
            "execution_status": rec.get("status"),
            "aborted": rec.get("aborted"),
            "errors": rec.get("errors", []),
            "reconciliation": rc,
            "execution_inputs_date": input_date,
        },
    )
    led.record_orders(run_id, args.broker, not args.execute,
                      rec["planned"], rec.get("results", []))

    if args.execute:
        eq = broker.get_account()["equity"]
        if input_date:
            led.record_equity(input_date, paper_equity=eq)
        if rc and rc["status"] != "ok":
            led.record_event("warning", "reconcile", json.dumps(rc["drifts"]))
            led.update_run_status(run_id, "degraded")
    return 2 if args.execute and ledger_status != "ok" else 0


def cmd_health(args) -> int:
    led = _ledger(args)
    out = led.health()
    warn = led.open_warnings()
    out["recent_warnings"] = warn[["ts", "source", "message"]].to_dict(orient="records") \
        if len(warn) else []
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_auth(args) -> int:
    """One-time interactive Tastytrade OAuth onboarding (writes refresh token to .env)."""
    from svyable.oauth import authorize

    env_path = Path(args.env_file) if args.env_file else ROOT / ".env"
    try:
        summary = authorize(env_path, open_browser=not args.no_browser, scope=args.scope)
    except Exception as exc:  # noqa: BLE001 — surface a clean message, no secret leakage
        print(f"authorization failed: {exc}", file=sys.stderr)
        return 2
    print("\nauthorized:")
    print(json.dumps(summary, indent=2))
    print(
        "\nThe daily loop now refreshes access tokens silently — no further 2FA "
        "until the refresh token is revoked or expires."
    )
    return 0


def cmd_tasty(args) -> int:
    from svyable.tastytrade_sdk import OrderIntent

    b = _tasty_sdk_broker(require_credentials=True)

    if args.action == "status":
        print(json.dumps(b.status_snapshot(), indent=2, default=str))
    elif args.action == "orders":
        for o in b.search_orders(start_date=args.date):
            print(f"  #{o.get('id')} {o.get('status'):<16} {o.get('order_type'):<7} "
                  f"{o.get('underlying_symbol', ''):<6} size={o.get('size')}")
    elif args.action == "cancel":
        if args.id is None:
            print("--id required", file=sys.stderr)
            return 2
        print(json.dumps(b.cancel_order(args.id, confirmation=args.confirmation), indent=2))
    elif args.action == "dry-run":
        intent = OrderIntent(
            args.symbol,
            args.side,
            args.qty,
            "limit" if args.price else "market",
            "day",
            args.price,
            True,
        )
        print(json.dumps(b.submit_intent(intent), indent=2, default=str))
    elif args.action == "quotes":
        syms = (args.symbols or args.symbol).replace(" ", "").split(",")
        print(json.dumps(b.get_market_snapshot(syms), indent=2))
    elif args.action == "pnl":
        rep = b.pnl_report()
        for p in rep["positions"]:
            print(f"  {p['symbol']:<6} {p['qty']:>8.0f} @ {p['mark']:>9.2f}  "
                  f"value ${p['value']:>11,.0f}  unreal ${p['unrealized']:>9,.0f}  "
                  f"day ${p['pl_day']:>8,.0f}")
        print(f"net liq ${rep['net_liq']:,.2f} | cash ${rep['cash_balance']:,.2f} | "
              f"unrealized ${rep['total_unrealized']:,.2f} | day P/L ${rep['total_pl_day']:,.2f}")
    return 0


def cmd_universe(args) -> int:
    from svyable.tastytrade import TastytradeClient
    from svyable.universe import take_snapshot, build_membership, write_symbols_file

    c = TastytradeClient(env=args.env, allow_production=(args.env == "production"))
    snap_dir = Path(args.out) / "universe" / "snapshots"
    info = take_snapshot(c, snap_dir, listed_market=args.exchange)
    print(f"snapshot: {info}")

    mem = build_membership(snap_dir)
    n = write_symbols_file(mem, Path(args.universe).parent / "universe_pit.txt")
    print(f"membership: {mem.shape[0]} days x {mem.shape[1]} symbols "
          f"(accumulating since {mem.index[0].date()})")
    print(f"symbols file: universe_pit.txt ({n} names) — PIT coverage grows daily; "
          f"the daily loop takes a snapshot automatically")
    return 0


def cmd_smoke(args) -> int:
    from svyable.providers import SyntheticProvider
    from svyable.config import nasdaq_lo_config
    from svyable.pipeline import run_pipeline, backtest_report

    panel = SyntheticProvider(n_assets=50, n_days=700).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_train_win=252)
    res = run_pipeline(panel, cfg, output_root=args.out, write_artifacts=True)
    rep = backtest_report(res, panel, cfg)
    print(json.dumps(rep, indent=2))
    w = res.weights.iloc[-1]
    assert abs(w.sum() - float(res.budget.iloc[-1])) < 0.05, "weights != budget"
    assert (w >= -1e-9).all(), "long-only violated"
    print("SMOKE OK")
    return 0


def _apply_env(args) -> None:
    """Environment profiles: sandbox (default) and production get fully
    isolated caches, outputs, and ledgers — nothing is shared, so a dev
    iteration can never contaminate the PROD record."""
    import os
    if args.env == "production":
        os.environ["TT_ENV"] = "production"
        os.environ["SVYABLE_ENV"] = "production"
        if args.out == str(ROOT / "outputs"):
            args.out = str(ROOT / "outputs-production")
        if args.cache == str(ROOT / "data-cache"):
            args.cache = str(ROOT / "data-cache-production")
    else:
        os.environ.setdefault("TT_ENV", "sandbox")
        os.environ.setdefault("SVYABLE_ENV", "sandbox")


def cmd_session(args) -> int:
    """Morning warmup (~8:00 ET): validate OAuth, mint the 24h DXLink quote
    token, snapshot the universe. Access tokens live 15 min but auto-refresh
    from the never-expiring grant, so after this warmup the whole trading day
    runs hands-free."""
    from svyable.tastytrade import TastytradeClient
    from svyable.dxlink import DXLinkCandles
    from svyable.universe import take_snapshot

    led = _ledger(args)
    out = {"env": args.env}
    try:
        c = TastytradeClient(env=args.env, allow_production=(args.env == "production"))
        c._authenticate()
        out["auth"] = f"ok ({c.auth_mode}; access token auto-refreshes all day)"
        try:
            dxl = DXLinkCandles(c, token_cache=Path(args.cache).parent
                                / "data-cache-tasty" / "quote_token.json")
            dxl._quote_token()
            out["quote_token"] = "ok (24h)"
        except Exception as e:  # noqa: BLE001 — needs full customer account
            out["quote_token"] = f"unavailable: {e}"
        try:
            b = _tasty_sdk_broker(require_credentials=False)
            if b is not None:
                out["account"] = b.get_account()
            out["universe_snapshot"] = take_snapshot(
                c, Path(args.out) / "universe" / "snapshots")
        except Exception as e:  # noqa: BLE001
            out["account"] = f"unavailable: {e}"
        led.record_run(kind="session", strategy="warmup", status="ok", metrics=out)
        print(json.dumps(out, indent=2, default=str))
        return 0
    except Exception as e:  # noqa: BLE001
        led.record_event("critical", "session", str(e))
        print(json.dumps({"env": args.env, "error": str(e)}, indent=2))
        return 2


def cmd_dashboard(args) -> int:
    from svyable.dashboard import generate
    path = generate(args.out, env=args.env)
    print(f"dashboard: {path}")
    return 0


def _mark_of(m: dict) -> float | None:
    """Best live mark from a per-symbol quote/trade snapshot: quote mid if both
    sides are present, else last trade."""
    bid, ask, last = m.get("bid"), m.get("ask"), m.get("last")
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if last and last > 0:
        return last
    return None


def cmd_monitor(args) -> int:
    """Real-time portfolio monitor: live dxLink Quote/Trade/Summary marks for
    held equity positions, plus (optionally) the tastytrade account streamer for
    order/balance push. Observe-only — never places or mutates orders."""
    import threading
    import time as _t

    from svyable.tastytrade import TastytradeClient
    from svyable.dxlink import DXLinkFeed
    from svyable.account_streamer import AccountStreamer

    def _num(x):
        try:
            v = float(x)
            return v if v == v else None      # drop NaN
        except (TypeError, ValueError):
            return None

    client = TastytradeClient(env=args.env, allow_production=(args.env == "production"))
    broker = _tasty_sdk_broker(require_credentials=True)

    positions: dict[str, dict] = {}
    for row in broker.get_positions_frame():
        if row.get("instrument_type") != "Equity":
            continue
        qty = float(row.get("quantity") or 0.0)
        if abs(qty) < 1e-9:
            continue
        positions[str(row["symbol"]).upper()] = {
            "qty": qty, "avg": _num(row.get("average_open_price")) or 0.0}
    symbols = sorted(positions)
    if not symbols:
        print("no equity positions to monitor")
        return 0

    marks: dict[str, dict] = {s: {} for s in symbols}
    lock = threading.Lock()

    def on_event(ev: dict) -> None:
        sym = str(ev.get("eventSymbol", "")).upper()
        if sym not in marks:
            return
        etype = ev.get("eventType")
        with lock:
            m = marks[sym]
            if etype == "Quote":
                m["bid"], m["ask"] = _num(ev.get("bidPrice")), _num(ev.get("askPrice"))
            elif etype == "Trade":
                m["last"] = _num(ev.get("price"))
            elif etype == "Summary":
                m["prev_close"] = _num(ev.get("prevDayClosePrice"))

    if not args.no_account_stream:
        def account_loop() -> None:
            def _on_acct(n: dict) -> None:
                if n.get("type") == "Order":
                    o = n.get("data", {})
                    print(f"[order] #{o.get('id')} {o.get('status')} "
                          f"{o.get('underlying-symbol', '')}", flush=True)
            try:
                AccountStreamer(client, [broker.account_number]).stream(
                    _on_acct, run_s=args.duration)
            except Exception as exc:  # noqa: BLE001 — informational side channel
                print(f"account stream ended: {exc}", file=sys.stderr)
        threading.Thread(target=account_loop, daemon=True).start()

    subs = [{"type": t, "symbol": s} for s in symbols
            for t in ("Quote", "Trade", "Summary")]
    feed = DXLinkFeed(client, token_cache=Path(args.cache).parent
                      / "data-cache-tasty" / "quote_token.json")
    threading.Thread(
        target=lambda: feed.stream(subs, on_event, run_s=args.duration),
        daemon=True).start()

    print(f"monitoring {len(symbols)} positions for {args.duration:.0f}s "
          f"(env={args.env}); Ctrl-C to stop\n")
    t_end = _t.time() + args.duration
    try:
        while _t.time() < t_end:
            _t.sleep(args.interval)
            total_unreal = total_val = 0.0
            lines = []
            with lock:
                for s in symbols:
                    mark = _mark_of(marks[s])
                    pos = positions[s]
                    if mark is None:
                        lines.append(f"  {s:<6} {pos['qty']:>8.0f}   (awaiting quote)")
                        continue
                    val = mark * pos["qty"]
                    unreal = (mark - pos["avg"]) * pos["qty"]
                    prev = marks[s].get("prev_close")
                    day = f"{(mark - prev) / prev * 100:+.2f}%" if prev else "  n/a"
                    total_val += val
                    total_unreal += unreal
                    lines.append(f"  {s:<6} {pos['qty']:>8.0f} @ {mark:>9.2f}  "
                                 f"val ${val:>11,.0f}  unreal ${unreal:>9,.0f}  "
                                 f"day {day:>7}")
            ts = _t.strftime("%H:%M:%S")
            print(f"[{ts}] live marks")
            print("\n".join(lines))
            print(f"  {'TOTAL':<6} {'':>8}   {'':>9}   val ${total_val:>11,.0f}  "
                  f"unreal ${total_unreal:>9,.0f}\n", flush=True)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="svyable")
    p.add_argument("--env", choices=["sandbox", "production"],
                   default=__import__("os").environ.get("SVYABLE_ENV", "sandbox"),
                   help="isolated profile: separate cache/outputs/ledger per env")
    p.add_argument("--cache", default=str(ROOT / "data-cache"))
    p.add_argument("--out", default=str(ROOT / "outputs"))
    p.add_argument("--universe", default=str(ROOT / "universe_nasdaq_seed.txt"))
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--provider", choices=["yf", "tasty"], default="yf",
                   help="tasty = DXLink candles (needs tastytrade customer account)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch")

    d = sub.add_parser("daily")
    d.add_argument("--strict", action="store_true",
                   help="exit non-zero instead of emitting weights on degraded data")
    d.add_argument("--force", action="store_true",
                   help="run even on a market holiday/weekend")

    b = sub.add_parser("backtest")
    b.add_argument("--end", default=None)
    b.add_argument("--trials", type=int, default=20,
                   help="configs tried, for deflated Sharpe")
    b.add_argument("--write", action="store_true")

    sub.add_parser("factors")

    wf = sub.add_parser("walkforward")
    wf.add_argument("--end", default=None)
    wf.add_argument("--trials", type=int, default=20)
    wf.add_argument("--no-sensitivity", action="store_true")

    rb = sub.add_parser("rebalance")
    rb.add_argument("--broker", choices=["paper", "tasty"], default="paper")
    rb.add_argument("--equity", type=float, default=100_000.0,
                    help="starting cash for a fresh local paper account")
    rb.add_argument("--execute", action="store_true",
                    help="run broker-side execution path (default: dry run)")
    rb.add_argument("--confirmation", default="",
                    help="configured account number required for production tasty execution")
    rb.add_argument("--continue-on-error", action="store_true",
                    help="attempt later legs after one leg fails; status still becomes degraded")

    sub.add_parser("smoke")
    sub.add_parser("health")

    u = sub.add_parser("universe")
    u.add_argument("--exchange", default="XNAS")

    t = sub.add_parser("tasty")
    t.add_argument("action", choices=["status", "orders", "cancel", "dry-run",
                                      "quotes", "pnl"])
    t.add_argument("--symbols", default=None, help="comma-separated (quotes action)")
    t.add_argument("--id", type=int, default=None, help="order id (cancel)")
    t.add_argument("--date", default=None, help="start date for orders search")
    t.add_argument("--symbol", default="AAPL", help="dry-run symbol")
    t.add_argument("--qty", type=int, default=1, help="dry-run quantity")
    t.add_argument("--side", choices=["buy", "sell"], default="buy")
    t.add_argument("--price", type=float, default=None,
                   help="limit price (omit for market)")
    t.add_argument("--confirmation", default="",
                   help="configured account number required for production cancel")

    sub.add_parser("session")
    sub.add_parser("dashboard")

    mon = sub.add_parser("monitor", help="real-time position marks + account push (observe-only)")
    mon.add_argument("--duration", type=float, default=300.0,
                     help="seconds to run the monitor (default 300)")
    mon.add_argument("--interval", type=float, default=5.0,
                     help="seconds between P&L refreshes (default 5)")
    mon.add_argument("--no-account-stream", action="store_true",
                     help="live marks only; skip the order/balance account streamer")

    au = sub.add_parser("auth", help="one-time Tastytrade OAuth onboarding -> .env")
    au.add_argument("--env-file", default=None, help="path to .env (default engine/.env)")
    au.add_argument("--scope", default="read",
                    help="OAuth scope. Default 'read' mints a token that physically "
                         "cannot trade. Use --scope 'read trade' only at go-live.")
    au.add_argument("--no-browser", action="store_true",
                    help="print the URL instead of opening a browser")

    args = p.parse_args(argv)
    _apply_env(args)
    return {"fetch": cmd_fetch, "daily": cmd_daily, "backtest": cmd_backtest,
            "factors": cmd_factors, "walkforward": cmd_walkforward,
            "rebalance": cmd_rebalance, "smoke": cmd_smoke, "health": cmd_health,
            "universe": cmd_universe, "tasty": cmd_tasty, "auth": cmd_auth,
            "session": cmd_session, "dashboard": cmd_dashboard,
            "monitor": cmd_monitor}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
