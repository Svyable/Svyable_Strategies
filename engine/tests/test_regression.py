"""Consistency guarantees: golden weights, causality, calendar, restatement,
ledger round-trip. Any code change that alters strategy behavior must fail here
first, on purpose, and be re-blessed explicitly.
"""

import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.providers import SyntheticProvider, detect_restatement
from svyable.config import nasdaq_lo_config
from svyable.golden_contract import (
    build_golden_fixture,
    config_repr,
    load_golden_contract,
    provider_repr,
)
from svyable.pipeline import run_pipeline
from svyable.markov_regime import estimate_price_action_markov
from svyable.pm_onepager import render_pm_onepager, synthetic_ticker_aliases

UNIVERSE_SEED = Path(__file__).resolve().parents[1] / "universe_nasdaq_seed.txt"

GOLDEN_FILE = Path(__file__).parent / "golden_weights.json"
GOLDEN_CONTRACT_FILE = Path(__file__).parent / "golden_contract.json"
GOLDEN_HUMAN_FILE = Path(__file__).parent / "golden_weights_human.md"
GOLDEN_CSV_FILE = Path(__file__).parent / "golden_weights.csv"


def _golden_fixture():
    """Shared, explicit CI fixture for the golden behavior contract."""
    contract = load_golden_contract(GOLDEN_CONTRACT_FILE)
    panel, cfg, factor_names = build_golden_fixture(contract)
    return contract, panel, cfg, factor_names


def _weights_hash(w: pd.DataFrame) -> str:
    arr = np.round(w.to_numpy(dtype=np.float64), 6)
    return hashlib.sha256(arr.tobytes()).hexdigest()[:24]


def _golden_weights_table(res) -> pd.DataFrame:
    last = res.weights.index[-1]
    latest = res.weights.loc[last].dropna()
    latest = latest[latest > 0].sort_values(ascending=False)
    table = latest.rename("weight").reset_index().rename(columns={"index": "symbol"})
    table.insert(0, "rank", range(1, len(table) + 1))
    table["weight"] = table["weight"].astype(float).round(8)
    table["weight_pct"] = (table["weight"] * 100.0).round(4)
    return table[["rank", "symbol", "weight", "weight_pct"]]


def _write_golden_snapshot(contract, cfg, res, panel, *, weights_hash: str, config_hash: str) -> None:
    _golden_weights_table(res).to_csv(GOLDEN_CSV_FILE, index=False)
    markov = estimate_price_action_markov(panel.market_ret, horizon=5)
    aliases = synthetic_ticker_aliases(res.weights.columns, UNIVERSE_SEED)
    md = render_pm_onepager(
        cfg,
        res,
        panel,
        weights_hash=weights_hash,
        config_hash=config_hash,
        provider_repr=provider_repr(contract),
        config_repr=config_repr(contract, cfg),
        markov=markov,
        symbol_labels=aliases,
    )
    GOLDEN_HUMAN_FILE.write_text(md)


def test_golden_weights():
    """Same code + same explicit fixture -> identical weights."""
    contract, panel, cfg, factor_names = _golden_fixture()
    res = run_pipeline(panel, cfg, write_artifacts=False, factor_names=factor_names)
    h = _weights_hash(res.weights)
    config_hash = cfg.config_hash()
    _write_golden_snapshot(contract, cfg, res, panel, weights_hash=h, config_hash=config_hash)

    if not GOLDEN_FILE.exists():
        GOLDEN_FILE.write_text(json.dumps(
            {"hash": h, "config_hash": config_hash, "golden_id": contract.get("golden_id")},
            indent=2,
        ))
        print(f"golden blessed: {h}")
        return

    golden = json.loads(GOLDEN_FILE.read_text())
    assert golden["config_hash"] == config_hash, (
        "test config changed — update golden_contract.json or re-bless golden_weights.json deliberately")
    if "golden_id" in golden:
        assert golden["golden_id"] == contract.get("golden_id"), (
            "golden contract changed — update golden_weights.json deliberately")

    if not os.environ.get("CI"):
        print(f"golden hash enforced in CI only (local={h}, golden={golden['hash']})")
        print(f"golden snapshot: {GOLDEN_HUMAN_FILE}")
        return
    assert golden["hash"] == h, (
        f"WEIGHTS CHANGED: {golden['hash']} -> {h}. Inspect "
        f"{GOLDEN_HUMAN_FILE.name} / {GOLDEN_CSV_FILE.name}; if intentional, "
        "commit the new hash and generated snapshot contract with the change.")


def test_causality_future_blindness():
    """Weights through date T must be identical whether or not data after T exists."""
    full = SyntheticProvider(n_assets=40, n_days=600, seed=3).get_panel()
    cut = 480
    truncated = full.slice(end=str(full.close.index[cut - 1].date()))

    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False,
                           seats_base=15, seats_min=10, seats_max=20)
    w_full = run_pipeline(full, cfg, write_artifacts=False).weights
    w_trunc = run_pipeline(truncated, cfg, write_artifacts=False).weights

    common = w_trunc.index
    diff = (w_full.loc[common] - w_trunc).abs().to_numpy().max()
    assert diff < 1e-9, f"look-ahead detected: max weight diff {diff:.2e}"


