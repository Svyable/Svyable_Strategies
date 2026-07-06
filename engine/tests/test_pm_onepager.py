"""PM one-pager renderer — structure, determinism, and traceability."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.providers import SyntheticProvider
from svyable.config import nasdaq_lo_config
from svyable.pipeline import run_pipeline
from svyable.markov_regime import estimate_price_action_markov
from svyable.pm_onepager import render_pm_onepager, holdings_table


def _run():
    panel = SyntheticProvider(n_assets=40, n_days=600, seed=3).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False,
                           seats_base=15, seats_min=10, seats_max=20)
    res = run_pipeline(panel, cfg, write_artifacts=False)
    return cfg, res, panel


def _render(cfg, res, panel):
    mk = estimate_price_action_markov(panel.market_ret, horizon=5)
    return render_pm_onepager(cfg, res, panel, weights_hash="deadbeef",
                              config_hash="cafef00d", provider_repr="P()",
                              config_repr="C()", markov=mk)


def test_contains_all_sections():
    cfg, res, panel = _run()
    md = _render(cfg, res, panel)
    for header in [
        "# Svyable strategy run — PM one-pager",
        "## 1 · Provenance & reproducibility contract",
        "## 2 · Risk posture",
        "## 3 · Regime stack",
        "## 4 · Price-action Markov regime",
        "## 5 · Sleeve allocation & live IC health",
        "## 6 · Factor stack",
        "## 7 · Construction & universe",
        "## 8 · Holdings (weights contract)",
    ]:
        assert header in md, f"missing section: {header}"


def test_traces_real_run_values():
    cfg, res, panel = _run()
    md = _render(cfg, res, panel)
    # hashes echoed
    assert "deadbeef" in md and "cafef00d" in md
    # every held symbol appears in the holdings table
    for sym in holdings_table(res)["symbol"]:
        assert sym in md
    # sleeves and the current markov state are named
    assert "momentum" in md and "defensive" in md
    mk = estimate_price_action_markov(panel.market_ret, horizon=5)
    assert mk.current_label in md
    # factor counts are rendered (proven/shadow language present)
    assert "proven" in md and "shadow" in md


def test_render_is_deterministic():
    cfg, res, panel = _run()
    assert _render(cfg, res, panel) == _render(cfg, res, panel)
    # no wall-clock leakage
    md = _render(cfg, res, panel)
    assert "202" not in md.split("as-of")[0]  # no stray timestamp before as-of line


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("PM ONEPAGER TESTS PASSED")
