"""Alpha-family governance helpers.

This module summarizes the newest Svyable factor families and strategies without
changing candidate selection or operational artifacts. It gives the PM a compact
view of what is in the incubation stack and which families still need more
health evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from svyable.factor_library import factor_metadata
from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_downside_resilience import DOWNSIDE_RESILIENCE
from svyable.strategy_leadership_quality import LEADERSHIP_QUALITY
from svyable.strategy_registry import get_strategy
from svyable.strategy_rotation_breadth import ROTATION_BREADTH
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


ALPHA_FAMILIES: dict[str, tuple[str, ...]] = {
    "alpha_catalyst": ALPHA_CATALYST,
    "tape_acceleration": TAPE_ACCELERATION,
    "leadership_quality": LEADERSHIP_QUALITY,
    "downside_resilience": DOWNSIDE_RESILIENCE,
    "rotation_breadth": ROTATION_BREADTH,
}

ALPHA_STRATEGIES: tuple[str, ...] = (
    "svyable_alpha_catalyst",
    "svyable_tape_acceleration",
    "svyable_leadership_quality",
    "svyable_downside_resilience",
    "svyable_rotation_breadth",
)


def alpha_family_factor_rows(catalog: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    """Return factor-level rows for the newest alpha-family stack."""
    catalog = factor_metadata() if catalog is None or catalog.empty else catalog
    stage_lookup = catalog["stage"].to_dict() if "stage" in catalog.columns else {}
    sleeve_lookup = catalog["sleeve"].to_dict() if "sleeve" in catalog.columns else {}
    lineage_lookup = catalog["lineage"].to_dict() if "lineage" in catalog.columns else {}
    rows: list[dict[str, Any]] = []
    for family, factors in ALPHA_FAMILIES.items():
        for factor in factors:
            rows.append({
                "family": family,
                "factor": factor,
                "stage": stage_lookup.get(factor, "unknown"),
                "sleeve": sleeve_lookup.get(factor, "unknown"),
                "lineage": lineage_lookup.get(factor, ""),
            })
    return rows


def alpha_family_strategy_rows(catalog: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    """Return strategy-level rows for alpha-family books."""
    catalog = factor_metadata() if catalog is None or catalog.empty else catalog
    stage_lookup = catalog["stage"].to_dict() if "stage" in catalog.columns else {}
    all_family_factors = {factor for factors in ALPHA_FAMILIES.values() for factor in factors}
    rows: list[dict[str, Any]] = []
    for strategy_id in ALPHA_STRATEGIES:
        spec = get_strategy(strategy_id)
        factors = tuple(spec.factor_names)
        shadow_count = sum(1 for factor in factors if stage_lookup.get(factor) == "shadow")
        family_count = sum(1 for factor in factors if factor in all_family_factors)
        cfg = spec.build_config()
        rows.append({
            "strategy_id": strategy_id,
            "display_name": spec.display_name,
            "family": spec.family,
            "regime_profile": spec.regime_profile,
            "factor_count": len(factors),
            "alpha_family_factor_count": family_count,
            "shadow_factor_count": shadow_count,
            "shadow_ratio": round(shadow_count / len(factors), 3) if factors else 0.0,
            "target_vol": cfg.target_vol,
            "max_pos": cfg.max_pos,
            "no_trade_band": cfg.no_trade_band,
            "minimum_hold_days": spec.minimum_hold_days,
        })
    return rows


def alpha_family_governance_report(catalog: pd.DataFrame | None = None) -> dict[str, Any]:
    """Return a compact read-only governance report for new alpha families."""
    factor_rows = alpha_family_factor_rows(catalog)
    strategy_rows = alpha_family_strategy_rows(catalog)
    family_frame = pd.DataFrame(factor_rows)
    stage_counts = (
        family_frame.groupby(["family", "stage"]).size().reset_index(name="count").to_dict(orient="records")
        if not family_frame.empty
        else []
    )
    blockers: list[str] = []
    warnings: list[str] = []
    if any(row["stage"] == "unknown" for row in factor_rows):
        blockers.append("one or more alpha-family factors are missing from factor metadata")
    if any(row["shadow_ratio"] > 0.60 for row in strategy_rows):
        warnings.append("one or more alpha-family strategies still rely heavily on shadow factors")
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "factor_count": len(factor_rows),
        "strategy_count": len(strategy_rows),
        "families": sorted(ALPHA_FAMILIES),
        "stage_counts": stage_counts,
        "strategy_rows": strategy_rows,
        "factor_rows": factor_rows,
        "blockers": blockers,
        "warnings": warnings,
        "contract": "Read-only alpha-family governance: does not compute portfolios, make decisions, or modify operations.",
    }


def render_alpha_family_markdown(report: dict[str, Any]) -> str:
    """Render a compact Markdown report."""
    lines = [
        "# Alpha-Family Governance Report",
        "",
        f"- Status: **{report.get('status', 'UNKNOWN')}**",
        f"- Families: {', '.join(report.get('families', []))}",
        f"- Factors: {report.get('factor_count', 0)}",
        f"- Strategies: {report.get('strategy_count', 0)}",
        "",
        report.get("contract", "Read-only governance."),
        "",
        "## Strategy rows",
        "",
    ]
    for row in report.get("strategy_rows", []) or []:
        lines.append(
            f"- `{row['strategy_id']}`: {row['alpha_family_factor_count']} family factors, "
            f"{row['shadow_factor_count']} shadow factors, target vol {row['target_vol']:.1%}, "
            f"minimum hold {row['minimum_hold_days']}d"
        )
    lines.extend(["", "## Warnings", ""])
    warnings = report.get("warnings", []) or []
    lines.extend([f"- {item}" for item in warnings] if warnings else ["None."])
    lines.extend(["", "## Blockers", ""])
    blockers = report.get("blockers", []) or []
    lines.extend([f"- {item}" for item in blockers] if blockers else ["None."])
    return "\n".join(lines).strip() + "\n"


def write_alpha_family_governance(output_root: str | Path = "outputs") -> dict[str, Any]:
    """Write JSON and Markdown alpha-family governance reports."""
    root = Path(output_root)
    report_dir = root / "governance"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = alpha_family_governance_report()
    json_path = report_dir / "latest_alpha_family_governance.json"
    md_path = report_dir / "latest_alpha_family_governance.md"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    md_path.write_text(render_alpha_family_markdown(report))
    return {**report, "json_path": str(json_path), "markdown_path": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render alpha-family governance diagnostics.")
    parser.add_argument("--out", default="outputs", help="Output root for persisted reports")
    parser.add_argument("--write", action="store_true", help="Persist JSON and Markdown reports")
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="Printed format")
    args = parser.parse_args(argv)

    report = write_alpha_family_governance(args.out) if args.write else alpha_family_governance_report()
    if args.format == "markdown":
        print(render_alpha_family_markdown(report))
    else:
        print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
