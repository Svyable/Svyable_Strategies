"""Matplotlib chart helpers for the Svyable analytics console.

Ported and adapted from the Q23 dashboard ``analytics/viz.py`` — the highest-value,
most robustly reusable visualizations, all driven purely by a daily return series
(or a weights-history frame) that Svyable already produces in ``pnl_diag.csv``.

Every helper returns a ``matplotlib.figure.Figure`` for ``st.pyplot``. Figures use a
self-contained dark panel style so they render consistently regardless of the active
Streamlit theme.
"""

from __future__ import annotations

import calendar
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

# Svyable palette — green for long/positive, red for short/risk, blue accents.
STRATEGY = "#2ecc71"
BENCHMARK = "#e74c3c"
ACCENT = "#3498db"
MUTED = "#95a5a6"
PANEL = "#0E1117"
_SERIES_COLORS = ["#2ecc71", "#3498db", "#f39c12", "#9b59b6", "#e74c3c", "#1abc9c"]


def setup_plot_style() -> None:
    """Apply the dark panel style shared by every analytics chart."""
    plt.style.use("seaborn-v0_8-darkgrid")
    plt.rcParams.update(
        {
            "figure.facecolor": PANEL,
            "axes.facecolor": "#262730",
            "axes.edgecolor": "#4A4A4A",
            "axes.labelcolor": "#FAFAFA",
            "text.color": "#FAFAFA",
            "xtick.color": "#FAFAFA",
            "ytick.color": "#FAFAFA",
            "grid.color": "#3A3A3A",
            "grid.alpha": 0.3,
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "lines.linewidth": 2,
        }
    )


