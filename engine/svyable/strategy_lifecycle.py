"""Day-in-the-life runbook for a Svyable strategy candidate.

This is a narrative/read-only model of the daily operating lifecycle. It helps
humans, agents, and docs describe what a strategy does from approved code to
candidate review to canonical artifacts without creating weights, changing
strategies, or touching broker-facing workflows.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from svyable.strategy_registry import get_strategy


DEFAULT_STRATEGY_ID = "svyable_alpha_catalyst"


def strategy_day_in_life(strategy_id: str = DEFAULT_STRATEGY_ID, *, as_of: str | None = None) -> dict[str, Any]:
    """Return a structured read-only day-in-life runbook for a strategy."""
    spec = get_strategy(strategy_id)
    config = spec.build_config()
    as_of_date = as_of or date.today().isoformat()
    stages = [
        {
            "phase": "00 · Approved-code boundary",
            "owner": "research/dev loop",
            "what_happens": "Only code that already lives on main can affect today's candidate board.",
            "artifact": "repository commit history",
            "guardrail": "No same-cycle code modification inside the daily PM loop.",
        },
        {
            "phase": "01 · Data refresh",
            "owner": "runtime",
            "what_happens": "Daily OHLCV panel is refreshed, validated, cached, and aligned to the expected close.",
            "artifact": "Panel(open/high/low/close/volume)",
            "guardrail": "Point-in-time discipline; stale or missing inputs surface as readiness issues.",
        },
        {
            "phase": "02 · Factor compute",
            "owner": "factor library",
            "what_happens": "The strategy's factor pack is computed using causal daily-bar transforms.",
            "artifact": "factor score frames",
            "guardrail": "Higher scores must mean more attractive to own; shadow factors earn no guaranteed floor.",
        },
        {
            "phase": "03 · Strategy recipe",
            "owner": "strategy registry",
            "what_happens": "The registered strategy applies its factor list, construction settings, concentration caps, cost assumptions, cadence, and maturity metadata.",
            "artifact": "StrategySpec + built SvyableConfig",
            "guardrail": "Strategies own factors/config; agents do not invent raw weights or symbols.",
        },
        {
            "phase": "04 · Candidate construction",
            "owner": "portfolio engine",
            "what_happens": "Seat selection, smoothing, no-trade bands, cluster caps, volatility target, and cost model create a candidate artifact.",
            "artifact": "candidate weights and operating inputs",
            "guardrail": "ADV, concentration, turbulence, and cost controls throttle the candidate before review.",
        },
        {
            "phase": "05 · Candidate board",
            "owner": "selector",
            "what_happens": "All enabled strategies and chimeras are ranked on an immutable board with a candidate-set hash.",
            "artifact": "candidate_board.csv + candidate_set_hash",
            "guardrail": "Later decisions must reference one allowed candidate ID and the matching hash.",
        },
        {
            "phase": "06 · Visible PM context",
            "owner": "agent PM harness",
            "what_happens": "Context, memo, visible rationale tree, readiness gates, counterfactuals, and allowed IDs are packaged for review.",
            "artifact": "agent_context.json + agent_pm_memo.md",
            "guardrail": "The harness explains artifacts; it does not expose hidden reasoning or create positions.",
        },
        {
            "phase": "07 · Human/agent review",
            "owner": "human PM + optional agent",
            "what_happens": "Selection Meta Harness and Factor Governance show alpha spotlight, registry quality, factor maturity, utility, regime proxy, and weight provenance.",
            "artifact": "GUI review + optional registry quality report",
            "guardrail": "Review is read-only until a guarded decision artifact is written.",
        },
        {
            "phase": "08 · Decision artifact",
            "owner": "guarded writer",
            "what_happens": "A small decision file selects exactly one allowed candidate using the latest date and board hash.",
            "artifact": "agent_decision.json",
            "guardrail": "The decision contains candidate ID, confidence, and reason only; no quantities or orders.",
        },
        {
            "phase": "09 · Guard / receipt / audit",
            "owner": "review chain",
            "what_happens": "Decision guard validates the file, review receipt freezes hashes, and integrity audit verifies nothing changed after review.",
            "artifact": "latest_agent_decision_guard.json, latest_agent_review_receipt.*, latest_agent_review_audit.json",
            "guardrail": "Any BLOCK must be resolved before canonical artifacts are prepared.",
        },
        {
            "phase": "10 · Canonical artifact handoff",
            "owner": "activation layer",
            "what_happens": "The reviewed candidate becomes the canonical target artifact for operations, then Portfolio Ops handles drift, quotes, preflight, reconciliation, and audit.",
            "artifact": "weights_today.csv + execution_inputs.csv + ledger.db",
            "guardrail": "Operations consume canonical artifacts only; bulk production action from Streamlit remains disabled.",
        },
        {
            "phase": "11 · Learning loop",
            "owner": "research/dev loop",
            "what_happens": "New issues, diagnostics, factor health, and registry quality findings become future code/research tasks after the daily loop.",
            "artifact": "docs, tests, commits, governance reports",
            "guardrail": "Future improvements can inform tomorrow's board, not today's already-reviewed cycle.",
        },
    ]
    return {
        "strategy_id": spec.strategy_id,
        "display_name": spec.display_name,
        "as_of": as_of_date,
        "family": spec.family,
        "regime_profile": spec.regime_profile,
        "maturity": spec.maturity,
        "enabled_by_default": spec.enabled_by_default,
        "factor_count": len(spec.factor_names),
        "pitch_role": spec.pitch_role,
        "minimum_hold_days": spec.minimum_hold_days,
        "config_summary": {
            "seats_base": config.seats_base,
            "seats_min": config.seats_min,
            "seats_max": config.seats_max,
            "max_pos": config.max_pos,
            "cluster_weight_cap": config.cluster_weight_cap,
            "no_trade_band": config.no_trade_band,
            "target_vol": config.target_vol,
            "target_vol_stressed": config.target_vol_stressed,
            "tc_bps": config.tc_bps,
            "ml_enabled": config.ml_enabled,
        },
        "stages": stages,
        "contract": "Read-only lifecycle narrative: does not compute factors, rank candidates, write decisions, create target weights, or touch operations.",
    }


def render_strategy_day_markdown(runbook: dict[str, Any]) -> str:
    """Render a human-readable day-in-life narrative."""
    cfg = runbook.get("config_summary", {}) or {}
    lines = [
        f"# A day in the life of {runbook.get('display_name', runbook.get('strategy_id'))}",
        "",
        f"Date lens: `{runbook.get('as_of')}`",
        "",
        "## Identity",
        "",
        f"- Strategy ID: `{runbook.get('strategy_id')}`",
        f"- Family: {runbook.get('family')}",
        f"- Regime profile: `{runbook.get('regime_profile')}`",
        f"- Maturity: `{runbook.get('maturity')}`",
        f"- Enabled by default: `{runbook.get('enabled_by_default')}`",
        f"- Factor count: {runbook.get('factor_count')}",
        f"- Role: {runbook.get('pitch_role')}",
        "",
        "## Operating shape",
        "",
        f"- Seats: {cfg.get('seats_min')}–{cfg.get('seats_max')} around base {cfg.get('seats_base')}",
        f"- Max position: {cfg.get('max_pos'):.2%}",
        f"- Cluster cap: {cfg.get('cluster_weight_cap'):.2%}",
        f"- No-trade band: {cfg.get('no_trade_band'):.2%}",
        f"- Target volatility: {cfg.get('target_vol'):.2%}; stressed target: {cfg.get('target_vol_stressed'):.2%}",
        f"- Cost assumption: {cfg.get('tc_bps')} bps",
        f"- Minimum hold: {runbook.get('minimum_hold_days')} days",
        f"- ML sleeve: {'enabled' if cfg.get('ml_enabled') else 'disabled'}",
        "",
        "## Timeline",
        "",
    ]
    for stage in runbook.get("stages", []) or []:
        lines.extend([
            f"### {stage['phase']}",
            "",
            f"- Owner: {stage['owner']}",
            f"- What happens: {stage['what_happens']}",
            f"- Artifact: `{stage['artifact']}`",
            f"- Guardrail: {stage['guardrail']}",
            "",
        ])
    lines.extend(["## Contract", "", runbook.get("contract", "Read-only narrative."), ""])
    return "\n".join(lines)


def write_strategy_day_runbook(
    output_root: str | Path = "outputs",
    *,
    strategy_id: str = DEFAULT_STRATEGY_ID,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Write JSON and Markdown day-in-life runbooks under outputs/runbooks."""
    root = Path(output_root)
    report_dir = root / "runbooks"
    report_dir.mkdir(parents=True, exist_ok=True)
    runbook = strategy_day_in_life(strategy_id, as_of=as_of)
    safe_id = strategy_id.replace("/", "_")
    json_path = report_dir / f"{safe_id}_day_in_life.json"
    md_path = report_dir / f"{safe_id}_day_in_life.md"
    json_path.write_text(json.dumps(runbook, indent=2, default=str))
    md_path.write_text(render_strategy_day_markdown(runbook))
    return {**runbook, "json_path": str(json_path), "markdown_path": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a read-only Svyable strategy day-in-life runbook.")
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY_ID, help="Registered strategy ID")
    parser.add_argument("--as-of", default=None, help="Optional date label for the runbook")
    parser.add_argument("--out", default="outputs", help="Output root for persisted runbooks")
    parser.add_argument("--write", action="store_true", help="Persist JSON and Markdown runbooks")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown", help="Printed format")
    args = parser.parse_args(argv)

    runbook = write_strategy_day_runbook(args.out, strategy_id=args.strategy, as_of=args.as_of) if args.write else strategy_day_in_life(args.strategy, as_of=args.as_of)
    if args.format == "json":
        print(json.dumps(runbook, indent=2, default=str))
    else:
        print(render_strategy_day_markdown(runbook))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
