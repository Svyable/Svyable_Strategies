"""CLI entry point for activating the latest validated strategy decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from svyable.dashboard import generate
from svyable.ledger import Ledger
from svyable.strategy_activation import activate_latest_selection

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="svyable-strategy-activate")
    parser.add_argument("--out", default=str(ROOT / "outputs"))
    parser.add_argument("--env", choices=["sandbox", "production"], default="sandbox")
    args = parser.parse_args(argv)

    result = activate_latest_selection(args.out)
    ledger = Ledger(Path(args.out) / "ledger.db")
    try:
        ledger.record_run(
            kind="strategy_activation",
            strategy="svyable_nasdaq_lo",
            status="ok",
            data_last_date=str(result.get("as_of", "")),
            metrics={
                "selected_strategy_id": result.get("strategy_id"),
                "action": result.get("action"),
                "source": result.get("source"),
                "expected_alpha_bps": result.get("expected_alpha_bps"),
                "one_way_turnover": result.get("one_way_turnover"),
                "estimated_cost_bps": result.get("estimated_cost_bps"),
                "candidate_set_hash": result.get("candidate_set_hash"),
            },
            output_dir=str(result["canonical_output_dir"]),
        )
    finally:
        ledger.close()

    print(json.dumps(result, indent=2, default=str))
    try:
        print(f"dashboard: {generate(args.out, env=args.env)}")
    except Exception as exc:
        print(f"dashboard generation warning: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
