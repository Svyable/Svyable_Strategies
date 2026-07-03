"""Purged nonlinear cross-sectional model used by the ML sleeve."""

from __future__ import annotations

import numpy as np

from svyable.config import SvyableConfig


def time_decay_weights(days: int, assets: int, half_life: int) -> np.ndarray:
    age = np.arange(days - 1, -1, -1, dtype=float)
    daily = np.exp(np.log(0.5) * age / max(1, half_life))
    return np.repeat(daily, assets)


def fit_cross_sectional_model(
    X: np.ndarray,
    y: np.ndarray,
    sample_weight: np.ndarray,
    cfg: SvyableConfig,
):
    from sklearn.linear_model import Ridge

    if cfg.ml_model == "hist_gbrt":
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor

            model = HistGradientBoostingRegressor(
                learning_rate=cfg.ml_learning_rate,
                max_iter=cfg.ml_max_iter,
                max_leaf_nodes=cfg.ml_max_leaf_nodes,
                l2_regularization=cfg.ml_l2_regularization,
                early_stopping=True,
                random_state=0,
            )
            model.fit(X, y, sample_weight=sample_weight)
            return model, "hist_gbrt"
        except (ImportError, ValueError):
            pass

    model = Ridge(alpha=cfg.ml_ridge_alpha)
    model.fit(np.nan_to_num(X), y, sample_weight=sample_weight)
    return model, "ridge"
