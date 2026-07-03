"""Regression tests for execution inputs and factor-governance artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.config import nasdaq_lo_config
from svyable.factor_library import compute_all, factor_metadata
from svyable.pipeline import run_pipeline
from svyable.providers import SyntheticProvider
from svyable.weighting import rank_ic


def test_pipeline_persists_execution_inputs_and_factor_health():
    with TemporaryDirectory() as tmp:
        panel = SyntheticProvider(n_assets=20, n_days=360).get_panel()
        cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False)
        result = run_pipeline(panel, cfg, output_root=tmp, write_artifacts=True)

        execution_path = result.output_dir / "execution_inputs.csv"
        assert execution_path.exists()
        execution = pd.read_csv(execution_path, index_col=0)
        assert {"price", "adv_dollars", "is_liquid"} <= set(execution.columns)

        catalog_path = result.output_dir / "factor_catalog.csv"
        sleeve_health_path = result.output_dir / "sleeve_health.csv"
        momentum_health_path = result.output_dir / "factor_health_momentum.csv"
        assert catalog_path.exists()
        assert sleeve_health_path.exists()
        assert momentum_health_path.exists()

        catalog = pd.read_csv(catalog_path, index_col=0)
        assert catalog.loc["inv_idio", "stage"] == "proven"
        assert catalog.loc["fip_momentum", "stage"] == "proven"
        assert catalog.loc["vpin_inv", "stage"] == "shadow"

        health = pd.read_csv(momentum_health_path)
        required = {
            "factor",
            "horizon",
            "mean_ic",
            "ic_vol",
            "ic_ir",
            "hit_rate",
            "observations",
            "coverage",
            "weight",
            "stage",
        }
        assert required <= set(health.columns)

        meta = json.loads((result.output_dir / "meta.json").read_text())
        assert meta["execution_inputs"]["adv_window"] == cfg.adv_win
        assert meta["execution_inputs"]["adv_participation_cap"] == cfg.adv_participation_cap
        assert meta["factor_library"]["proven"] > 0
        assert meta["factor_library"]["shadow"] > 0
        assert meta["factor_library"]["missing_values_preserved_for_ic"] is True


def test_factor_library_preserves_missing_values_for_ic():
    panel = SyntheticProvider(n_assets=20, n_days=300).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False)
    factors = compute_all(panel, cfg, names=["mom_12_1", "inv_idio"])
    assert factors["mom_12_1"].iloc[:250].isna().any().any()
    catalog = factor_metadata(factors)
    assert set(catalog.index) == {"mom_12_1", "inv_idio"}


def test_rank_ic_requires_pairwise_eligible_breadth():
    index = pd.date_range("2026-01-01", periods=2)
    columns = list("ABCDE")
    factor = pd.DataFrame(
        [[1, 2, 3, np.nan, np.nan], [1, 2, 3, 4, 5]],
        index=index,
        columns=columns,
    )
    forward = pd.DataFrame(
        [[1, 2, 3, 4, 5], [5, 4, 3, 2, 1]],
        index=index,
        columns=columns,
    )
    eligible = pd.DataFrame(True, index=index, columns=columns)
    result = rank_ic(factor, forward, eligible=eligible, min_obs=4)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == -1.0


if __name__ == "__main__":
    test_pipeline_persists_execution_inputs_and_factor_health()
    test_factor_library_preserves_missing_values_for_ic()
    test_rank_ic_requires_pairwise_eligible_breadth()
    print("EXECUTION AND FACTOR ARTIFACT TESTS PASSED")
