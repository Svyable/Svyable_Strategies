"""Purged nonlinear cross-sectional ML sleeve.

The primary model is histogram gradient boosting with a deterministic ridge
fallback. Targets are cross-sectional forward-return ranks. Training windows
are purged by the forecast horizon and weighted toward recent observations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.panel import Panel, cs_zscore, forward_returns
from svyable.config import SvyableConfig
from svyable.ml_nonlinear import fit_cross_sectional_model, time_decay_weights


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

    predictions = np.full((T, N), np.nan, dtype=np.float32)
    model = None
    model_kind = ""
    horizon = cfg.ml_horizon

    for t in range(cfg.ml_train_win + horizon, T):
        if model is None or (t % cfg.ml_refit_every) == 0:
            start = t - cfg.ml_train_win - horizon
            stop = t - horizon
            X_train = array[start:stop].reshape(-1, F)
            y_train = target[start:stop].reshape(-1)
            weights = time_decay_weights(
                stop - start,
                N,
                cfg.ml_sample_half_life,
            )
            valid = np.isfinite(y_train) & np.isfinite(X_train).any(axis=1)
            valid_index = np.flatnonzero(valid)
            if len(valid_index) < 500:
                continue
            if len(valid_index) > cfg.ml_max_rows:
                valid_index = valid_index[-cfg.ml_max_rows:]
            model, model_kind = fit_cross_sectional_model(
                X_train[valid_index],
                y_train[valid_index],
                weights[valid_index],
                cfg,
            )

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
