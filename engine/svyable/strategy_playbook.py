"""Daily strategy playbook cards.

A candidate board already materializes every strategy's weights and diagnostics.
This module turns those persisted artifacts into PM-friendly markdown cards so a
human can flip through the roster like a playbook before choosing today's book.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_frame(path: Path, *, index_col: int | str | None = 0) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, index_col=index_col)
    except Exception:
        return pd.DataFrame()


def _f(value: object, nd: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if not np.isfinite(number) else f"{number:.{nd}f}"


def _pct(value: object, nd: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if not np.isfinite(number) else f"{number * 100:.{nd}f}%"


def _bps(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if not np.isfinite(number) else f"{number:.2f} bps"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def weights_hash(frame: pd.DataFrame | pd.Series) -> str:
    """Short deterministic hash for a displayed weight vector/history."""
    if isinstance(frame, pd.Series):
        array = frame.astype(float).sort_index().to_numpy(dtype=np.float64)
    else:
        array = frame.astype(float).to_numpy(dtype=np.float64)
    return hashlib.sha256(np.round(array, 6).tobytes()).hexdigest()[:24]


def _candidate_dict(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, pd.Series):
        return row.to_dict()
    return dict(row)


def _hold_utility(board: pd.DataFrame | None) -> float | None:
    if board is None or board.empty or "candidate_id" not in board.columns:
        return None
    hold = board[board["candidate_id"].astype(str) == "hold_current"]
    if hold.empty:
        return None
    try:
        return float(hold.iloc[0].get("utility_bps"))
    except (TypeError, ValueError):
        return None


def _weights_table(output_dir: Path) -> pd.DataFrame:
    weights = _read_frame(output_dir / "weights_today.csv")
    if weights.empty:
        return weights
    column = "weight" if "weight" in weights.columns else weights.columns[0]
    out = weights[[column]].rename(columns={column: "weight"}).copy()
    out.index = out.index.astype(str)
    out = out[out["weight"].astype(float).abs() > 1e-10]
    out = out.sort_values("weight", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out["weight_pct"] = (out["weight"].astype(float) * 100.0).round(4)
    return out.reset_index().rename(columns={"index": "symbol"})


def _dominant_sleeve(output_dir: Path) -> tuple[str | None, pd.Series]:
    sleeves = _read_frame(output_dir / "sleeve_weights.csv")
    if sleeves.empty:
        return None, pd.Series(dtype=float)
    latest = sleeves.ffill().iloc[-1].dropna().astype(float)
    if latest.empty:
        return None, latest
    return str(latest.idxmax()), latest.sort_values(ascending=False)


def _top_factors(output_dir: Path, sleeve: str | None, top_n: int = 8) -> list[dict[str, Any]]:
    if not sleeve:
        return []
    weights = _read_frame(output_dir / f"factor_weights_{sleeve}.csv")
    catalog = _read_frame(output_dir / "factor_catalog.csv")
    if weights.empty:
        return []
    latest = weights.ffill().iloc[-1].dropna().astype(float)
    top = latest.reindex(latest.abs().sort_values(ascending=False).index).head(top_n)
    rows: list[dict[str, Any]] = []
    for name, weight in top.items():
        meta = catalog.loc[name].to_dict() if name in catalog.index else {}
        rows.append(
            {
                "factor": str(name),
                "weight": float(weight),
                "stage": str(meta.get("stage", "")),
                "sleeve": str(meta.get("sleeve", sleeve)),
                "description": str(meta.get("description") or meta.get("lineage") or ""),
            }
        )
    return rows


def _play_call(row: dict[str, Any]) -> str:
    if str(row.get("candidate_id")) == "hold_current":
        return "HOLD CURRENT BOOK"
    if _truthy(row.get("eligible")):
        return "RUN CANDIDATE"
    return "DO NOT RUN — BLOCKED"


def render_candidate_playbook(
    row: pd.Series | dict[str, Any],
    *,
    board: pd.DataFrame | None = None,
    board_dir: str | Path | None = None,
) -> str:
    """Render one PM playbook card for a candidate-board row."""
    item = _candidate_dict(row)
    candidate_id = str(item.get("candidate_id", "unknown"))
    name = str(item.get("name") or candidate_id)
    output_dir = Path(str(item.get("output_dir") or ""))
    meta = _read_json(output_dir / "meta.json") if str(output_dir) not in {"", "."} else {}
    holdings = _weights_table(output_dir) if meta else pd.DataFrame()
    dom_sleeve, sleeves = _dominant_sleeve(output_dir) if meta else (None, pd.Series(dtype=float))
    factors = _top_factors(output_dir, dom_sleeve)
    hold_util = _hold_utility(board)
    try:
        edge = float(item.get("utility_bps")) - hold_util if hold_util is not None else None
    except (TypeError, ValueError):
        edge = None
    config = meta.get("config") or {}
    data = meta.get("data") or {}
    regime = meta.get("regime") or {}
    perf = meta.get("perf_1y_net") or {}
    weights_digest = weights_hash(holdings.set_index("symbol")["weight"]) if not holdings.empty else "n/a"

    lines = [
        f"# Playbook card — {name}",
        "",
        "> Daily review card for choosing one strategy from the roster. This is a decision aid, not a live-capital recommendation.",
        "",
        "## 1 · Call sheet",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Play call | **{_play_call(item)}** |",
        f"| Candidate ID | `{candidate_id}` |",
        f"| Strategy ID | `{item.get('strategy_id', '—')}` |",
        f"| Family | {item.get('family', '—')} |",
        f"| Action | {item.get('action', '—')} |",
        f"| Eligible | {'yes' if _truthy(item.get('eligible')) else 'NO'} |",
        f"| Utility | {_bps(item.get('utility_bps'))} |",
        f"| Net expected alpha | {_bps(item.get('net_expected_alpha_bps', item.get('expected_alpha_bps')))} |",
        f"| Estimated cost | {_bps(item.get('estimated_cost_bps'))} |",
        f"| One-way turnover | {_pct(item.get('one_way_turnover'))} |",
        f"| Edge vs hold | {_bps(edge) if edge is not None else 'n/a'} |",
        f"| Current overlap | {_pct(item.get('current_overlap'))} |",
        "",
    ]
    if item.get("components"):
        lines += ["**Blend components:**", "", f"```json\n{item.get('components')}\n```", ""]

    lines += [
        "## 2 · Holdings",
        "",
        f"- positions: `{int(item.get('positions', 0) or 0)}`",
        f"- gross book: `{_f(item.get('gross'))}`",
        f"- weights hash: `{weights_digest}`",
        "",
    ]
    if holdings.empty:
        lines += ["No materialized weights artifact was found for this candidate. Hold-current rows intentionally have no new target artifact.", ""]
    else:
        lines += ["| Rank | Symbol | Weight | Weight % |", "| ---: | --- | ---: | ---: |"]
        for rec in holdings.head(30).to_dict(orient="records"):
            lines.append(
                f"| {int(rec['rank'])} | {rec['symbol']} | {float(rec['weight']):.8f} | {float(rec['weight_pct']):.4f}% |"
            )
        lines.append("")

    lines += [
        "## 3 · Risk and regime state",
        "",
        "| Signal | Value |",
        "| --- | ---: |",
        f"| Recent vol | {_pct(item.get('recent_vol'))} |",
        f"| 252d Sharpe | {_f(item.get('sharpe_252d'))} |",
        f"| 63d return | {_pct(item.get('return_63d'))} |",
        f"| 252d return | {_pct(item.get('return_252d'))} |",
        f"| Recent max drawdown | {_pct(item.get('recent_max_drawdown'))} |",
        f"| Kill switch | {'TRIPPED' if _truthy(item.get('kill_switch')) else 'clear'} |",
        f"| Data status | {data.get('status', 'n/a')} |",
        f"| Regime multiplier | {_f(regime.get('multiplier'))} |",
        f"| Turbulence percentile | {_f(regime.get('turb_pct'))} |",
        f"| Breadth | {_f(regime.get('breadth'))} |",
        f"| Absorption | {_f(regime.get('absorption'))} |",
        "",
    ]

    if not sleeves.empty:
        lines += ["## 4 · Sleeves live today", "", "| Sleeve | Weight |", "| --- | ---: |"]
        for sleeve, weight in sleeves.items():
            lines.append(f"| {sleeve} | {_pct(weight)} |")
        lines.append("")
    if factors:
        lines += [f"## 5 · Top factors inside dominant sleeve `{dom_sleeve}`", ""]
        for factor in factors:
            desc = factor["description"].strip()
            if len(desc) > 100:
                desc = desc[:99] + "…"
            lines.append(
                f"- `{factor['factor']}` ({factor['stage']}, wt {_f(factor['weight'])})"
                + (f" — {desc}" if desc else "")
            )
        lines.append("")

    lines += [
        "## 6 · Construction and artifact trail",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Config hash | `{meta.get('config_hash', 'n/a')}` |",
        f"| Target vol | {_pct(config.get('target_vol'))} |",
        f"| Seats base/min/max | {config.get('seats_base', 'n/a')} / {config.get('seats_min', 'n/a')} / {config.get('seats_max', 'n/a')} |",
        f"| Max position | {_pct(config.get('max_pos'))} |",
        f"| No-trade band | {_pct(config.get('no_trade_band'))} |",
        f"| Costs | {_f(config.get('tc_bps'), 1)} bps + {_pct(config.get('adv_participation_cap'))} ADV cap |",
        f"| Output dir | `{output_dir if meta else 'n/a'}` |",
        f"| Board dir | `{board_dir or 'n/a'}` |",
        "",
    ]
    if perf:
        lines += ["**1y diagnostic metrics from artifact:**", ""]
        for key, value in list(perf.items())[:12]:
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    lines += [
        "## 7 · PM interpretation",
        "",
        "Use this card to ask: does the play fit today’s regime, does it clear the hold-current hurdle after costs, "
        "and are the live sleeves/factors consistent with the intended mandate? Choose `hold_current` when the edge is not clear.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def playbook_path(board_dir: str | Path, candidate_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in candidate_id)
    return Path(board_dir) / "playbooks" / f"{safe}.md"


def write_playbook_bundle(board: pd.DataFrame, board_dir: str | Path) -> dict[str, Any]:
    """Write every candidate playbook for a board directory."""
    out_dir = Path(board_dir) / "playbooks"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for _, row in board.iterrows():
        candidate_id = str(row.get("candidate_id"))
        path = playbook_path(board_dir, candidate_id)
        path.write_text(render_candidate_playbook(row, board=board, board_dir=board_dir))
        rows.append(
            {
                "candidate_id": candidate_id,
                "name": row.get("name"),
                "eligible": bool(_truthy(row.get("eligible"))),
                "utility_bps": row.get("utility_bps"),
                "path": str(path),
            }
        )
    index = pd.DataFrame(rows).sort_values("utility_bps", ascending=False)
    index_path = out_dir / "index.csv"
    index.to_csv(index_path, index=False)
    (out_dir / "index.json").write_text(json.dumps(rows, indent=2, default=str))
    return {
        "count": len(rows),
        "directory": str(out_dir),
        "index_path": str(index_path),
    }
