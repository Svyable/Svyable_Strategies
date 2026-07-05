"""Quality audit for strategy registry coverage and duplication.

This module is a read-only diagnostic layer. It looks for missing factor
references, duplicate strategy factor packs, repeated factors inside a strategy,
and heavily overlapping strategy pairs so we can refine or consolidate where
appropriate without changing daily selection behavior.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import pandas as pd

from svyable.factor_library import factor_metadata
from svyable.strategy_registry import list_strategies


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)


def registry_quality_audit(*, overlap_threshold: float = 0.85) -> dict[str, Any]:
    """Return read-only registry quality diagnostics."""
    catalog = factor_metadata()
    known = set(str(name) for name in catalog.index)
    specs = list_strategies(include_experimental=True)

    missing_rows: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []
    strategy_rows: list[dict[str, Any]] = []
    packs: dict[str, tuple[str, ...]] = {}

    for spec in specs:
        factors = tuple(str(item) for item in spec.factor_names)
        unique = tuple(dict.fromkeys(factors))
        repeated = sorted({factor for factor in factors if factors.count(factor) > 1})
        missing = sorted(set(factors) - known)
        if missing:
            missing_rows.append({"strategy_id": spec.strategy_id, "missing_factors": missing, "missing_count": len(missing)})
        if repeated:
            duplicate_rows.append({"strategy_id": spec.strategy_id, "duplicate_factors": repeated, "duplicate_count": len(repeated)})
        strategy_rows.append({
            "strategy_id": spec.strategy_id,
            "display_name": spec.display_name,
            "family": spec.family,
            "maturity": spec.maturity,
            "enabled_by_default": spec.enabled_by_default,
            "factor_count": len(factors),
            "unique_factor_count": len(unique),
            "missing_factor_count": len(missing),
            "duplicate_factor_count": len(repeated),
        })
        packs[spec.strategy_id] = unique

    exact_pack_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    for left, right in combinations(sorted(packs), 2):
        left_set = set(packs[left])
        right_set = set(packs[right])
        if packs[left] == packs[right]:
            exact_pack_rows.append({"left": left, "right": right, "factor_count": len(packs[left])})
        overlap = _jaccard(left_set, right_set)
        if overlap >= overlap_threshold and left_set != right_set:
            overlap_rows.append({
                "left": left,
                "right": right,
                "overlap": round(overlap, 4),
                "shared_factor_count": len(left_set & right_set),
                "left_only_count": len(left_set - right_set),
                "right_only_count": len(right_set - left_set),
            })

    blockers: list[str] = []
    warnings: list[str] = []
    if missing_rows:
        blockers.append("strategy registry references unknown factors")
    if duplicate_rows:
        warnings.append("one or more strategies repeat the same factor internally")
    if exact_pack_rows:
        warnings.append("one or more strategy pairs have identical factor packs")
    if overlap_rows:
        warnings.append("one or more strategy pairs have high factor-pack overlap")

    return {
        "status": "PASS" if not blockers else "BLOCK",
        "strategy_count": len(specs),
        "known_factor_count": len(known),
        "missing_reference_count": sum(row["missing_count"] for row in missing_rows),
        "duplicate_factor_count": sum(row["duplicate_count"] for row in duplicate_rows),
        "exact_duplicate_pack_count": len(exact_pack_rows),
        "high_overlap_pair_count": len(overlap_rows),
        "blockers": blockers,
        "warnings": warnings,
        "strategies": strategy_rows,
        "missing_references": missing_rows,
        "internal_duplicates": duplicate_rows,
        "exact_duplicate_packs": exact_pack_rows,
        "high_overlap_pairs": overlap_rows,
        "contract": "Read-only registry audit: does not alter factors, strategies, weights, or candidate selection.",
    }


def registry_quality_frames(*, overlap_threshold: float = 0.85) -> dict[str, pd.DataFrame]:
    """Return audit tables as DataFrames for Streamlit or notebooks."""
    report = registry_quality_audit(overlap_threshold=overlap_threshold)
    return {
        "strategies": pd.DataFrame(report["strategies"]),
        "missing_references": pd.DataFrame(report["missing_references"]),
        "internal_duplicates": pd.DataFrame(report["internal_duplicates"]),
        "exact_duplicate_packs": pd.DataFrame(report["exact_duplicate_packs"]),
        "high_overlap_pairs": pd.DataFrame(report["high_overlap_pairs"]),
    }
