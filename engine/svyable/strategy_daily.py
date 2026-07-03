"""Canonical weekday runner for the multi-strategy PM loop.

Usage:
    python -m svyable.strategy_daily --start 2020-01-01

The runner refreshes one shared market panel, evaluates all enabled registered
strategies, applies the persisted selection policy, and writes one canonical
portfolio for the Tastytrade execution workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from svyable.calendar import expected_last_close, is_trading_day
from svyable.ledger import Ledger
from svyable.providers import TastytradeProvider, YFinanceProvider
from svyable.strategy_selector import load_policy, run_strategy_selection

ROOT = Path(__file__).resolve().parents[1]


def _provider(args):
    if args.provider == "tasty":
        return TastytradeProvider(
            cache_dir=Path(args.cache).parent / "data-cache-tasty",
            universe_file=args.universe,
        )
    return YFinanceProvider(cache_dir=args.cache, universe_file=args.universe)


def run(args) -> int:
    ledger = Ledger(Path(args.out) / "ledger.db")
    try:
        if not is_trading_day(date.today()) and not args.force:
            print("market holiday/weekend — skipping (use --force to override)")
            ledger.record_run(
                kind="daily_selection",
                strategy="svyable_nasdaq_lo",
                status="ok",
                metrics={"skipped": "holiday"},
            )
            return 0

        provider = _provider(args)
        try:
            info = provider.refresh(start=args.start)
            print(f"data refresh: {info}")
            if info.get("mode") == "full_restatement":
                ledger.record_event(
                    "warning",
                    "data",
                    f"restatement full-refetch: {info.get('restated')}",
                )
        except Exception as exc:
            print(f"WARNING: data refresh failed ({exc}); using cache", file=sys.stderr)
            ledger.record_event("warning", "data", f"refresh failed: {exc}")

        panel = provider.get_panel(start=args.start)
        report = panel.validate()
        expected = expected_last_close(date.today())
        observed = panel.close.index[-1].date()
        if observed < expected:
            report["status"] = "degraded"
            report.setdefault("issues", []).append(
                f"stale: have {observed}, expected {expected}"
            )
        if report["status"] != "ok":
            print(f"DATA DEGRADED: {report['issues']}", file=sys.stderr)
            ledger.record_event("warning", "data", f"degraded: {report['issues']}")
            if args.strict:
                ledger.record_run(
                    kind="daily_selection",
                    strategy="svyable_nasdaq_lo",
                    status="failed",
                    data_last_date=str(observed),
                    data_status="degraded",
                    metrics={"issues": report["issues"]},
                )
                return 2

        policy = load_policy(args.out)
        selection = run_strategy_selection(
            panel,
            args.out,
            policy=policy,
            activate=True,
        )
        decision = selection.decision
        strategy_id = str(decision["strategy_id"])
        selected_result = selection.candidate_results.get(strategy_id)
        shadow_nav = None
        if selected_result is not None:
            shadow_nav = float(
                (1.0 + selected_result.pnl["net_ret"].fillna(0.0))
                .cumprod()
                .iloc[-1]
            )
            ledger.record_equity(str(observed), shadow_nav=shadow_nav)

        ledger.record_run(
            kind="daily_selection",
            strategy="svyable_nasdaq_lo",
            status=report["status"],
            data_last_date=str(observed),
            data_status=report["status"],
            metrics={
                "selected_strategy_id": strategy_id,
                "action": decision["action"],
                "selection_source": decision.get("source"),
                "expected_alpha_bps": decision.get("expected_alpha_bps"),
                "one_way_turnover": decision.get("one_way_turnover"),
                "estimated_cost_bps": decision.get("estimated_cost_bps"),
                "candidate_set_hash": decision.get("candidate_set_hash"),
                "candidate_count": len(selection.board) - 1,
                "shadow_nav": shadow_nav,
            },
            output_dir=str(selection.canonical_output_dir or ""),
        )

        print(json.dumps({
            "selected_strategy_id": strategy_id,
            "action": decision["action"],
            "source": decision.get("source"),
            "reason": decision.get("reason"),
            "expected_alpha_bps": decision.get("expected_alpha_bps"),
            "one_way_turnover": decision.get("one_way_turnover"),
            "estimated_cost_bps": decision.get("estimated_cost_bps"),
            "candidate_board": str(selection.board_dir / "candidate_board.csv"),
            "canonical_output": str(selection.canonical_output_dir),
        }, indent=2, default=str))

        try:
            from svyable.dashboard import generate

            print(f"dashboard: {generate(args.out, env=args.env)}")
        except Exception as exc:
            print(f"WARNING: dashboard generation failed ({exc})", file=sys.stderr)
        return 0
    finally:
        ledger.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="svyable-strategy-daily")
    result.add_argument("--env", choices=["sandbox", "production"], default="sandbox")
    result.add_argument("--cache", default=str(ROOT / "data-cache"))
    result.add_argument("--out", default=str(ROOT / "outputs"))
    result.add_argument("--universe", default=str(ROOT / "universe_nasdaq_seed.txt"))
    result.add_argument("--start", default="2020-01-01")
    result.add_argument("--provider", choices=["yf", "tasty"], default="yf")
    result.add_argument("--strict", action="store_true")
    result.add_argument("--force", action="store_true")
    return result


def main(argv=None) -> int:
    return run(parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
