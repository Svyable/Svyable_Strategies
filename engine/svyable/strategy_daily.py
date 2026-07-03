"""Canonical weekday runner for the multi-strategy PM loop.

The runner refreshes one shared market panel and evaluates all enabled strategy
recipes. Deterministic/manual policies activate immediately. Agent mode emits an
immutable candidate board and waits for ``python -m svyable.strategy_activate``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from svyable.calendar import expected_last_close, is_trading_day
from svyable.ledger import Ledger
from svyable.providers import TastytradeProvider, YFinanceProvider
from svyable.strategy_activation import activate_latest_selection
from svyable.strategy_selector import load_policy, run_strategy_selection

ROOT = Path(__file__).resolve().parents[1]


def _provider(args):
    if args.provider == "tasty":
        return TastytradeProvider(
            cache_dir=Path(args.cache).parent / "data-cache-tasty",
            universe_file=args.universe,
        )
    return YFinanceProvider(cache_dir=args.cache, universe_file=args.universe)


def _broker_weights(panel, ledger: Ledger) -> tuple[pd.Series | None, str]:
    """Read actual Tastytrade equity weights; never submit or modify anything."""
    try:
        from svyable.broker_settings import TastySettings
        from svyable.tastytrade_sdk import TastySdkBroker

        settings = TastySettings.from_env(require_credentials=False)
        if not (
            settings.client_secret
            and settings.refresh_token
            and settings.account_number
        ):
            return None, "canonical_target"
        broker = TastySdkBroker(settings=settings)
        account = broker.get_account()
        equity = float(account.get("equity", 0.0))
        if equity <= 0:
            raise ValueError("Tastytrade account equity is not positive")
        rows = broker.get_positions_frame()
        values: dict[str, float] = {}
        latest_close = panel.close.iloc[-1]
        for row in rows:
            if str(row.get("instrument_type")) != "Equity":
                continue
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            market_value = row.get("market_value")
            if market_value is None:
                quantity = float(row.get("quantity", 0.0))
                price = float(latest_close.get(symbol, float("nan")))
                if price == price:
                    market_value = quantity * price
            if market_value is not None:
                values[symbol] = values.get(symbol, 0.0) + float(market_value)
        weights = pd.Series(values, dtype=float) / equity
        weights = weights[weights.abs() > 1e-10]
        ledger.record_event(
            "info",
            "strategy_selector",
            f"Using read-only Tastytrade actual positions for {len(weights)} equities.",
        )
        return weights, "tastytrade_actual"
    except Exception as exc:
        ledger.record_event(
            "warning",
            "strategy_selector",
            f"Actual-position read failed; using canonical target: {exc}",
        )
        return None, "canonical_target"


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
        actual_weights, position_source = _broker_weights(panel, ledger)
        selection = run_strategy_selection(
            panel,
            args.out,
            policy=policy,
            activate=False,
            current_weights_override=actual_weights,
            current_position_source=position_source,
        )

        awaiting_agent = policy.mode == "agent" or args.evaluate_only
        if awaiting_agent:
            decision = selection.decision
            status = "awaiting_agent" if policy.mode == "agent" else "evaluated"
            canonical_output = None
        else:
            decision = activate_latest_selection(args.out)
            status = report["status"]
            canonical_output = decision["canonical_output_dir"]

        strategy_id = str(decision["strategy_id"])
        selected_result = selection.candidate_results.get(strategy_id)
        shadow_nav = None
        if selected_result is not None:
            shadow_nav = float(
                (1.0 + selected_result.pnl["net_ret"].fillna(0.0))
                .cumprod()
                .iloc[-1]
            )
            if not awaiting_agent:
                ledger.record_equity(str(observed), shadow_nav=shadow_nav)

        ledger.record_run(
            kind="daily_selection",
            strategy="svyable_nasdaq_lo",
            status=status,
            data_last_date=str(observed),
            data_status=report["status"],
            metrics={
                "selected_strategy_id": strategy_id,
                "action": decision["action"],
                "selection_source": decision.get("source"),
                "current_position_source": position_source,
                "expected_alpha_bps": decision.get("expected_alpha_bps"),
                "one_way_turnover": decision.get("one_way_turnover"),
                "estimated_cost_bps": decision.get("estimated_cost_bps"),
                "candidate_set_hash": decision.get("candidate_set_hash"),
                "candidate_count": len(selection.board) - 1,
                "shadow_nav": shadow_nav,
                "awaiting_agent": awaiting_agent,
            },
            output_dir=str(canonical_output or selection.board_dir),
        )

        output = {
            "status": status,
            "recommended_strategy_id": strategy_id,
            "action": decision["action"],
            "source": decision.get("source"),
            "current_position_source": position_source,
            "reason": decision.get("reason"),
            "expected_alpha_bps": decision.get("expected_alpha_bps"),
            "one_way_turnover": decision.get("one_way_turnover"),
            "estimated_cost_bps": decision.get("estimated_cost_bps"),
            "candidate_board": str(selection.board_dir / "candidate_board.csv"),
            "canonical_output": canonical_output,
        }
        if policy.mode == "agent":
            output["next_step"] = (
                "Review the board, write strategy_selection/agent_decision.json, "
                "then run `python -m svyable.strategy_activate`."
            )
        print(json.dumps(output, indent=2, default=str))

        if not awaiting_agent:
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
    result.add_argument(
        "--evaluate-only",
        action="store_true",
        help="write the candidate board without activating canonical weights",
    )
    return result


def main(argv=None) -> int:
    return run(parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
