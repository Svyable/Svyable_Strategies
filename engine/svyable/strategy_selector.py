"""Daily multi-strategy evaluation and canonical portfolio selection.

Deterministic code computes every candidate portfolio and its decision metrics.
A human or agent may select only from the emitted candidate board. The selected
portfolio is copied into the canonical ``svyable_nasdaq_lo`` artifact path used
by the Tastytrade execution layer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from svyable.panel import EPS, Panel
from svyable.pipeline import RunResult, run_pipeline
from svyable.strategy_registry import (
    StrategySpec,
    default_strategy_ids,
    get_strategy,
)

CANONICAL_STRATEGY_ID = "svyable_nasdaq_lo"


@dataclass(frozen=True)
class SelectionPolicy:
    mode: str = "deterministic"  # deterministic | agent | manual
    enabled_strategy_ids: tuple[str, ...] = field(
        default_factory=lambda: tuple(default_strategy_ids())
    )
    manual_strategy_id: str = "q23_hybrid_alpha"
    switch_buffer_bps: float = 2.0
    rebalance_buffer_bps: float = 0.5
    turnover_penalty_bps: float = 3.0
    max_one_way_turnover: float = 0.35
    risk_penalty_scale: float = 0.05
    min_expected_net_alpha_bps: float = -2.0
    alpha_halflife: int = 63
    alpha_min_history: int = 42
    fallback_to_current: bool = True

    def validate(self) -> None:
        if self.mode not in {"deterministic", "agent", "manual"}:
            raise ValueError("selection mode must be deterministic, agent, or manual")
        if not 0 < self.max_one_way_turnover <= 1.0:
            raise ValueError("max_one_way_turnover must be in (0, 1]")
        for strategy_id in self.enabled_strategy_ids:
            get_strategy(strategy_id)
        if self.mode == "manual":
            get_strategy(self.manual_strategy_id)


@dataclass
class SelectionRun:
    board: pd.DataFrame
    decision: dict[str, Any]
    candidate_results: dict[str, RunResult]
    canonical_output_dir: Path | None
    board_dir: Path


def policy_path(output_root: str | Path) -> Path:
    return Path(output_root) / "strategy_selection" / "policy.json"


def state_path(output_root: str | Path) -> Path:
    return Path(output_root) / "strategy_selection" / "state.json"


def agent_decision_path(output_root: str | Path) -> Path:
    return Path(output_root) / "strategy_selection" / "agent_decision.json"


def load_policy(output_root: str | Path) -> SelectionPolicy:
    path = policy_path(output_root)
    if not path.exists():
        return SelectionPolicy()
    payload = json.loads(path.read_text())
    if "enabled_strategy_ids" in payload:
        payload["enabled_strategy_ids"] = tuple(payload["enabled_strategy_ids"])
    policy = SelectionPolicy(**payload)
    policy.validate()
    return policy


def save_policy(output_root: str | Path, policy: SelectionPolicy) -> Path:
    policy.validate()
    path = policy_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(policy), indent=2, sort_keys=True))
    return path


def _load_state(output_root: str | Path) -> dict[str, Any]:
    path = state_path(output_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _latest_run_dir(root: Path, strategy_id: str) -> Path | None:
    base = root / strategy_id
    if not base.exists():
        return None
    runs = sorted(
        path
        for path in base.iterdir()
        if path.is_dir() and (path / "weights_today.csv").exists()
    )
    return runs[-1] if runs else None


def _read_weights(path: Path | None) -> pd.Series:
    if path is None or not (path / "weights_today.csv").exists():
        return pd.Series(dtype=float)
    frame = pd.read_csv(path / "weights_today.csv", index_col=0)
    column = "weight" if "weight" in frame else frame.columns[0]
    series = frame[column].astype(float)
    series.index = series.index.astype(str)
    return series


def current_weights(output_root: str | Path) -> pd.Series:
    return _read_weights(
        _latest_run_dir(Path(output_root), CANONICAL_STRATEGY_ID)
    )


def _align_weights(left: pd.Series, right: pd.Series) -> tuple[pd.Series, pd.Series]:
    index = left.index.union(right.index)
    return left.reindex(index).fillna(0.0), right.reindex(index).fillna(0.0)


def _one_way_turnover(target: pd.Series, current: pd.Series) -> float:
    target, current = _align_weights(target, current)
    return float((target - current).abs().sum() / 2.0)


def _portfolio_expected_alpha(
    result: RunResult,
    panel: Panel,
    weights: pd.Series,
    policy: SelectionPolicy,
) -> tuple[float, float, int]:
    """Causal next-day alpha estimate calibrated from score-to-return slopes."""
    score = result.ensemble.score.reindex_like(panel.ret)
    future = panel.ret.shift(-1)
    valid = score.notna() & future.notna()
    x = score.where(valid)
    y = future.where(valid)
    slopes = (x * y).sum(axis=1, min_count=1) / (
        (x * x).sum(axis=1, min_count=1) + EPS
    )
    slope_history = slopes.dropna()
    if len(slope_history) >= policy.alpha_min_history:
        slope_hat = float(
            slope_history.ewm(
                halflife=policy.alpha_halflife,
                min_periods=policy.alpha_min_history,
                adjust=False,
            ).mean().dropna().iloc[-1]
        )
    else:
        slope_hat = 0.0

    latest_score = score.ffill().iloc[-1]
    aligned_weights, aligned_score = _align_weights(weights, latest_score)
    cross_sectional = slope_hat * float((aligned_weights * aligned_score).sum())

    active = (
        result.pnl["net_ret"]
        - panel.market_ret.reindex(result.pnl.index).fillna(0.0)
    ).iloc[:-1].dropna()
    realized = 0.0
    if len(active) >= policy.alpha_min_history:
        realized = float(
            active.ewm(
                halflife=policy.alpha_halflife,
                min_periods=policy.alpha_min_history,
                adjust=False,
            ).mean().dropna().iloc[-1]
        )

    observations = int(len(slope_history))
    confidence = min(1.0, observations / max(1.0, 2.0 * policy.alpha_min_history))
    expected = confidence * (0.70 * cross_sectional + 0.30 * realized)
    expected = float(np.clip(expected, -0.01, 0.01))
    return expected, confidence, observations


def _recent_risk(result: RunResult) -> tuple[float, float]:
    returns = result.pnl["net_ret"].dropna().tail(126)
    if returns.empty:
        return 0.0, 0.0
    vol = float(returns.tail(63).std() * np.sqrt(252.0))
    nav = (1.0 + returns).cumprod()
    drawdown = float((1.0 - nav / nav.cummax()).max())
    return vol, drawdown


def _days_since(value: str | None, as_of: date) -> int:
    if not value:
        return 10_000
    try:
        return max(0, (as_of - date.fromisoformat(value[:10])).days)
    except ValueError:
        return 10_000


def _candidate_row(
    spec: StrategySpec,
    result: RunResult,
    panel: Panel,
    current: pd.Series,
    current_strategy_id: str | None,
    state: dict[str, Any],
    policy: SelectionPolicy,
    as_of: date,
) -> dict[str, Any]:
    target = result.weights.iloc[-1].astype(float)
    target.index = target.index.astype(str)
    turnover = _one_way_turnover(target, current)
    expected, confidence, observations = _portfolio_expected_alpha(
        result, panel, target, policy
    )
    vol, drawdown = _recent_risk(result)
    cfg = spec.build_config()
    estimated_cost_bps = turnover * 2.0 * cfg.tc_bps
    turnover_penalty = turnover * policy.turnover_penalty_bps
    risk_penalty_bps = max(0.0, vol - cfg.target_vol) * 10_000.0 * policy.risk_penalty_scale
    expected_alpha_bps = expected * 10_000.0
    net_alpha_bps = expected_alpha_bps - estimated_cost_bps
    utility_bps = net_alpha_bps - turnover_penalty - risk_penalty_bps
    same_strategy = spec.strategy_id == current_strategy_id
    held_days = _days_since(state.get("selected_at"), as_of) if same_strategy else 0
    since_rebalance = _days_since(state.get("last_rebalanced_at"), as_of) if same_strategy else 10_000
    cadence_due = (not same_strategy) or since_rebalance >= spec.rebalance_interval_days
    hold_lock = bool(
        current_strategy_id
        and not same_strategy
        and _days_since(state.get("selected_at"), as_of) < get_strategy(current_strategy_id).minimum_hold_days
    )
    kill_switch = bool(result.risk.kill_switch.iloc[-1] > 0)
    eligible = bool(
        not kill_switch
        and not hold_lock
        and cadence_due
        and turnover <= policy.max_one_way_turnover
        and net_alpha_bps >= policy.min_expected_net_alpha_bps
    )
    current_aligned, target_aligned = _align_weights(current, target)
    overlap = float(np.minimum(current_aligned.abs(), target_aligned.abs()).sum())
    return {
        "candidate_id": spec.strategy_id,
        "strategy_id": spec.strategy_id,
        "action": "rebalance",
        "name": spec.display_name,
        "family": spec.family,
        "maturity": spec.maturity,
        "factor_count": len(spec.factor_names),
        "positions": int((target.abs() > 1e-8).sum()),
        "gross": float(target.abs().sum()),
        "expected_alpha_bps": round(expected_alpha_bps, 3),
        "alpha_confidence": round(confidence, 3),
        "alpha_observations": observations,
        "one_way_turnover": round(turnover, 5),
        "estimated_cost_bps": round(estimated_cost_bps, 3),
        "turnover_penalty_bps": round(turnover_penalty, 3),
        "risk_penalty_bps": round(risk_penalty_bps, 3),
        "net_expected_alpha_bps": round(net_alpha_bps, 3),
        "utility_bps": round(utility_bps, 3),
        "recent_vol": round(vol, 5),
        "recent_max_drawdown": round(drawdown, 5),
        "current_overlap": round(overlap, 5),
        "cadence_due": cadence_due,
        "hold_lock": hold_lock,
        "kill_switch": kill_switch,
        "eligible": eligible,
        "is_current_strategy": same_strategy,
        "held_days": held_days,
        "minimum_hold_days": spec.minimum_hold_days,
        "rebalance_interval_days": spec.rebalance_interval_days,
        "output_dir": str(result.output_dir or ""),
    }


def _hold_row(
    current_strategy_id: str | None,
    current: pd.Series,
    candidate_results: dict[str, RunResult],
    panel: Panel,
    policy: SelectionPolicy,
) -> dict[str, Any]:
    expected = confidence = 0.0
    observations = 0
    vol = drawdown = 0.0
    if current_strategy_id in candidate_results:
        result = candidate_results[current_strategy_id]
        expected, confidence, observations = _portfolio_expected_alpha(
            result, panel, current, policy
        )
        vol, drawdown = _recent_risk(result)
    expected_bps = expected * 10_000.0
    return {
        "candidate_id": "hold_current",
        "strategy_id": current_strategy_id or "cash",
        "action": "hold",
        "name": "Hold current portfolio" if current_strategy_id else "Hold cash",
        "family": "no-trade baseline",
        "maturity": "baseline",
        "factor_count": 0,
        "positions": int((current.abs() > 1e-8).sum()),
        "gross": float(current.abs().sum()),
        "expected_alpha_bps": round(expected_bps, 3),
        "alpha_confidence": round(confidence, 3),
        "alpha_observations": observations,
        "one_way_turnover": 0.0,
        "estimated_cost_bps": 0.0,
        "turnover_penalty_bps": 0.0,
        "risk_penalty_bps": 0.0,
        "net_expected_alpha_bps": round(expected_bps, 3),
        "utility_bps": round(expected_bps, 3),
        "recent_vol": round(vol, 5),
        "recent_max_drawdown": round(drawdown, 5),
        "current_overlap": float(current.abs().sum()),
        "cadence_due": False,
        "hold_lock": False,
        "kill_switch": False,
        "eligible": True,
        "is_current_strategy": True,
        "held_days": 0,
        "minimum_hold_days": 0,
        "rebalance_interval_days": 0,
        "output_dir": "",
    }


def _board_hash(board: pd.DataFrame, as_of: date) -> str:
    columns = [
        "candidate_id", "strategy_id", "action", "expected_alpha_bps",
        "one_way_turnover", "estimated_cost_bps", "utility_bps", "eligible",
    ]
    payload = {
        "as_of": str(as_of),
        "rows": board[columns].sort_values("candidate_id").to_dict(orient="records"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:24]


def _deterministic_choice(board: pd.DataFrame, policy: SelectionPolicy) -> dict[str, Any]:
    hold = board.loc[board["candidate_id"] == "hold_current"].iloc[0]
    eligible = board[(board["eligible"]) & (board["action"] == "rebalance")]
    if eligible.empty:
        chosen = hold
        reason = "No rebalance candidate passed eligibility gates."
    else:
        best = eligible.sort_values("utility_bps", ascending=False).iloc[0]
        buffer_bps = (
            policy.rebalance_buffer_bps
            if bool(best["is_current_strategy"])
            else policy.switch_buffer_bps
        )
        if float(best["utility_bps"]) >= float(hold["utility_bps"]) + buffer_bps:
            chosen = best
            reason = (
                f"Highest eligible utility exceeded hold by at least {buffer_bps:.2f} bps."
            )
        else:
            chosen = hold
            reason = "Best candidate did not clear the cost-aware hold buffer."
    return {**chosen.to_dict(), "reason": reason, "source": "deterministic"}


def _agent_choice(
    board: pd.DataFrame,
    policy: SelectionPolicy,
    output_root: str | Path,
    candidate_hash: str,
    as_of: date,
) -> dict[str, Any]:
    path = agent_decision_path(output_root)
    fallback = _deterministic_choice(board, policy)
    if not path.exists():
        return {**fallback, "source": "deterministic_fallback", "reason": "No agent decision file."}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {**fallback, "source": "deterministic_fallback", "reason": "Malformed agent decision."}
    if payload.get("as_of") != str(as_of) or payload.get("candidate_set_hash") != candidate_hash:
        return {**fallback, "source": "deterministic_fallback", "reason": "Stale agent decision."}
    candidate_id = str(payload.get("candidate_id", ""))
    matches = board[board["candidate_id"] == candidate_id]
    if matches.empty or not bool(matches.iloc[0]["eligible"]):
        return {**fallback, "source": "deterministic_fallback", "reason": "Agent selected an unavailable candidate."}
    chosen = matches.iloc[0]
    return {
        **chosen.to_dict(),
        "source": "agent",
        "reason": str(payload.get("reason", "Agent selected an eligible candidate."))[:1000],
        "agent_confidence": payload.get("confidence"),
    }


def choose_candidate(
    board: pd.DataFrame,
    policy: SelectionPolicy,
    output_root: str | Path,
    candidate_hash: str,
    as_of: date,
) -> dict[str, Any]:
    if policy.mode == "agent":
        return _agent_choice(board, policy, output_root, candidate_hash, as_of)
    if policy.mode == "manual":
        matches = board[
            (board["strategy_id"] == policy.manual_strategy_id)
            & (board["action"] == "rebalance")
            & (board["eligible"])
        ]
        if not matches.empty:
            return {
                **matches.iloc[0].to_dict(),
                "source": "manual_policy",
                "reason": "Selected by persisted manual policy.",
            }
    return _deterministic_choice(board, policy)


def _copy_canonical_artifacts(
    selected: dict[str, Any],
    candidate_results: dict[str, RunResult],
    current: pd.Series,
    output_root: str | Path,
    tag: str,
    candidate_hash: str,
    as_of: date,
) -> Path:
    root = Path(output_root)
    strategy_id = str(selected["strategy_id"])
    action = str(selected["action"])
    source_result = candidate_results.get(strategy_id)
    if source_result is None or source_result.output_dir is None:
        if action != "hold":
            raise RuntimeError(f"No artifact source for selected strategy {strategy_id}")
        current_state = _load_state(output_root)
        source_strategy = current_state.get("selected_strategy_id")
        source_result = candidate_results.get(source_strategy)
    if source_result is None or source_result.output_dir is None:
        raise RuntimeError("Cannot emit canonical artifacts without a current candidate run")

    destination = root / CANONICAL_STRATEGY_ID / tag
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_result.output_dir, destination)

    if action == "hold":
        current[current.abs() > 1e-12].rename("weight").to_csv(
            destination / "weights_today.csv"
        )
        history_path = destination / "weights_history.csv"
        history = pd.read_csv(history_path, index_col=0) if history_path.exists() else pd.DataFrame()
        today_label = str(as_of)
        current_frame = current.to_frame().T
        current_frame.index = [today_label]
        history = pd.concat([history.iloc[:-1], current_frame]).tail(63)
        history.to_csv(history_path)

    meta_path = destination / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta["strategy_id"] = CANONICAL_STRATEGY_ID
    meta["selected_strategy_id"] = strategy_id
    meta["selection"] = {
        key: value
        for key, value in selected.items()
        if key not in {"output_dir"}
    }
    meta["selection"]["candidate_set_hash"] = candidate_hash
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True, default=str))

    report_path = destination / "morning_report.md"
    existing = report_path.read_text() if report_path.exists() else ""
    selection_text = (
        f"\n\n## Strategy selection\n\n"
        f"- Selected: **{strategy_id}**\n"
        f"- Action: **{action}**\n"
        f"- Source: {selected.get('source')}\n"
        f"- Expected alpha: {selected.get('expected_alpha_bps')} bps\n"
        f"- One-way turnover: {float(selected.get('one_way_turnover', 0.0)):.1%}\n"
        f"- Estimated cost: {selected.get('estimated_cost_bps')} bps\n"
        f"- Reason: {selected.get('reason')}\n"
        f"- Candidate hash: `{candidate_hash}`\n"
    )
    report_path.write_text(existing + selection_text)
    return destination


def run_strategy_selection(
    panel: Panel,
    output_root: str | Path,
    *,
    policy: SelectionPolicy | None = None,
    tag: str | None = None,
    activate: bool = True,
) -> SelectionRun:
    policy = policy or load_policy(output_root)
    policy.validate()
    as_of = panel.close.index[-1].date()
    use_tag = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    state = _load_state(output_root)
    current_strategy_id = state.get("selected_strategy_id")
    current = current_weights(output_root)

    results: dict[str, RunResult] = {}
    rows: list[dict[str, Any]] = []
    for strategy_id in policy.enabled_strategy_ids:
        spec = get_strategy(strategy_id)
        cfg = spec.build_config()
        result = run_pipeline(
            panel,
            cfg,
            output_root=output_root,
            tag=use_tag,
            write_artifacts=True,
            factor_names=spec.factor_names,
            run_context={
                "candidate_strategy_id": spec.strategy_id,
                "strategy_family": spec.family,
                "strategy_maturity": spec.maturity,
            },
        )
        results[strategy_id] = result
        rows.append(
            _candidate_row(
                spec,
                result,
                panel,
                current,
                current_strategy_id,
                state,
                policy,
                as_of,
            )
        )

    rows.append(
        _hold_row(current_strategy_id, current, results, panel, policy)
    )
    board = pd.DataFrame(rows).sort_values("utility_bps", ascending=False)
    candidate_hash = _board_hash(board, as_of)
    board["candidate_set_hash"] = candidate_hash
    board["as_of"] = str(as_of)

    board_dir = Path(output_root) / "strategy_selection" / use_tag
    board_dir.mkdir(parents=True, exist_ok=True)
    board.to_csv(board_dir / "candidate_board.csv", index=False)
    (board_dir / "candidate_board.json").write_text(
        json.dumps(board.to_dict(orient="records"), indent=2, default=str)
    )
    agent_template = {
        "as_of": str(as_of),
        "candidate_set_hash": candidate_hash,
        "candidate_id": "hold_current",
        "confidence": 0.0,
        "reason": "Choose only an eligible candidate_id from candidate_board.csv.",
    }
    (board_dir / "agent_decision_template.json").write_text(
        json.dumps(agent_template, indent=2)
    )

    decision = choose_candidate(
        board, policy, output_root, candidate_hash, as_of
    )
    decision.update(
        {
            "as_of": str(as_of),
            "candidate_set_hash": candidate_hash,
            "mode": policy.mode,
            "selected_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    (board_dir / "selection.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True, default=str)
    )

    canonical_dir = None
    if activate:
        canonical_dir = _copy_canonical_artifacts(
            decision,
            results,
            current,
            output_root,
            use_tag,
            candidate_hash,
            as_of,
        )
        new_state = {
            "selected_strategy_id": decision["strategy_id"],
            "selected_action": decision["action"],
            "selected_at": (
                state.get("selected_at")
                if decision["action"] == "hold" and state.get("selected_at")
                else str(as_of)
            ),
            "last_rebalanced_at": (
                str(as_of)
                if decision["action"] == "rebalance"
                else state.get("last_rebalanced_at")
            ),
            "candidate_set_hash": candidate_hash,
            "canonical_output_dir": str(canonical_dir),
            "source": decision.get("source"),
            "reason": decision.get("reason"),
        }
        path = state_path(output_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(new_state, indent=2, sort_keys=True))

    return SelectionRun(
        board=board,
        decision=decision,
        candidate_results=results,
        canonical_output_dir=canonical_dir,
        board_dir=board_dir,
    )
