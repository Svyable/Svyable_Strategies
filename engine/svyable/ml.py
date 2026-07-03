"""Purged nonlinear cross-sectional ML sleeve.

The primary model is histogram gradient boosting with a deterministic ridge
fallback. Targets are cross-sectional forward-return ranks. Training windows are
purged by the forecast horizon and weighted toward recent observations.

Efficiency (all numerically inert):
  * Predictions are memoized on a content digest of the factor panel, the close
    panel, and the ML hyperparameters — so strategies/backtests that share the
    same factor set and ML config reuse the result instead of recomputing it.
  * The independent walk-forward refits are planned up front (no look-ahead) and
    fitted once per anchor, optionally in parallel (``ml_n_jobs``).

The causal contract is unchanged: the model covering day ``t`` is trained only on
data strictly older than ``t - horizon``, and each day is predicted with the most
recent such model — identical, byte for byte, to the sequential implementation.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

import numpy as np
import pandas as pd

from svyable.panel import Panel, cs_zscore, forward_returns
from svyable.config import SvyableConfig
from svyable.ml_nonlinear import fit_cross_sectional_model, time_decay_weights

# Bounded in-process memo: identical inputs -> identical prediction.
_PREDICTION_CACHE: "OrderedDict[str, pd.DataFrame | None]" = OrderedDict()
_CACHE_MAXSIZE = 8

# Hyperparameters that change the prediction (ml_cache / ml_n_jobs do not).
_ML_KEY_FIELDS = (
    "ml_model", "ml_refit_every", "ml_train_win", "ml_horizon",
    "ml_ridge_alpha", "ml_max_iter", "ml_max_leaf_nodes", "ml_learning_rate",
    "ml_l2_regularization", "ml_sample_half_life", "ml_max_rows",
)

_MIN_TRAIN_ROWS = 500


def _digest(
    array: np.ndarray,
    target: np.ndarray,
    index: pd.Index,
    columns: pd.Index,
    cfg: SvyableConfig,
) -> str:
    """Content hash over full inputs — collisions would silently return wrong
    weights, so this hashes the whole factor/target payload, not a fingerprint."""
    h = hashlib.blake2b(digest_size=16)
    for name, arr in (("f", array), ("y", target)):
        h.update(name.encode())
        h.update(str(arr.shape).encode())
        h.update(np.ascontiguousarray(arr).tobytes())
    h.update(index.asi8.tobytes())
    h.update("\x00".join(map(str, columns)).encode())
    for field in _ML_KEY_FIELDS:
        h.update(f"{field}={getattr(cfg, field)}".encode())
    return h.hexdigest()


def ml_sleeve_score(
    factors: dict[str, pd.DataFrame],
    panel: Panel,
    cfg: SvyableConfig,
) -> pd.DataFrame | None:
    if not cfg.ml_enabled:
        return None
    try:
        import sklearn  # noqa: F401
    except ImportError:
        return None

    names = sorted(factors)
    index, columns = panel.close.index, panel.close.columns
    T, N, F = len(index), len(columns), len(names)
    if T < cfg.ml_train_win + cfg.ml_horizon + cfg.ml_refit_every:
        return None

    array = np.stack(
        [factors[name].to_numpy(dtype=np.float32) for name in names],
        axis=2,
    )
    forward = forward_returns(panel.close, cfg.ml_horizon)
    target = forward.rank(axis=1, pct=True).sub(0.5).to_numpy(dtype=np.float32)

    key = _digest(array, target, index, columns, cfg) if cfg.ml_cache else None
    if key is not None and key in _PREDICTION_CACHE:
        _PREDICTION_CACHE.move_to_end(key)
        hit = _PREDICTION_CACHE[key]
        return hit.copy() if hit is not None else None

    result = _walk_forward(array, target, index, columns, T, N, F, cfg)

    if key is not None:
        _PREDICTION_CACHE[key] = result
        _PREDICTION_CACHE.move_to_end(key)
        while len(_PREDICTION_CACHE) > _CACHE_MAXSIZE:
            _PREDICTION_CACHE.popitem(last=False)

    return result.copy() if result is not None else None


def _walk_forward(
    array: np.ndarray,
    target: np.ndarray,
    index: pd.Index,
    columns: pd.Index,
    T: int,
    N: int,
    F: int,
    cfg: SvyableConfig,
) -> pd.DataFrame:
    horizon = cfg.ml_horizon
    train_win = cfg.ml_train_win
    refit_every = cfg.ml_refit_every
    start = train_win + horizon

    # Rows eligible for training: finite target and at least one finite feature.
    valid_mask = np.isfinite(target) & np.isfinite(array).any(axis=2)  # (T, N)
    # The training window length is constant, so the decay weights are too.
    weights_full = time_decay_weights(train_win, N, cfg.ml_sample_half_life)

    # Plan the refit schedule exactly as the sequential loop would, without
    # fitting: a fit point is the first eligible day and every ``refit_every``
    # step; skipped (undersized) points leave the previous model in force.
    anchors: list[tuple[int, int]] = []          # (row_start, row_stop)
    assignment = np.full(T, -1, dtype=np.int64)   # day -> anchor index (-1 = none)
    have_model = False
    current = -1
    for t in range(start, T):
        if (not have_model) or (t % refit_every == 0):
            s0, s1 = t - train_win - horizon, t - horizon
            if int(valid_mask[s0:s1].sum()) < _MIN_TRAIN_ROWS:
                continue
            anchors.append((s0, s1))
            current = len(anchors) - 1
            have_model = True
        if not have_model:
            continue
        assignment[t] = current

    def _fit(s0: int, s1: int):
        X = array[s0:s1].reshape(-1, F)
        y = target[s0:s1].reshape(-1)
        rows = np.flatnonzero(valid_mask[s0:s1].reshape(-1))
        if len(rows) > cfg.ml_max_rows:
            rows = rows[-cfg.ml_max_rows:]
        return fit_cross_sectional_model(X[rows], y[rows], weights_full[rows], cfg)

    if anchors and cfg.ml_n_jobs != 1 and len(anchors) > 1:
        from joblib import Parallel, delayed

        fitted = Parallel(n_jobs=cfg.ml_n_jobs)(
            delayed(_fit)(s0, s1) for s0, s1 in anchors
        )
    else:
        fitted = [_fit(s0, s1) for s0, s1 in anchors]

    predictions = np.full((T, N), np.nan, dtype=np.float32)
    for t in range(start, T):
        a = assignment[t]
        if a < 0:
            continue
        model, model_kind = fitted[a]
        if model is None:
            continue
        X_now = array[t]
        live = np.isfinite(X_now).any(axis=1)
        if not live.any():
            continue
        if model_kind == "ridge":
            predictions[t, live] = model.predict(np.nan_to_num(X_now[live]))
        else:
            predictions[t, live] = model.predict(X_now[live])

    return cs_zscore(pd.DataFrame(predictions, index=index, columns=columns))
