"""Shared, pure data-access and cleaning helpers for the dashboard views.

Single source of truth for the small transforms every view needs — coercing CSV
frames to clean, datetime-indexed numeric data and resolving per-candidate run
artifacts. Keeping them here (rather than re-implemented per page) is the DRY
backbone the rendering modules build on; every function is pure and unit-tested.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_HELD_EPS = 20  # default minimum return-history length worth charting


def clean_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    """Return ``frame`` datetime-indexed, unparseable dates dropped, sorted ascending."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.index = pd.to_datetime(out.index, errors="coerce")
    return out[~out.index.isna()].sort_index()


def numeric_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    """:func:`clean_timeseries` plus numeric coercion with zero-filled gaps."""
    out = clean_timeseries(frame)
    if out.empty:
        return out
    return out.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def clean_returns(frame: pd.DataFrame, column: str = "net_ret") -> pd.Series:
    """Extract a clean, datetime-indexed return series from a diagnostics frame."""
    if frame is None or frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(frame[column], errors="coerce")
    series.index = pd.to_datetime(series.index, errors="coerce")
    return series[~series.index.isna()].sort_index().dropna()


def resolve_run_artifact(
    output_root: str | Path, row: pd.Series, filename: str
) -> Path | None:
    """Locate a candidate run artifact for a board ``row``.

    Prefers the board's ``output_dir`` pointer (tried as-is and relative to the
    output root and its parent, so path style does not matter), then falls back
    to the newest ``candidate_<strategy_id>`` run. Returns ``None`` if missing.
    """
    root = Path(output_root)
    raw = str(row.get("output_dir", "") or "").strip()
    for base in (Path(raw), root.parent / raw, root / raw) if raw else ():
        probe = base / filename
        if probe.exists():
            return probe
    strategy_id = str(row.get("strategy_id", "") or row.get("candidate_id", ""))
    matches = sorted(root.glob(f"candidate_{strategy_id}/*/{filename}"))
    return matches[-1] if matches else None


def load_candidate_returns(
    output_root: str | Path, board: pd.DataFrame, min_days: int = _HELD_EPS
) -> dict[str, pd.Series]:
    """Shadow-NAV return series per board candidate, keyed by ``candidate_id``."""
    curves: dict[str, pd.Series] = {}
    for _, row in board.iterrows():
        path = resolve_run_artifact(output_root, row, "pnl_diag.csv")
        if path is None:
            continue
        series = clean_returns(pd.read_csv(path, index_col=0))
        if len(series) >= min_days:
            curves[str(row.get("candidate_id", ""))] = series
    return curves


def load_candidate_weights(
    output_root: str | Path, board: pd.DataFrame
) -> dict[str, pd.Series]:
    """Latest target-weight book per board candidate, keyed by ``candidate_id``."""
    books: dict[str, pd.Series] = {}
    for _, row in board.iterrows():
        path = resolve_run_artifact(output_root, row, "weights_today.csv")
        if path is None:
            continue
        frame = pd.read_csv(path, index_col=0)
        if frame.empty:
            continue
        column = "weight" if "weight" in frame.columns else frame.columns[0]
        series = pd.to_numeric(frame[column], errors="coerce").dropna()
        series.index = series.index.astype(str)
        if not series.empty:
            books[str(row.get("candidate_id", ""))] = series
    return books


def board_row_for_candidate(
    board: pd.DataFrame, candidate_id: str
) -> pd.Series | None:
    """Return the board row for ``candidate_id`` (``None`` when absent)."""
    if board is None or board.empty or "candidate_id" not in board.columns:
        return None
    matches = board[board["candidate_id"].astype(str) == str(candidate_id)]
    return matches.iloc[0] if not matches.empty else None


def load_candidate_timeseries(
    output_root: str | Path,
    board: pd.DataFrame,
    candidate_id: str,
    filename: str,
    *,
    numeric: bool = False,
) -> pd.DataFrame:
    """Load one datetime-indexed temporal artifact for a single board candidate.

    Resolves the candidate's newest run directory (via the board's ``output_dir``
    pointer, falling back to the ``candidate_<strategy_id>`` glob) and returns the
    named CSV as a clean, date-sorted frame. This is the shared backbone for
    every per-candidate temporal view — ``weights_history.csv`` (weight by name
    over time), ``pnl_diag.csv`` (returns/turnover/exposure), ``sleeve_weights``,
    ``ic_health``, and ``regime`` — so no view re-implements artifact resolution.
    Returns an empty frame when the candidate or file is missing.
    """
    row = board_row_for_candidate(board, candidate_id)
    if row is None:
        return pd.DataFrame()
    path = resolve_run_artifact(output_root, row, filename)
    if path is None:
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, index_col=0)
    except (OSError, ValueError, pd.errors.ParserError):
        return pd.DataFrame()
    return numeric_timeseries(frame) if numeric else clean_timeseries(frame)