def test_calendar():
    from svyable.calendar import is_trading_day, previous_trading_day
    assert not is_trading_day(date(2026, 7, 3))
    assert is_trading_day(date(2026, 7, 6))
    assert not is_trading_day(date(2026, 11, 26))
    assert not is_trading_day(date(2026, 12, 25))
    assert not is_trading_day(date(2026, 4, 3))
    assert not is_trading_day(date(2026, 6, 19))
    assert not is_trading_day(date(2026, 7, 4))
    assert previous_trading_day(date(2026, 7, 6)) == date(2026, 7, 2)


def test_restatement_detection():
    idx = pd.bdate_range("2024-01-01", periods=30)
    old = pd.DataFrame({"AAA": np.linspace(100, 110, 30),
                        "BBB": np.linspace(50, 55, 30)}, index=idx)
    fresh = old.copy()
    assert detect_restatement(old, fresh) == []
    fresh["BBB"] *= 0.5
    assert detect_restatement(old, fresh) == ["BBB"]


def test_ledger_roundtrip(tmp_path=None):
    import tempfile
    from svyable.ledger import Ledger
    with tempfile.TemporaryDirectory() as td:
        led = Ledger(Path(td) / "ledger.db")
        rid = led.record_run(kind="daily", strategy="test", status="ok",
                             metrics={"sharpe": 1.0})
        led.record_orders(rid, "paper", True,
                          [{"symbol": "AAPL", "side": "buy", "qty": 10,
                            "est_price": 200.0, "est_notional": 2000.0,
                            "reason": "rebalance"}], [])
        led.record_equity("2026-07-01", shadow_nav=1.00, paper_equity=100_000)
        led.record_equity("2026-07-02", shadow_nav=1.01, paper_equity=100_900)
        led.record_event("warning", "test", "hello")
        h = led.health()
        assert h["warnings_7d"] == 1
        assert h["tracking_days"] == 1
        eq = led.equity_frame()
        assert abs(eq["drift_bps"].iloc[-1] - (-9.9)) < 0.5
        led.close()


def test_shadow_sleeve_not_floored():
    from svyable.sleeves import build_ensemble

    panel = SyntheticProvider(n_assets=40, n_days=700, seed=3).get_panel()
    cfg = nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False,
                           seats_base=15, seats_min=10, seats_max=20)

    rng = np.random.default_rng(7)
    noise = pd.DataFrame(rng.standard_normal(panel.close.shape),
                         index=panel.close.index, columns=panel.close.columns)

    ens = build_ensemble(panel, cfg, extra_sleeve_scores={"ml": noise})
    sw = ens.sleeve_weights
    assert "ml" in sw.columns
    assert sw["ml"].min() < 0.01, (
        f"shadow sleeve pinned above floor (min={sw['ml'].min():.4f}); the "
        "meta-learner cannot zero out an untrusted sleeve")

    proven = [s.name for s in cfg.sleeves if s.proven and s.name in sw.columns]
    assert (sw[proven] > 0).all().all(), "a proven sleeve collapsed to zero"


def test_nw_tstat_corrects_overlap():
    from svyable.analysis import nw_tstat
    rng = np.random.default_rng(11)
    iid = pd.Series(rng.normal(0.02, 0.1, 1500))
    overlapped = iid.rolling(21).mean().dropna() * 21
    t_naive = float(overlapped.mean() / overlapped.std() * np.sqrt(len(overlapped)))
    t_nw = nw_tstat(overlapped, lag=21)
    assert t_nw < 0.5 * t_naive, f"NW ({t_nw:.1f}) should shrink naive ({t_naive:.1f})"
    t_iid_naive = float(iid.mean() / iid.std() * np.sqrt(len(iid)))
    t_iid_nw = nw_tstat(iid, lag=21)
    assert abs(t_iid_nw - t_iid_naive) < 0.5 * abs(t_iid_naive) + 1.0


def test_bad_print_detection():
    panel = SyntheticProvider(n_assets=10, n_days=400, seed=5).get_panel()
    assert not any("bad-print" in i for i in panel.validate()["issues"])
    c = panel.close.copy()
    c.iloc[200, 3] *= 1.9
    from svyable.panel import Panel
    bad = Panel(open=panel.open, high=panel.high.where(panel.high > c, c),
                low=panel.low, close=c, volume=panel.volume)
    assert any("bad-print" in i for i in bad.validate()["issues"])


if __name__ == "__main__":
    test_golden_weights()
    test_causality_future_blindness()
    test_calendar()
    test_restatement_detection()
    test_ledger_roundtrip()
    test_shadow_sleeve_not_floored()
    test_nw_tstat_corrects_overlap()
    test_bad_print_detection()
    print("ALL REGRESSION TESTS PASSED")
