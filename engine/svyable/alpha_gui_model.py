"""View models for alpha-catalyst GUI surfaces.

These helpers keep the Factor Governance Streamlit screen focused on rendering
while making the new alpha-factor and strategy summary testable.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from svyable.strategy_alpha_catalyst import ALPHA_CATALYST
from svyable.strategy_registry import get_strategy
from svyable.strategy_tape_acceleration import TAPE_ACCELERATION


ALPHA_STRATEGY_IDS = ("svyable_alpha_catalyst", "svyable_tape_acceleration")
ALPHA_FAMILIES = {
    **{name: "Alpha Catalyst" for name in ALPHA_CATALYST},
    **{name: "Tape Acceleration" for name in TAPE_ACCELERATION},
}


def _stage_for(catalog: pd.DataFrame, factor: str) -> str:
    if catalog is not None and not catalog.empty and factor in catalog.index and "stage" in catalog.columns:
        return str(catalog.loc[factor, "stage"])
    return "unknown"


def _catalog_value(catalog: pd.DataFrame, factor: str, column: str, default: Any = "") -> Any:
    if catalog is not None and not catalog.empty and factor in catalog.index and column in catalog.columns:
        return catalog.loc[factor, column]
    return default


def alpha_factor_table(catalog: pd.DataFrame) -> pd.DataFrame:
    """Return Alpha Catalyst + Tape Acceleration factor metadata rows."""
    rows: list[dict[str, Any]] = []
    for factor, family in ALPHA_FAMILIES.items():
        rows.append({
            "family": family,
            "factor": factor,
            "stage": _stage_for(catalog, factor),
            "sleeve": _catalog_value(catalog, factor, "sleeve", "unknown"),
            "lineage": _catalog_value(catalog, factor, "lineage", ""),
            "description": _catalog_value(catalog, factor, "description", ""),
        })
    return pd.DataFrame(rows)


def alpha_strategy_cards(catalog: pd.DataFrame) -> pd.DataFrame:
    """Return compact summary cards for the two newest alpha books."""
    stage_lookup = catalog["stage"].to_dict() if catalog is not None and not catalog.empty and "stage" in catalog.columns else {}
    rows: list[dict[str, Any]] = []
    for strategy_id in ALPHA_STRATEGY_IDS:
        spec = get_strategy(strategy_id)
        factors = tuple(spec.factor_names)
        alpha_family_count = sum(1 for factor in factors if factor in ALPHA_FAMILIES)
        proven = sum(1 for factor in factors if stage_lookup.get(factor) == "proven")
        shadow = sum(1 for factor in factors if stage_lookup.get(factor) == "shadow")
        rows.append({
            "strategy_id": spec.strategy_id,
            "name": spec.display_name,
            "family": spec.family,
            "regime_profile": spec.regime_profile,
            "alpha_family_factors": alpha_family_count,
            "total_factors": len(factors),
            "proven_factors": proven,
            "shadow_factors": shadow,
            "shadow_ratio": round(shadow / len(factors), 3) if factors else 0.0,
            "target_vol": spec.build_config().target_vol,
            "max_pos": spec.build_config().max_pos,
            "no_trade_band": spec.build_config().no_trade_band,
            "minimum_hold_days": spec.minimum_hold_days,
            "pitch_role": spec.pitch_role,
        })
    return pd.DataFrame(rows)


def alpha_dashboard_metrics(catalog: pd.DataFrame) -> dict[str, Any]:
    """Return headline metrics for the alpha GUI spotlight."""
    table = alpha_factor_table(catalog)
    stages = table["stage"].value_counts().to_dict() if not table.empty else {}
    strategies = alpha_strategy_cards(catalog)
    return {
        "alpha_factor_count": int(len(table)),
        "alpha_strategy_count": int(len(strategies)),
        "shadow_factors": int(stages.get("shadow", 0)),
        "proven_factors": int(stages.get("proven", 0)),
        "avg_shadow_ratio": round(float(strategies["shadow_ratio"].mean()), 3) if not strategies.empty else 0.0,
    }
