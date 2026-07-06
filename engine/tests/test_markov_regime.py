"""Price-action Markov regime model — determinism + stochastic-matrix invariants."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.markov_regime import (STATE_LABELS, classify_states,
                                    estimate_price_action_markov)


def _market_series(seed=3, n=600):
    from svyable.providers import SyntheticProvider
    return SyntheticProvider(n_assets=40, n_days=n, seed=seed).get_panel().market_ret


def test_classify_states_are_causal_and_in_range():
    ret = _market_series()
    states = classify_states(ret, vol_win=63)
    assert states.min() >= 0 and states.max() <= len(STATE_LABELS) - 1
    # Causality: truncating the tail must not change earlier state labels, because
    # the classifier only uses trailing (lagged) volatility.
    cut = ret.index[400]
    trunc = classify_states(ret.loc[:cut], vol_win=63)
    common = trunc.index
    assert (states.loc[common] == trunc).all()


def test_transition_matrix_is_row_stochastic():
    mk = estimate_price_action_markov(_market_series(), horizon=5)
    rows = mk.transition.sum(axis=1)
    assert np.allclose(rows, 1.0), rows
    assert (mk.transition >= 0).all()
    assert mk.counts.sum() == mk.n_obs


def test_forecast_rows_are_distributions_and_modal_path_tracks_argmax():
    mk = estimate_price_action_markov(_market_series(), horizon=5)
    assert mk.forecast.shape == (6, len(STATE_LABELS))
    assert np.allclose(mk.forecast.sum(axis=1), 1.0)
    # h=0 is a one-hot on the current state.
    assert mk.forecast[0].argmax() == mk.current_state
    assert mk.forecast[0, mk.current_state] == 1.0
    assert len(mk.modal_path) == 5
    for h in range(1, 6):
        assert mk.modal_path[h - 1] == int(mk.forecast[h].argmax())


def test_stationary_is_left_eigenvector():
    mk = estimate_price_action_markov(_market_series(), horizon=3)
    assert abs(mk.stationary.sum() - 1.0) < 1e-9
    # pi P == pi (fixed point of the chain).
    assert np.allclose(mk.stationary @ mk.transition, mk.stationary, atol=1e-6)


def test_deterministic_across_calls():
    a = estimate_price_action_markov(_market_series(), horizon=5)
    b = estimate_price_action_markov(_market_series(), horizon=5)
    assert a.current_state == b.current_state
    assert np.array_equal(a.counts, b.counts)
    assert a.modal_path == b.modal_path


def test_persistence_and_dwell_consistent():
    mk = estimate_price_action_markov(_market_series(), horizon=5)
    assert mk.persistence == mk.transition[mk.current_state, mk.current_state]
    if mk.persistence < 1.0:
        assert abs(mk.expected_dwell - 1.0 / (1.0 - mk.persistence)) < 1e-9
    assert mk.entropy_bits >= 0.0


def test_absorbing_state_stays():
    # A monotonic up-drift never leaves the top state; its row must be identity-like
    # (self-transition), never all-zero.
    ret = pd.Series(np.full(400, 0.02))
    mk = estimate_price_action_markov(ret, horizon=4)
    assert np.allclose(mk.transition.sum(axis=1), 1.0)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("MARKOV REGIME TESTS PASSED")
