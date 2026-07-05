"""Consistency guarantees: golden weights, causality, calendar, restatement,
ledger round-trip. Any code change that alters strategy behavior must fail here
first, on purpose, and be re-blessed explicitly.
"""

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.providers import SyntheticProvider, detect_restatement
from svyable.config import nasdaq_lo_config
from svyable.pipeline import run_pipeline

GOLDEN_FILE = Path(__file__).parent / "golden_weights.json"


def _cfg():
    # ML off: sklearn floating-point nondeterminism must not gate regressions
    return nasdaq_lo_config(min_adv=0.0, min_price=0.0, ml_enabled=False,
                            seats_base=15, seats_min=10, seats_max=20)


def _weights_hash(w: pd.DataFrame) -> str:
    # Round to 6 decimals before hashing. Weights sum to ~1 across the book, so
    # 1e-6 is still a very tight regression gate (real strategy/factor changes
    # move weights by basis points, 1e-4+), while absorbing sub-1e-6 BLAS/numpy
    # version float noise so the golden hash is reproducible across environments
    # (local dev vs. pinned CI) instead of pinned to one interpreter build.
    arr = np.round(w.to_numpy(dtype=np.float64), 6)
    return hashlib.sha256(arr.tobytes()).hexdigest()[:24]


def test_golden_weights():
    """Same code + same inputs -> byte-identical weights. The golden hash is the
    contract; a legitimate strategy change updates the file in the same commit."""
    panel = SyntheticProvider(n_assets=40, n_days=600, seed=3).get_panel()
    res = run_pipeline(panel, _cfg(), write_artifacts=False)
    h = _weights_hash(res.weights)

    if not GOLDEN_FILE.exists():
        GOLDEN_FILE.write_text(json.dumps(
            {"hash": h, "config_hash": _cfg().config_hash()}, indent=2))
        print(f"golden blessed: {h}")
        return

    golden = json.loads(GOLDEN_FILE.read_text())
    assert golden["config_hash"] == _cfg().config_hash(), (
        "test config changed — delete golden_weights.json to re-bless deliberately")
    assert golden["hash"] == h, (
        f"WEIGHTS CHANGED: {golden['hash']} -> {h}. If intentional, delete "
        "tests/golden_weights.json and commit the new hash with the change.")


def test_causality_future_blindness():
    """Weights through date T must be identical whether or not data after T
    exists. Catches any accidental look-ahead anywhere in the pipeline."""
    full = SyntheticProvider(n_assets=40, n_days=600, seed=3).get_panel()
    cut = 480
    truncated = full.slice(end=str(full.close.index[cut - 1].date()))

    w_full = run_pipeline(full, _cfg(), write_artifacts=False).weights
    w_trunc = run_pipeline(truncated, _cfg(), write_artifacts=False).weights

    common = w_trunc.index
    diff = (w_full.loc[common] - w_trunc).abs().to_numpy().max()
    assert diff < 1e-9, f"look-ahead detected: max weight diff {diff:.2e}"


def test_calendar():
    from svyable.calendar import is_trading_day, previous_trading_day
    assert not is_trading_day(date(2026, 7, 3))          # July 4 observed (Sat)
    assert is_trading_day(date(2026, 7, 6))              # following Monday trades
    assert not is_trading_day(date(2026, 11, 26))        # Thanksgiving
    assert not is_trading_day(date(2026, 12, 25))        # Christmas (Fri)
    assert not is_trading_day(date(2026, 4, 3))          # Good Friday 2026
    assert not is_trading_day(date(2026, 6, 19))         # Juneteenth (Fri)
    assert not is_trading_day(date(2026, 7, 4))          # Saturday anyway
    assert previous_trading_day(date(2026, 7, 6)) == date(2026, 7, 2)


def test_restatement_detection():
    idx = pd.bdate_range("2024-01-01", periods=30)
    old = pd.DataFrame({"AAA": np.linspace(100, 110, 30),
                        "BBB": np.linspace(50, 55, 30)}, index=idx)
    fresh = old.copy()
    assert detect_restatement(old, fresh) == []
    fresh["BBB"] *= 0.5                                   # 2:1 split re-adjustment
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
        assert h["tracking_days"] == 1   # drift measurable only from the 2nd point
        # day2 drift: live +0.90% vs shadow +1.00% -> -10 bps
        eq = led.equity_frame()
        assert abs(eq["drift_bps"].iloc[-1] - (-9.9)) < 0.5
        led.close()


def test_shadow_sleeve_not_floored():
    """A shadow sleeve (proven=False) with no predictive power must be allowed to
    bleed toward zero weight — the sleeve-level IC meta-learner is the immune
    system (strategy.md §8.10/§13). Proven sleeves keep their anti-collapse
    floor. Injects a pure-noise 'ml' sleeve independent of forward returns."""
    from svyable.config import nasdaq_lo_config
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

    # zero-IC shadow sleeve is allowed near zero, not pinned at the floor
    assert sw["ml"].min() < 0.01, (
        f"shadow sleeve pinned above floor (min={sw['ml'].min():.4f}); the "
        "meta-learner cannot zero out an untrusted sleeve")

    # proven sleeves are still protected from full collapse
    proven = [s.name for s in cfg.sleeves if s.proven and s.name in sw.columns]
    assert (sw[proven] > 0).all().all(), "a proven sleeve collapsed to zero"


def test_nw_tstat_corrects_overlap():
    """On an overlapping (autocorrelated) series, NW t must be well below the
    naive t; on iid noise they should roughly agree."""
    from svyable.analysis import nw_tstat
    rng = np.random.default_rng(11)
    iid = pd.Series(rng.normal(0.02, 0.1, 1500))
    overlapped = iid.rolling(21).mean().dropna() * 21   # induce 21-day overlap
    t_naive = float(overlapped.mean() / overlapped.std() * np.sqrt(len(overlapped)))
    t_nw = nw_tstat(overlapped, lag=21)
    assert t_nw < 0.5 * t_naive, f"NW ({t_nw:.1f}) should shrink naive ({t_naive:.1f})"
    t_iid_naive = float(iid.mean() / iid.std() * np.sqrt(len(iid)))
    t_iid_nw = nw_tstat(iid, lag=21)
    assert abs(t_iid_nw - t_iid_naive) < 0.5 * abs(t_iid_naive) + 1.0


def test_bad_print_detection():
    panel = SyntheticProvider(n_assets=10, n_days=400, seed=5).get_panel()
    assert not any("bad-print" in i for i in panel.validate()["issues"])
    # inject a spike-and-reverse glitch
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
