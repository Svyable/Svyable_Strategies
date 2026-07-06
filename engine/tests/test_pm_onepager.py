"""PM one-pager renderer — structure, determinism, and traceability."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.providers import SyntheticProvider
from svyable.config import nasdaq_lo_config
from svyable.pipeline import run_pipeline
from svyable.markov_regime import estimate_price_action_markov
from svyable.pm_onepager import (render_pm_onepager, holdings_table,
                                 synthetic_ticker_aliases)

UNIVERSE_SEED = Path(__file__).resolve().parents[1] / "universe_nasdaq_seed.txt"


def test_synthetic_ticker_aliases_map_by_index():
    aliases = synthetic_ticker_aliases(["SYN000", "SYN032", "NOTSYN"], UNIVERSE_SEED)
    assert aliases["SYN000"] == "AAPL"        # first seed line
    assert aliases["SYN032"] == "INTC"        # index 32 in seed order
    assert "NOTSYN" not in aliases            # real symbols pass through untouched
    assert synthetic_ticker_aliases(["SYN000"], "/no/such/file.txt") == {}


def _run():
    panel = SyntheticProvider(n_assets=40, n_days=600, seed=3).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False,
                           seats_base=15, seats_min=10, seats_max=20)
    res = run_pipeline(panel, cfg, write_artifacts=False)
    return cfg, res, panel


ALIASES = {"SYN012": "PEP", "SYN032": "INTC", "SYN005": "GOOG"}


def _render(cfg, res, panel, symbol_labels=None):
    mk = estimate_price_action_markov(panel.market_ret, horizon=5)
    return render_pm_onepager(cfg, res, panel, weights_hash="deadbeef",
                              config_hash="cafef00d", provider_repr="P()",
                              config_repr="C()", markov=mk,
                              symbol_labels=symbol_labels)


def test_contains_all_sections():
    cfg, res, panel = _run()
    md = _render(cfg, res, panel)
    for header in [
        "# Svyable strategy run — PM one-pager",
        "## 1 · Provenance & reproducibility contract",
        "## 2 · Holdings (weights contract)",
        "## 3 · Risk posture",
        "## 4 · Regime stack",
        "## 5 · Price-action Markov regime",
        "## 6 · Sleeve allocation & live IC health",
        "## 7 · Factor stack",
        "## 8 · Construction & universe",
    ]:
        assert header in md, f"missing section: {header}"


def test_holdings_precede_analytics():
    # Book should sit near the top: holdings section before risk/regime/markov.
    cfg, res, panel = _run()
    md = _render(cfg, res, panel)
    assert md.index("## 2 · Holdings") < md.index("## 3 · Risk posture")
    assert md.index("## 2 · Holdings") < md.index("## 5 · Price-action Markov")


def test_ticker_aliases_render():
    cfg, res, panel = _run()
    md = _render(cfg, res, panel, symbol_labels=ALIASES)
    # Held synthetic symbols that are aliased must show the real ticker AND keep
    # the synthetic id for traceability.
    held = set(holdings_table(res)["symbol"])
    for syn, ticker in ALIASES.items():
        if syn in held:
            assert ticker in md and syn in md
    assert "| Rank | Ticker | Synthetic ID |" in md


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
