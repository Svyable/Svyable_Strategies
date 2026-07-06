"""Golden regression contract helpers.

The CI golden is a reproducibility fixture, not a claim that the strategy is the
best live-capital choice. Keeping the contract in one small JSON document makes
it obvious which strategy/config is pinned and gives the Streamlit GUI a safe way
to propose or change the golden candidate deliberately.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from svyable.config import SvyableConfig, nasdaq_lo_config
from svyable.providers import SyntheticProvider
from svyable.strategy_registry import get_strategy, registry_frame

DEFAULT_PROVIDER = {"kind": "synthetic", "n_assets": 40, "n_days": 600, "seed": 3}
DEFAULT_FIXTURE_OVERRIDES = {
    "min_adv": 0.0,
    "min_price": 0.0,
    "ml_enabled": False,
    "seats_base": 15,
    "seats_min": 10,
    "seats_max": 20,
}
DEFAULT_CONTRACT: dict[str, Any] = {
    "contract_version": 1,
    "golden_id": "base_nasdaq_lo",
    "kind": "base_config",
    "strategy_id": "svyable_nasdaq_lo",
    "label": "Base Nasdaq LO deterministic fixture",
    "reason": (
        "Default CI behavior contract: stable, ML-off, synthetic, and small enough "
        "to make every behavioral change explicit. This is not a live-capital ranking."
    ),
    "provider": DEFAULT_PROVIDER,
    "fixture_overrides": DEFAULT_FIXTURE_OVERRIDES,
}


def default_contract_path() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "golden_contract.json"


def load_golden_contract(path: str | Path | None = None) -> dict[str, Any]:
    contract_path = Path(path) if path is not None else default_contract_path()
    if not contract_path.exists():
        return dict(DEFAULT_CONTRACT)
    payload = json.loads(contract_path.read_text())
    merged = dict(DEFAULT_CONTRACT)
    merged.update(payload)
    merged["provider"] = {**DEFAULT_PROVIDER, **dict(payload.get("provider", {}))}
    merged["fixture_overrides"] = {
        **DEFAULT_FIXTURE_OVERRIDES,
        **dict(payload.get("fixture_overrides", {})),
    }
    return merged


def save_golden_contract(contract: dict[str, Any], path: str | Path | None = None) -> Path:
    contract_path = Path(path) if path is not None else default_contract_path()
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    return contract_path


def provider_from_contract(contract: dict[str, Any]) -> SyntheticProvider:
    provider = dict(contract.get("provider") or DEFAULT_PROVIDER)
    if provider.get("kind") != "synthetic":
        raise ValueError("golden CI contract currently supports only the synthetic provider")
    return SyntheticProvider(
        n_assets=int(provider.get("n_assets", 40)),
        n_days=int(provider.get("n_days", 600)),
        seed=int(provider.get("seed", 3)),
    )


def provider_repr(contract: dict[str, Any]) -> str:
    provider = dict(contract.get("provider") or DEFAULT_PROVIDER)
    if provider.get("kind") != "synthetic":
        return str(provider)
    return (
        "SyntheticProvider("
        f"n_assets={int(provider.get('n_assets', 40))}, "
        f"n_days={int(provider.get('n_days', 600))}, "
        f"seed={int(provider.get('seed', 3))})"
    )


def config_from_contract(contract: dict[str, Any]) -> tuple[SvyableConfig, tuple[str, ...] | None]:
    overrides = dict(contract.get("fixture_overrides") or {})
    kind = str(contract.get("kind", "base_config"))
    if kind == "base_config":
        return nasdaq_lo_config(**overrides), None
    if kind == "registered_strategy":
        spec = get_strategy(str(contract["strategy_id"]))
        cfg = spec.build_config()
        if overrides:
            cfg = replace(cfg, **overrides)
        return cfg, tuple(spec.factor_names)
    raise ValueError(f"unknown golden contract kind: {kind}")


def config_repr(contract: dict[str, Any], cfg: SvyableConfig | None = None) -> str:
    cfg = cfg or config_from_contract(contract)[0]
    overrides = dict(contract.get("fixture_overrides") or {})
    joined = ", ".join(f"{key}={value!r}" for key, value in sorted(overrides.items()))
    return f"{contract.get('label', cfg.strategy_id)}({joined})"


def build_golden_fixture(contract: dict[str, Any]):
    provider = provider_from_contract(contract)
    panel = provider.get_panel()
    cfg, factor_names = config_from_contract(contract)
    return panel, cfg, factor_names


def base_contract(reason: str | None = None) -> dict[str, Any]:
    payload = dict(DEFAULT_CONTRACT)
    payload["provider"] = dict(DEFAULT_PROVIDER)
    payload["fixture_overrides"] = dict(DEFAULT_FIXTURE_OVERRIDES)
    if reason:
        payload["reason"] = reason
    return payload


def registered_strategy_contract(strategy_id: str, reason: str | None = None) -> dict[str, Any]:
    spec = get_strategy(strategy_id)
    overrides = {
        "min_adv": 0.0,
        "min_price": 0.0,
    }
    return {
        "contract_version": 1,
        "golden_id": f"registered_{spec.strategy_id}",
        "kind": "registered_strategy",
        "strategy_id": spec.strategy_id,
        "label": spec.display_name,
        "reason": reason or (
            "Deliberately selected from the strategy roster as the CI golden behavior contract. "
            "Re-bless golden_weights.json and golden_weights_human.md in the same commit."
        ),
        "provider": dict(DEFAULT_PROVIDER),
        "fixture_overrides": overrides,
    }


def golden_option_frame():
    rows = [
        {
            "candidate_id": "base_nasdaq_lo",
            "name": DEFAULT_CONTRACT["label"],
            "kind": "base_config",
            "ml_enabled": False,
            "role": "stable CI default",
            "determinism_note": "recommended baseline: ML off and historically stable",
        }
    ]
    registry = registry_frame().reset_index()
    for row in registry.to_dict(orient="records"):
        ml_enabled = bool(row.get("ml_enabled", False))
        rows.append(
            {
                "candidate_id": str(row["strategy_id"]),
                "name": row.get("name"),
                "kind": "registered_strategy",
                "ml_enabled": ml_enabled,
                "role": row.get("pitch_role"),
                "determinism_note": (
                    "ML strategy: useful to test, but exact hash may be more fragile"
                    if ml_enabled
                    else "deterministic non-ML roster candidate"
                ),
            }
        )
    try:
        import pandas as pd

        return pd.DataFrame(rows)
    except Exception:  # pragma: no cover - pandas always exists in engine runtime
        return rows
