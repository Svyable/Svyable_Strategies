"""Regression test for persisted daily execution inputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.config import nasdaq_lo_config
from svyable.pipeline import run_pipeline
from svyable.providers import SyntheticProvider


def test_pipeline_persists_execution_inputs():
    with TemporaryDirectory() as tmp:
        panel = SyntheticProvider(n_assets=20, n_days=320).get_panel()
        cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False)
        result = run_pipeline(panel, cfg, output_root=tmp, write_artifacts=True)
        path = result.output_dir / "execution_inputs.csv"
        assert path.exists()
        frame = pd.read_csv(path, index_col=0)
        assert {"price", "adv_dollars", "is_liquid"} <= set(frame.columns)
        meta = json.loads((result.output_dir / "meta.json").read_text())
        assert meta["execution_inputs"]["adv_window"] == cfg.adv_win
        assert meta["execution_inputs"]["adv_participation_cap"] == cfg.adv_participation_cap


if __name__ == "__main__":
    test_pipeline_persists_execution_inputs()
    print("EXECUTION ARTIFACT TEST PASSED")
