"""Small helpers for factor health review."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()].sort_index()
    return out.apply(pd.to_numeric, errors="coerce")


def factor_trend_alerts(
    ic_health: pd.DataFrame,
    *,
    short_window: int = 21,
    long_window: int = 126,
    min_history: int = 42,
) -> pd.DataFrame:
    frame = _numeric_frame(ic_health)
    if frame.empty:
        return pd.DataFrame(columns=["factor", "state", "latest_ic", "short_ic", "long_ic", "ic_delta", "slope", "history"])

    rows: list[dict] = []
    for name in frame.columns:
        series = frame[name].dropna()
        if len(series) < min_history:
            continue
        short_ic = float(series.tail(short_window).mean())
        long_ic = float(series.tail(long_window).mean())
        latest = float(series.iloc[-1])
        y = series.tail(long_window).to_numpy(dtype=float)
        x = np.arange(len(y), dtype=float)
        slope = float(np.polyfit(x, y, 1)[0]) if len(y) >= 3 else 0.0
        delta = short_ic - long_ic
        if latest > 0 and delta > 0.01 and slope > 0:
            state = "improving"
        elif latest < 0 or (delta < -0.015 and slope < 0):
            state = "deteriorating"
        elif delta < -0.0075 or slope < 0:
            state = "watch"
        else:
            state = "stable"
        rows.append({
            "factor": name,
            "state": state,
            "latest_ic": latest,
            "short_ic": short_ic,
            "long_ic": long_ic,
            "ic_delta": delta,
            "slope": slope,
            "history": int(len(series)),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    order = {"deteriorating": 0, "watch": 1, "stable": 2, "improving": 3}
    result["rank"] = result["state"].map(order).fillna(9)
    return result.sort_values(["rank", "ic_delta", "latest_ic"]).drop(columns=["rank"]).reset_index(drop=True)


def exposure_concentration(
    factor_exposures: pd.DataFrame,
    *,
    exposure_column: str = "exposure",
    top_n: int = 15,
) -> pd.DataFrame:
    if factor_exposures is None or factor_exposures.empty or exposure_column not in factor_exposures.columns:
        return pd.DataFrame(columns=["factor", "exposure", "abs_exposure", "share_of_abs_exposure", "state"])
    frame = factor_exposures.copy()
    frame[exposure_column] = pd.to_numeric(frame[exposure_column], errors="coerce")
    frame = frame.dropna(subset=[exposure_column])
    if frame.empty:
        return pd.DataFrame()
    frame["abs_exposure"] = frame[exposure_column].abs()
    total = float(frame["abs_exposure"].sum())
    frame["share_of_abs_exposure"] = frame["abs_exposure"] / (total + 1e-12)
    frame["state"] = np.where(
        frame["share_of_abs_exposure"] >= 0.20,
        "dominant",
        np.where(frame["share_of_abs_exposure"] >= 0.10, "large", "normal"),
    )
    cols = ["factor", exposure_column, "abs_exposure", "share_of_abs_exposure", "state"]
    return frame.sort_values("abs_exposure", ascending=False)[cols].head(top_n).reset_index(drop=True)


def factor_review_summary(trends: pd.DataFrame, concentration: pd.DataFrame) -> dict[str, int | str]:
    deteriorating = int((trends.get("state") == "deteriorating").sum()) if trends is not None and not trends.empty else 0
    watch = int((trends.get("state") == "watch").sum()) if trends is not None and not trends.empty else 0
    improving = int((trends.get("state") == "improving").sum()) if trends is not None and not trends.empty else 0
    dominant = int((concentration.get("state") == "dominant").sum()) if concentration is not None and not concentration.empty else 0
    if deteriorating or dominant:
        headline = "review required"
    elif watch:
        headline = "watchlist active"
    elif improving:
        headline = "improving"
    else:
        headline = "stable"
    return {"headline": headline, "deteriorating": deteriorating, "watch": watch, "improving": improving, "dominant": dominant}
