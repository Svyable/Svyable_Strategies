"""Explicit factor menus for reproducible Q23-style strategy variants.

Profiles keep the production strategy small and inspectable. Adding a factor to
the registry does not silently change live weights; promotion requires changing
the selected profile or supplying an explicit factor list in configuration.
"""

from __future__ import annotations


Q23_PRICE_ACTION: tuple[str, ...] = (
    # defensive / low risk
    "inv_vol",
    "inv_downside",
    "low_beta",
    "beta_stability",
    "amihud_inv",
    "vol_of_vol_inv",
    # momentum / trend
    "mom_12_1",
    "resid_mom",
    "resid_mom_short",
    "trend_consistency",
    "prox_52w_high",
    "slope_ema",
    "breakout",
    "mom_accel",
    "momentum_quality",
    "efficiency_ratio",
    "capm_alpha",
    # mean reversion / OU
    "srev",
    "resid_srev",
    "ou_zscore",
    "ou_predicted_return",
    "ou_mom_blend",
    "mean_reversion_speed",
)

Q23_CORE: tuple[str, ...] = Q23_PRICE_ACTION + (
    # Daily OHLCV flow proxies that were useful in the Q23 harness. They remain
    # isolated in the micro sleeve and can be removed without changing code.
    "ofi_med",
    "mtf_ofi_alignment",
    "kyle_lambda_inv",
    "bvc_imbalance",
    "exec_quality",
    "flow_persistence",
)

PROFILES: dict[str, tuple[str, ...] | None] = {
    "q23_price_action": Q23_PRICE_ACTION,
    "q23_core": Q23_CORE,
    "research_all": None,
}


def factor_names(profile: str, registry_names: list[str]) -> list[str]:
    """Resolve a profile against the active registry in deterministic order."""
    if profile not in PROFILES:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown factor profile {profile!r}; choose one of: {choices}")
    selected = PROFILES[profile]
    if selected is None:
        return sorted(registry_names)
    missing = [name for name in selected if name not in registry_names]
    if missing:
        raise ValueError(
            f"Factor profile {profile!r} references missing factors: {', '.join(missing)}"
        )
    return list(selected)
