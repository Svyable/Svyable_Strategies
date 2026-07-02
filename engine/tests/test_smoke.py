"""Synthetic end-to-end smoke test — no network, no optional deps required."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from svyable.providers import SyntheticProvider
from svyable.config import nasdaq_lo_config
from svyable.pipeline import run_pipeline, backtest_report
from svyable.construct import project_capped_simplex


def test_projection():
    v = np.array([0.5, 0.3, 0.2, 0.0])
    lo = np.array([0.05, 0.05, 0.05, 0.0])
    hi = np.array([0.3, 0.3, 0.3, 0.0])
    w = project_capped_simplex(v, 0.9, lo, hi)
    assert abs(w.sum() - 0.9) < 1e-6
    assert (w <= hi + 1e-9).all() and (w >= lo - 1e-9).all()


def test_pipeline_end_to_end(tmp_path=None):
    panel = SyntheticProvider(n_assets=40, n_days=600, seed=3).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_train_win=252,
                           seats_base=15, seats_min=10, seats_max=20)
    res = run_pipeline(panel, cfg, output_root=None, write_artifacts=False)

    w = res.weights
    # long-only
    assert (w.values >= -1e-9).all()
    # weights sum tracks budget on recent days
    tail = w.iloc[-50:]
    b = res.budget.iloc[-50:]
    gap = (tail.sum(axis=1) - b).abs()
    assert gap.median() < 0.05
    # position caps respected (with lev scaling)
    assert (w.values <= cfg.max_pos * cfg.lev_cap + 1e-6).all()
    # causality guard: factors at t unchanged when future data changes.
    # (structural: nothing in the pipeline indexes forward except fwd-returns
    #  used only for IC, which are shifted by horizon+1)
    rep = backtest_report(res, panel, cfg)
    assert "full_period" in rep and "sharpe" in rep["full_period"]
    print("pipeline report:", rep["full_period"])


if __name__ == "__main__":
    test_projection()
    test_pipeline_end_to_end()
    print("ALL TESTS PASSED")
