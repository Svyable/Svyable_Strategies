"""ML cross-sectional sleeve (strategy.md §13, Gu-Kelly-Xiu style, home-scale).

Ridge regression on the stacked factor matrix -> cross-sectionally demeaned
forward returns. Refit every `ml_refit_every` days on a trailing window with a
purge gap of the forward horizon (no train/predict overlap). Predictions are
z-scored per day and enter the ensemble as one more sleeve — the sleeve-level
IC meta-learner decides how much to trust it.

Degrades to None (sleeve skipped) if scikit-learn is not installed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from svyable.panel import EPS, Panel, cs_zscore, forward_returns
from svyable.config import SvyableConfig


def ml_sleeve_score(factors: dict[str, pd.DataFrame], panel: Panel,
                    cfg: SvyableConfig) -> pd.DataFrame | None:
    if not cfg.ml_enabled:
        return None
    try:
        from sklearn.linear_model import Ridge
    except ImportError:
        return None

    names = sorted(factors)
    idx, cols = panel.close.index, panel.close.columns
    T, N, F = len(idx), len(cols), len(names)
    if T < cfg.ml_train_win + cfg.ml_horizon + cfg.ml_refit_every:
        return None

    A = np.stack([np.nan_to_num(factors[n].to_numpy(dtype=np.float32)) for n in names],
                 axis=2)                                   # (T, N, F)
    fwd = forward_returns(panel.close, cfg.ml_horizon)
    y = fwd.sub(fwd.mean(axis=1), axis=0).to_numpy(dtype=np.float32)  # demeaned target

    preds = np.full((T, N), np.nan, dtype=np.float32)
    model = None
    h = cfg.ml_horizon

    for t in range(cfg.ml_train_win + h, T):
        if model is None or (t % cfg.ml_refit_every) == 0:
            # train on [t - train_win - h, t - h): every target fully realized by t
            t0, t1 = t - cfg.ml_train_win - h, t - h
            Xtr = A[t0:t1].reshape(-1, F)
            ytr = y[t0:t1].reshape(-1)
            ok = np.isfinite(ytr) & np.isfinite(Xtr).all(axis=1)
            if ok.sum() < 500:
                continue
            model = Ridge(alpha=cfg.ml_ridge_alpha)
            model.fit(Xtr[ok], ytr[ok])
        if model is not None:
            preds[t] = model.predict(A[t])

    score = pd.DataFrame(preds, index=idx, columns=cols)
    return cs_zscore(score).fillna(0.0)