def _coerce_time_index(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.index = pd.to_datetime(result.index, errors="coerce")
    return result[~result.index.isna()].sort_index()


def _safe_bound(values, default: float = 0.01) -> float:
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if not len(finite):
        return default
    bound = float(np.nanmax(np.abs(finite)))
    return bound or default


def cumulative_return_chart(
    returns: pd.Series,
    benchmark: pd.Series | None = None,
    title: str = "Cumulative Return",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    perf = (1.0 + returns).cumprod() - 1.0
    ax.plot(perf.index, perf.values, label="Strategy", linewidth=2.5, color=STRATEGY)
    if benchmark is not None and not benchmark.empty:
        bench = (1.0 + benchmark).cumprod() - 1.0
        ax.plot(bench.index, bench.values, label="Benchmark", linewidth=2, color=BENCHMARK, alpha=0.8)

    ax.axhline(y=0, color="white", linestyle="--", alpha=0.3, linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_ylabel("Cumulative Return")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.legend(loc="upper left", framealpha=0.9)
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def drawdown_chart(
    returns: pd.Series,
    title: str = "Drawdown",
    figsize: tuple[int, int] = (12, 4),
) -> Figure:
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    perf = (1.0 + returns).cumprod()
    dd = perf / perf.cummax() - 1.0
    ax.fill_between(dd.index, dd.values, 0, alpha=0.7, color=BENCHMARK, label="Drawdown")
    ax.axhline(y=0, color="white", linestyle="--", alpha=0.3, linewidth=1)

    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_ylabel("Drawdown")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.legend(loc="lower left", framealpha=0.9)
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def rolling_metrics_chart(
    metrics: pd.DataFrame,
    columns: Sequence[str],
    title: str = "Rolling Metrics",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    for i, column in enumerate(columns):
        if column in metrics.columns:
            ax.plot(
                metrics.index,
                metrics[column].values,
                label=column.replace("_", " ").title(),
                linewidth=2,
                color=_SERIES_COLORS[i % len(_SERIES_COLORS)],
            )
    ax.axhline(y=0, color="white", linestyle="--", alpha=0.3, linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.legend(loc="best", framealpha=0.9)
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def return_distribution_chart(
    returns: pd.Series,
    title: str = "Daily Return Distribution",
    figsize: tuple[int, int] = (12, 4),
) -> Figure:
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    values = returns.dropna().values
    ax.hist(values, bins=60, color=ACCENT, alpha=0.75, edgecolor=PANEL)
    mean = float(np.mean(values)) if len(values) else 0.0
    p05, p95 = (np.quantile(values, [0.05, 0.95]) if len(values) else (0.0, 0.0))
    ax.axvline(mean, color=STRATEGY, linestyle="-", linewidth=2, label=f"Mean {mean:.2%}")
    ax.axvline(p05, color=BENCHMARK, linestyle="--", linewidth=1.5, label=f"5% {p05:.2%}")
    ax.axvline(p95, color=STRATEGY, linestyle="--", linewidth=1.5, alpha=0.6, label=f"95% {p95:.2%}")

    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_xlabel("Daily Return")
    ax.set_ylabel("Frequency")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.1%}"))
    ax.legend(loc="upper left", framealpha=0.9, fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def monthly_returns_heatmap(
    returns: pd.Series,
    title: str = "Monthly Returns",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    """Year x month table of compounded returns, coloured red→green."""
    setup_plot_style()

    monthly = (1.0 + returns).resample("ME").prod() - 1.0
    frame = monthly.to_frame("ret")
    frame["year"] = frame.index.year
    frame["month"] = frame.index.month
    grid = frame.pivot_table(index="year", columns="month", values="ret", aggfunc="sum")
    grid = grid.reindex(columns=range(1, 13))

    fig, ax = plt.subplots(figsize=figsize)
    bound = _safe_bound(grid.values)
    im = ax.imshow(grid.values, aspect="auto", cmap="RdYlGn", vmin=-bound, vmax=bound)

    ax.set_xticks(range(12))
    ax.set_xticklabels([calendar.month_abbr[m] for m in range(1, 13)], fontsize=9)
    ax.set_yticks(range(len(grid.index)))
    ax.set_yticklabels(grid.index, fontsize=9)

    for r in range(grid.shape[0]):
        for c in range(grid.shape[1]):
            value = grid.values[r, c]
            if np.isfinite(value):
                ax.text(c, r, f"{value:.1%}", ha="center", va="center", fontsize=7, color="#111111")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="Monthly Return")
    fig.tight_layout()
    return fig


def calendar_heatmap(
    returns: pd.Series,
    title: str = "Daily Returns Calendar",
    figsize: tuple[int, int] = (16, 9),
) -> Figure:
    """Per-year month×day calendar of daily returns, coloured red→green."""
    setup_plot_style()

    frame = returns.to_frame("ret")
    frame["year"] = frame.index.year
    frame["month"] = frame.index.month
    frame["day"] = frame.index.day

    years = sorted(frame["year"].unique())
    n_cols = min(3, len(years)) or 1
    n_rows = (len(years) + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize, squeeze=False)
    flat_axes = axes.flatten()

    bound = float(returns.abs().quantile(0.95)) or 0.01
    last = 0
    im = None
    for i, year in enumerate(years):
        ax = flat_axes[i]
        year_data = frame[frame["year"] == year]
        cal = np.full((12, 31), np.nan)
        for row in year_data.itertuples(index=False):
            cal[int(row.month) - 1, int(row.day) - 1] = row.ret
        im = ax.imshow(cal, aspect="auto", cmap="RdYlGn", vmin=-bound, vmax=bound, interpolation="nearest")
        ax.set_yticks(range(12))
        ax.set_yticklabels([calendar.month_abbr[m + 1] for m in range(12)], fontsize=7)
        ax.set_xticks(range(0, 31, 5))
        ax.set_xticklabels(range(1, 32, 5), fontsize=7)
        ax.set_title(str(year), fontsize=10, fontweight="bold")
        last = i

    for j in range(last + 1, len(flat_axes)):
        flat_axes[j].axis("off")

    if im is not None:
        fig.colorbar(im, ax=axes, orientation="horizontal", fraction=0.02, pad=0.05, label="Daily Return")
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.995)
    return fig


def weekday_month_heatmap(
    returns: pd.Series,
    title: str = "Average return by month and weekday",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    """Month × weekday temporal seasonality heatmap, red for loss, green for gain."""
    setup_plot_style()
    frame = returns.dropna().to_frame("ret")
    frame["month"] = frame.index.month
    frame["weekday"] = frame.index.weekday
    grid = frame.pivot_table(index="month", columns="weekday", values="ret", aggfunc="mean")
    grid = grid.reindex(index=range(1, 13), columns=range(5))

    fig, ax = plt.subplots(figsize=figsize)
    bound = _safe_bound(grid.values)
    im = ax.imshow(grid.values, aspect="auto", cmap="RdYlGn", vmin=-bound, vmax=bound)
    ax.set_xticks(range(5))
    ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri"])
    ax.set_yticks(range(12))
    ax.set_yticklabels([calendar.month_abbr[m] for m in range(1, 13)])
    for r in range(grid.shape[0]):
        for c in range(grid.shape[1]):
            value = grid.values[r, c]
            if np.isfinite(value):
                ax.text(c, r, f"{value * 100:.2f}", ha="center", va="center", fontsize=7, color="#111111")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="Average daily return")
    fig.tight_layout()
    return fig


def rolling_hit_rate_chart(
    returns: pd.Series,
    window: int = 63,
    title: str = "Rolling hit rate",
    figsize: tuple[int, int] = (12, 4),
) -> Figure:
    """Rolling share of positive daily returns, green above 50%, red below."""
    setup_plot_style()
    hit = (returns > 0).astype(float).rolling(window, min_periods=max(10, window // 3)).mean().dropna()
    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(hit.index, hit.values, color=ACCENT, linewidth=2.0, label=f"{window}d hit rate")
    ax.fill_between(hit.index, hit.values, 0.5, where=hit.values >= 0.5, color=STRATEGY, alpha=0.25)
    ax.fill_between(hit.index, hit.values, 0.5, where=hit.values < 0.5, color=BENCHMARK, alpha=0.25)
    ax.axhline(0.5, color="white", linestyle="--", alpha=0.4, linewidth=1, label="50%")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_ylabel("Hit rate")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.legend(loc="best", framealpha=0.9)
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def candidate_ranking_chart(
    board: pd.DataFrame,
    value_col: str = "utility_bps",
    label_col: str = "candidate_id",
    eligible_col: str = "eligible",
    title: str = "Candidate ranking",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    """Horizontal bars of a per-candidate score, green when eligible, grey when not."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    frame = board[[label_col, value_col]].copy()
    if eligible_col in board.columns:
        frame[eligible_col] = board[eligible_col].astype(bool).values
    else:
        frame[eligible_col] = True
    frame = frame.dropna(subset=[value_col]).sort_values(value_col)

    colors = [STRATEGY if ok else MUTED for ok in frame[eligible_col]]
    ax.barh(frame[label_col].astype(str), frame[value_col].astype(float), color=colors)
    ax.axvline(x=0, color="white", linestyle="--", alpha=0.4, linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_xlabel(value_col.replace("_", " ").title())
    for i, value in enumerate(frame[value_col].astype(float)):
        ax.text(value, i, f" {value:.1f}", va="center", ha="left" if value >= 0 else "right", fontsize=8)
    ax.grid(True, axis="x", alpha=0.2)
    fig.tight_layout()
    return fig


def signed_bar_chart(
    values: pd.Series,
    title: str = "",
    xlabel: str = "",
    figsize: tuple[int, int] = (11, 6),
) -> Figure:
    """Horizontal bars coloured green (positive) / red (negative), sorted ascending."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    series = values.dropna().sort_values()
    colors = [STRATEGY if v >= 0 else BENCHMARK for v in series.values]
    ax.barh(series.index.astype(str), series.values, color=colors)
    ax.axvline(x=0, color="white", linestyle="--", alpha=0.4, linewidth=1)
    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    if xlabel:
        ax.set_xlabel(xlabel)
    ax.grid(True, axis="x", alpha=0.2)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    return fig


def long_short_exposure_chart(
    weights_history: pd.DataFrame,
    title: str = "Long / short exposure tape",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    """Time series of long gross, short gross, net exposure, and gross exposure."""
    setup_plot_style()
    frame = _coerce_time_index(weights_history).astype(float)
    long_gross = frame.clip(lower=0.0).sum(axis=1)
    short_gross = frame.clip(upper=0.0).abs().sum(axis=1)
    net = frame.sum(axis=1)
    gross = frame.abs().sum(axis=1)

    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(long_gross.index, long_gross.values, color=STRATEGY, linewidth=2.4, label="Long gross")
    ax.plot(short_gross.index, short_gross.values, color=BENCHMARK, linewidth=2.4, label="Short gross")
    ax.plot(net.index, net.values, color=ACCENT, linewidth=2.0, label="Net exposure")
    ax.plot(gross.index, gross.values, color=MUTED, linewidth=1.6, alpha=0.75, label="Gross exposure")
    ax.axhline(0, color="white", linestyle="--", alpha=0.35, linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_ylabel("Portfolio weight")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.legend(loc="best", framealpha=0.9, ncol=2)
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def factor_weight_heatmap(
    weights: pd.DataFrame,
    *,
    top: int = 30,
    title: str = "Factor weights over time",
    figsize: tuple[int, int] = (13, 8),
) -> Figure:
    """Factor × date heatmap of signed factor allocations, red negative / green positive."""
    setup_plot_style()
    frame = _coerce_time_index(weights).astype(float).dropna(how="all")
    if frame.empty:
        frame = pd.DataFrame([[0.0]], columns=["no_data"], index=[pd.Timestamp.today()])
    score = frame.abs().tail(252).mean().sort_values(ascending=False)
    keep = score.head(min(top, len(score))).index
    frame = frame[keep].tail(252)

    fig, ax = plt.subplots(figsize=figsize)
    values = frame.values.T
    bound = _safe_bound(values)
    im = ax.imshow(values, aspect="auto", cmap="RdYlGn", vmin=-bound, vmax=bound, interpolation="nearest")
    ax.set_yticks(range(len(frame.columns)))
    ax.set_yticklabels(frame.columns, fontsize=7)
    step = max(1, len(frame.index) // 12)
    ticks = list(range(0, len(frame.index), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(frame.index[i].date()) for i in ticks], rotation=45, ha="right", fontsize=7)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="Factor weight")
    fig.tight_layout()
    return fig


def ic_health_heatmap(
    ic_health: pd.DataFrame,
    title: str = "Smoothed IC health over time",
    figsize: tuple[int, int] = (13, 6),
) -> Figure:
    """Sleeve/factor IC health heatmap through time."""
    setup_plot_style()
    frame = _coerce_time_index(ic_health).astype(float).tail(252)
    if frame.empty:
        frame = pd.DataFrame([[0.0]], columns=["no_data"], index=[pd.Timestamp.today()])
    fig, ax = plt.subplots(figsize=figsize)
    values = frame.values.T
    bound = _safe_bound(values)
    im = ax.imshow(values, aspect="auto", cmap="RdYlGn", vmin=-bound, vmax=bound, interpolation="nearest")
    ax.set_yticks(range(len(frame.columns)))
    ax.set_yticklabels(frame.columns, fontsize=8)
    step = max(1, len(frame.index) // 12)
    ticks = list(range(0, len(frame.index), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(frame.index[i].date()) for i in ticks], rotation=45, ha="right", fontsize=7)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="Smoothed IC")
    fig.tight_layout()
    return fig


def sleeve_trust_area_chart(
    sleeve_weights: pd.DataFrame,
    title: str = "Sleeve trust allocation over time",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    """Stacked area of sleeve trust weights through time."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    frame = _coerce_time_index(sleeve_weights)
    ax.stackplot(
        frame.index,
        *[frame[col].values for col in frame.columns],
        labels=list(frame.columns),
        colors=_SERIES_COLORS[: len(frame.columns)],
        alpha=0.85,
    )
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_ylabel("Trust weight")
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left", framealpha=0.9, fontsize=8, ncol=len(frame.columns))
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def alpha_vs_cost_scatter(
    board: pd.DataFrame,
    title: str = "Expected alpha vs. turnover cost",
    figsize: tuple[int, int] = (10, 5),
) -> Figure:
    """Scatter of gross expected alpha against one-way turnover, sized by utility."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    frame = board.copy()
    x = frame.get("one_way_turnover", pd.Series(dtype=float)).astype(float)
    y = frame.get("expected_alpha_bps", pd.Series(dtype=float)).astype(float)
    eligible = frame.get("eligible", pd.Series(True, index=frame.index)).astype(bool)
    colors = [STRATEGY if ok else MUTED for ok in eligible]

    ax.scatter(x, y, s=90, c=colors, edgecolor=PANEL, alpha=0.9, zorder=3)
    for _, row in frame.iterrows():
        ax.annotate(
            str(row.get("candidate_id", "")),
            (float(row.get("one_way_turnover", 0.0)), float(row.get("expected_alpha_bps", 0.0))),
            fontsize=7,
            xytext=(4, 4),
            textcoords="offset points",
        )
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_xlabel("One-way turnover")
    ax.set_ylabel("Expected alpha (bps)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def multi_equity_chart(
    curves: dict[str, pd.Series],
    highlight: str | None = None,
    title: str = "Candidate cumulative returns",
    figsize: tuple[int, int] = (12, 6),
) -> Figure:
    """Overlay cumulative-return curves for several candidate strategies."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    for i, (name, returns) in enumerate(sorted(curves.items())):
        if returns is None or returns.empty:
            continue
        perf = (1.0 + returns).cumprod() - 1.0
        is_focus = name == highlight
        ax.plot(
            perf.index,
            perf.values,
            label=name,
            linewidth=3 if is_focus else 1.6,
            color=STRATEGY if is_focus else _SERIES_COLORS[i % len(_SERIES_COLORS)],
            alpha=1.0 if is_focus else 0.75,
            zorder=5 if is_focus else 2,
        )
    ax.axhline(y=0, color="white", linestyle="--", alpha=0.3, linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_ylabel("Cumulative Return")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.legend(loc="upper left", framealpha=0.9, fontsize=8, ncol=2)
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def correlation_heatmap(
    corr: pd.DataFrame,
    title: str = "Strategy return correlation",
    figsize: tuple[int, int] = (9, 7),
) -> Figure:
    """Annotated correlation matrix, blue (diversifying) → red (redundant)."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1.0, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index, fontsize=8)
    for i in range(corr.shape[0]):
        for j in range(corr.shape[1]):
            value = corr.values[i, j]
            ax.text(
                j,
                i,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=7,
                color="#111111" if abs(value) < 0.6 else "#FAFAFA",
            )
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03, label="Correlation")
    fig.tight_layout()
    return fig


def risk_return_scatter(
    metrics: pd.DataFrame,
    highlight: str | None = None,
    title: str = "Risk / return map",
    figsize: tuple[int, int] = (10, 6),
) -> Figure:
    """Annualized volatility vs. return, marker size scaled by Sharpe."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    x = metrics["ann_vol"].astype(float)
    y = metrics["ann_return"].astype(float)
    sharpe = metrics["sharpe"].astype(float) if "sharpe" in metrics.columns else pd.Series(1.0, index=metrics.index)
    sizes = (sharpe.clip(lower=0.0) * 120 + 60).fillna(60)
    colors = [STRATEGY if name == highlight else ACCENT for name in metrics.index]

    ax.scatter(x, y, s=sizes, c=colors, edgecolor=PANEL, alpha=0.85, zorder=3)
    for name in metrics.index:
        ax.annotate(
            str(name),
            (float(metrics.loc[name, "ann_vol"]), float(metrics.loc[name, "ann_return"])),
            fontsize=7,
            xytext=(5, 4),
            textcoords="offset points",
        )
    ax.axhline(y=0, color="white", linestyle="--", alpha=0.3, linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    ax.set_xlabel("Annualized volatility")
    ax.set_ylabel("Annualized return")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def position_drift_chart(
    table: pd.DataFrame,
    top: int = 25,
    figsize: tuple[int, int] = (11, 6),
) -> Figure:
    """Diverging bars of the largest target-vs-actual weight drifts (percentage points)."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)
    subset = table.head(top).iloc[::-1]
    colors = [BENCHMARK if v > 0 else ACCENT for v in subset["drift"]]
    ax.barh(subset.index.astype(str), subset["drift"].values * 100, color=colors)
    ax.axvline(x=0, color="white", linestyle="--", alpha=0.4, linewidth=1)
    ax.set_title("Position drift — book vs. strategy target", fontsize=14, fontweight="bold", pad=16)
    ax.set_xlabel("Drift (percentage points of gross)")
    ax.grid(True, axis="x", alpha=0.2)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    return fig


def position_heatmap(
    matrix: pd.DataFrame,
    title: str = "Position stack — weight by name over time",
    figsize: tuple[int, int] = (13, 8),
) -> Figure:
    """Asset × date heatmap of portfolio weights (the Q23 'position stack')."""
    setup_plot_style()
    fig, ax = plt.subplots(figsize=figsize)

    values = matrix.values.T  # assets on y, dates on x
    bound = _safe_bound(values)
    im = ax.imshow(values, aspect="auto", cmap="RdYlGn", vmin=-bound, vmax=bound, interpolation="nearest")

    ax.set_yticks(range(len(matrix.columns)))
    ax.set_yticklabels(matrix.columns, fontsize=7)
    step = max(1, len(matrix.index) // 12)
    ticks = range(0, len(matrix.index), step)
    ax.set_xticks(list(ticks))
    ax.set_xticklabels([str(matrix.index[i])[:10] for i in ticks], rotation=45, ha="right", fontsize=7)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=16)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="Weight")
    fig.tight_layout()
    return fig


def exposure_turnover_chart(
    diag: pd.DataFrame,
    title: str = "Exposure & Turnover",
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    setup_plot_style()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, sharex=True)

    if "gross_exposure" in diag.columns:
        ax1.plot(diag.index, diag["gross_exposure"].values, label="Gross", linewidth=2, color=ACCENT)
    if "net_exposure" in diag.columns:
        ax1.plot(diag.index, diag["net_exposure"].values, label="Net", linewidth=2, color=STRATEGY)
    ax1.set_title("Exposure", fontsize=11, fontweight="bold")
    ax1.legend(loc="best", framealpha=0.9)
    ax1.grid(True, alpha=0.2)

    if "turnover" in diag.columns:
        ax2.bar(diag.index, diag["turnover"].values, color=BENCHMARK, alpha=0.7, width=1)
    ax2.set_title("Turnover", fontsize=11, fontweight="bold")
    ax2.grid(True, alpha=0.2)

    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    return fig
