"""Price-action-only Markov regime model.

A first-order Markov chain estimated from the market return path *alone* — no
factors, no fundamentals. The daily equal-weight market return is standardised by
its own trailing volatility and bucketed into ordered states (Crash/Down/Flat/
Up/Surge). Consecutive-day transitions give an empirical row-stochastic matrix
whose powers yield the most-likely forward state path and long-run (stationary)
distribution.

This is a *behavioural diagnostic* for the PM validating a run — "given only how
price has moved, what state are we in and what typically follows" — not a
forecast or a capital recommendation. It is fully deterministic on a pinned
panel, so it is safe to snapshot into a tracked contract document.

Design notes:
* Volatility is trailing and lagged one day (``vol.shift(1)``) so the state label
  for day *t* uses no information from day *t* onward — the chain is causal.
* Zero-count rows (a state never observed leaving) fall back to "stay" (identity)
  so the matrix is always a valid stochastic matrix.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Ordered state labels and the z-score cut points between them. Five states keep
# the transition matrix legible on a one-pager while still separating a tail
# "Crash"/"Surge" from an ordinary "Down"/"Up" day.
STATE_LABELS = ("Crash", "Down", "Flat", "Up", "Surge")
Z_EDGES = (-1.5, -0.5, 0.5, 1.5)


@dataclass(frozen=True)
class MarkovRegime:
    labels: tuple[str, ...]
    z_edges: tuple[float, ...]
    vol_win: int
    n_obs: int                     # transitions the matrix was estimated on
    counts: np.ndarray             # KxK integer transition counts
    transition: np.ndarray         # KxK row-stochastic matrix
    state_freq: np.ndarray         # unconditional state frequencies
    current_state: int
    horizon: int
    forecast: np.ndarray           # (horizon+1, K); row h = P(state | +h days)
    modal_path: tuple[int, ...]    # argmax state per step, h = 1..horizon
    stationary: np.ndarray         # long-run distribution
    persistence: float             # P(stay | current state)
    expected_dwell: float          # 1 / (1 - persistence), in trading days
    entropy_bits: float            # Shannon entropy of the current-state row

    @property
    def current_label(self) -> str:
        return self.labels[self.current_state]

    def modal_path_labels(self) -> list[str]:
        return [self.labels[s] for s in self.modal_path]


def classify_states(market_ret: pd.Series, *, vol_win: int = 63,
                    z_edges: tuple[float, ...] = Z_EDGES) -> pd.Series:
    """Vol-standardised, causally-lagged price-action state per day (0..K-1)."""
    ret = pd.Series(market_ret).astype(float)
    vol = ret.rolling(vol_win, min_periods=max(10, vol_win // 3)).std()
    z = ret / vol.shift(1).replace(0.0, np.nan)
    z = z.dropna()
    states = np.digitize(z.to_numpy(), z_edges)     # 0..len(edges)
    return pd.Series(states, index=z.index, dtype=int)


def _row_stochastic(counts: np.ndarray) -> np.ndarray:
    row_sums = counts.sum(axis=1, keepdims=True)
    trans = np.divide(counts, row_sums, out=np.zeros_like(counts, dtype=float),
                      where=row_sums > 0)
    # A never-exited state "stays" — keeps the matrix stochastic and honest
    # rather than inventing transitions we never saw.
    for i in range(trans.shape[0]):
        if row_sums[i, 0] == 0:
            trans[i, i] = 1.0
    return trans


def _stationary(trans: np.ndarray, *, iters: int = 2000,
                tol: float = 1e-12) -> np.ndarray:
    k = trans.shape[0]
    dist = np.full(k, 1.0 / k)
    for _ in range(iters):
        nxt = dist @ trans
        s = nxt.sum()
        if s > 0:
            nxt = nxt / s
        if np.abs(nxt - dist).max() < tol:
            return nxt
        dist = nxt
    return dist


def estimate_price_action_markov(market_ret: pd.Series, *, vol_win: int = 63,
                                 horizon: int = 5,
                                 z_edges: tuple[float, ...] = Z_EDGES,
                                 labels: tuple[str, ...] = STATE_LABELS
                                 ) -> MarkovRegime:
    """Fit the first-order price-action chain and project it forward."""
    k = len(labels)
    states = classify_states(market_ret, vol_win=vol_win, z_edges=z_edges)
    seq = states.to_numpy()

    counts = np.zeros((k, k), dtype=np.int64)
    for a, b in zip(seq[:-1], seq[1:]):
        counts[a, b] += 1
    n_obs = int(counts.sum())

    trans = _row_stochastic(counts)
    freq = np.bincount(seq, minlength=k).astype(float)
    freq = freq / freq.sum() if freq.sum() > 0 else freq
    current = int(seq[-1]) if len(seq) else k // 2

    forecast = np.zeros((horizon + 1, k))
    vec = np.zeros(k)
    vec[current] = 1.0
    forecast[0] = vec
    for h in range(1, horizon + 1):
        vec = vec @ trans
        forecast[h] = vec
    modal_path = tuple(int(forecast[h].argmax()) for h in range(1, horizon + 1))

    stationary = _stationary(trans)
    persistence = float(trans[current, current])
    expected_dwell = float("inf") if persistence >= 1.0 else 1.0 / (1.0 - persistence)

    row = trans[current]
    nz = row[row > 0]
    entropy = float(-(nz * np.log2(nz)).sum()) if nz.size else 0.0

    return MarkovRegime(
        labels=labels, z_edges=z_edges, vol_win=vol_win, n_obs=n_obs,
        counts=counts, transition=trans, state_freq=freq, current_state=current,
        horizon=horizon, forecast=forecast, modal_path=modal_path,
        stationary=stationary, persistence=persistence,
        expected_dwell=expected_dwell, entropy_bits=entropy,
    )
