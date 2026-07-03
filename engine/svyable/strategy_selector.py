"""Daily multi-strategy evaluation and cost-aware portfolio selection.

Deterministic code computes every candidate portfolio and its decision metrics.
A human or agent may choose only from the immutable candidate board. Activation
is a separate validated step that writes the one canonical Tastytrade portfolio.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from svyable import factor_library as flib
from svyable.config import SvyableConfig
from svyable.panel import EPS, Panel
from svyable.pipeline import RunResult, run_pipeline
from svyable.strategy_registry import (
    StrategySpec,
    default_strategy_ids,
    get_strategy,
)

CANONICAL_STRATEGY_ID = "svyable_nasdaq_lo"

_FACTOR_CONFIG_FIELDS = (
    "beta_win", "idio_win", "down_win", "mom_win", "mom_short", "mom_long",
    "rev_win", "ema_fast", "ema_slow", "ou_short_win", "ou_med_win",
    "ou_halflife_min", "ou_halflife_max", "ofi_short_win", "ofi_med_win",
    "ofi_long_win", "vpin_win", "impact_win", "attention_win",
    "disposition_win", "efficiency_win", "persistence_win", "skew_win",
    "kurt_win", "vov_win",
)


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
        if not self.enabled_strategy_ids:
            raise ValueError("at least one strategy must be enabled")
        if not 0 < self.max_one_way_turnover <= 1.0:
            raise ValueError("max_one_way_turnover must be in (0, 1]")
        if self.alpha_min_history < 10:
            raise ValueError("alpha_min_history must be at least 10")
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
    slope_hat = 0.0
    if len(slope_history) >= policy.alpha_min_history:
        smoothed = slope_history.ewm(
            halflife=policy.alpha_halflife,
            min_periods=policy.alpha_min_history,
            adjust=False,
        ).mean().dropna()
        if len(smoothed):
            slope_hat = float(smoothed.iloc[-1])

    latest_score = score.ffill().iloc[-1]
    aligned_weights, aligned_score = _align_weights(weights, latest_score)
    cross_sectional = slope_hat * float((aligned_weights * aligned_score).sum())

    active = (
        result.pnl["net_ret"]
        - panel.market_ret.reindex(result.pnl.index).fillna(0.0)
    ).iloc[:-1].dropna()
    realized = 0.0
    if len(active) >= policy.alpha_min_history:
        smoothed_active = active.ewm(
            halflife=policy.alpha_halflife,
            min_periods=policy.alpha_min_history,
            adjust=False,
        ).mean().dropna()
        if len(smoothed_active):
            realized = float(smoothed_active.iloc[-1])

    observations = int(len(slope_history))
    confidence = min(1.0, observations / max(1.0, 2.0 * policy.alpha_min_history))
    expected = confidence * (0.70 * cross_sectional + 0.30 * realized)
    return float(np.clip(expected, -0.01, 0.01)), confidence, observations


def _recent_metrics(result: RunResult) -> dict[str, float]:
    returns = result.pnl["net_ret"].dropna()
    recent = returns.tail(252)
    if recent.empty:
        return {
            "recent_vol": 0.0,
            "recent_max_drawdown": 0.0,
            "return_63d": 0.0,
            "return_252d": 0.0,
            "sharpe_252d": 0.0,
            "avg_one_way_turnover_63d": 0.0,
        }
    nav = (1.0 + recent).cumprod()
    vol = float(recent.tail(63).std() * np.sqrt(252.0))
    mean = float(recent.mean())
    std = float(recent.std())
    turnover = result.pnl.get("turnover", pd.Series(dtype=float)).tail(63)
    return {
        "recent_vol": vol,
        "recent_max_drawdown": float((1.0 - nav / nav.cummax()).max()),
        "return_63d": float((1.0 + recent.tail(63)).prod() - 1.0),
        "return_252d": float((1.0 + recent).prod() - 1.0),
        "sharpe_252d": mean / (std + EPS) * np.sqrt(252.0),
        "avg_one_way_turnover_63d": float(turnover.mean() / 2.0) if len(turnover) else 0.0,
    }


def _days_since(value: str | None, as_of: date) -> int:
    if not value:
        return 10_000
    try:
        return max(0, (as_of - date.fromisoformat(value[:10])).days)
    except ValueError:
        return 10_000


def _factor_signature(cfg: SvyableConfig) -> tuple[Any, ...]:
    return tuple(getattr(cfg, field) for field in _FACTOR_CONFIG_FIELDS)


def _factor_caches(
    panel: Panel,
    specs: list[StrategySpec],
) -> dict[str, dict[str, pd.DataFrame]]:
    grouped: dict[tuple[Any, ...], list[StrategySpec]] = {}
    for spec in specs:
        grouped.setdefault(_factor_signature(spec.build_config()), []).append(spec)

    caches: dict[str, dict[str, pd.DataFrame]] = {}
    for group in grouped.values():
        representative = group[0].build_config()
        union = sorted({name for spec in group for name in spec.factor_names})
        cache = flib.compute_all(panel, representative, names=union)
        for spec in group:
            caches[spec.strategy_id] = cache
    return caches


def _candidate_row(
    spec: StrategySpec,
    result: RunResult,
    panel: Panel,
    current: pd.Series,
    current_strategy_id: str | None,
    state: dict[str, Any],
    policy: SelectionPolicy,
    as_of: date,
    current_source: str,
) -> dict[str, Any]:
    target = result.weights.iloc[-1].astype(float)
    target.index = target.index.astype(str)
    target_aligned, current_aligned = _align_weights(target, current)
    delta = target_aligned - current_aligned
    turnover = float(delta.abs().sum() / 2.0)
    max_change = float(delta.abs().max()) if len(delta) else 0.0
    expected, confidence, observations = _portfolio_expected_alpha(
        result, panel, target, policy
    )
    metrics = _recent_metrics(result)
    cfg = spec.build_config()
    estimated_cost_bps = turnover * 2.0 * cfg.tc_bps
    turnover_penalty = turnover * policy.turnover_penalty_bps
    risk_penalty_bps = (
        max(0.0, metrics["recent_vol"] - cfg.target_vol)
        * 10_000.0
        * policy.risk_penalty_scale
    )
    expected_alpha_bps = expected * 10_000.0
    net_alpha_bps = expected_alpha_bps - estimated_cost_bps
    utility_bps = net_alpha_bps - turnover_penalty - risk_penalty_bps
    same_strategy = spec.strategy_id == current_strategy_id
    held_days = _days_since(state.get("selected_at"), as_of) if same_strategy else 0
    since_rebalance = (
        _days_since(state.get("last_rebalanced_at"), as_of)
        if same_strategy else 10_000
    )
    cadence_due = (not same_strategy) or since_rebalance >= spec.rebalance_interval_days
    current_spec = (
        get_strategy(current_strategy_id)
        if current_strategy_id and current_strategy_id != "cash"
        else None
    )
    hold_lock = bool(
        current_spec
        and not same_strategy
        and _days_since(state.get("selected_at"), as_of) < current_spec.minimum_hold_days
    )
    kill_switch = bool(result.risk.kill_switch.iloc[-1] > 0)
    rebalance_required = bool(max_change >= cfg.no_trade_band or turnover > 1e-6)
    eligible = bool(
        not kill_switch
        and not hold_lock
        and cadence_due
        and rebalance_required
        and turnover <= policy.max_one_way_turnover
        and net_alpha_bps >= policy.min_expected_net_alpha_bps
    )
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
        "max_weight_change": round(max_change, 5),
        "estimated_cost_bps": round(estimated_cost_bps, 3),
        "turnover_penalty_bps": round(turnover_penalty, 3),
        "risk_penalty_bps": round(risk_penalty_bps, 3),
        "net_expected_alpha_bps": round(net_alpha_bps, 3),
        "utility_bps": round(utility_bps, 3),
        "current_overlap": round(overlap, 5),
        "current_position_source": current_source,
        "rebalance_required": rebalance_required,
        "cadence_due": cadence_due,
        "hold_lock": hold_lock,
        "kill_switch": kill_switch,
        "eligible": eligible,
        "is_current_strategy": same_strategy,
        "held_days": held_days,
        "minimum_hold_days": spec.minimum_hold_days,
        "rebalance_interval_days": spec.rebalance_interval_days,
        "output_dir": str(result.output_dir or ""),
        **{key: round(value, 5) for key, value in metrics.items()},
    }


def _hold_row(
    current_strategy_id: str | None,
    current: pd.Series,
    candidate_results: dict[str, RunResult],
    panel: Panel,
    policy: SelectionPolicy,
    current_source: str,
) -> dict[str, Any]:
    expected = confidence = 0.0
    observations = 0
    metrics = {
        "recent_vol": 0.0,
        "recent_max_drawdown": 0.0,
        "return_63d": 0.0,
        "return_252d": 0.0,
        "sharpe_252d": 0.0,
        "avg_one_way_turnover_63d": 0.0,
    }
    if current_strategy_id in candidate_results:
        result = candidate_results[current_strategy_id]
        expected, confidence, observations = _portfolio_expected_alpha(
            result, panel, current, policy
        )
        metrics = _recent_metrics(result)
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
        "max_weight_change": 0.0,
        "estimated_cost_bps": 0.0,
        "turnover_penalty_bps": 0.0,
        "risk_penalty_bps": 0.0,
        "net_expected_alpha_bps": round(expected_bps, 3),
        "utility_bps": round(expected_bps, 3),
        "current_overlap": float(current.abs().sum()),
        "current_position_source": current_source,
        "rebalance_required": False,
        "cadence_due": False,
        "hold_lock": False,
        "kill_switch": False,
        "eligible": True,
        "is_current_strategy": True,
        "held_days": 0,
        "minimum_hold_days": 0,
        "rebalance_interval_days": 0,
        "output_dir": "",
        **{key: round(value, 5) for key, value in metrics.items()},
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
        no_current_portfolio = str(hold["strategy_id"]) == "cash"
        if no_current_portfolio or not policy.fallback_to_current:
            chosen = best
            reason = "Selected the highest eligible utility candidate."
        else:
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
        return {
            **fallback,
            "source": "deterministic_recommendation",
            "reason": "Awaiting a fresh agent decision for this board.",
        }
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {
            **fallback,
            "source": "deterministic_recommendation",
            "reason": "Malformed agent decision; awaiting correction.",
        }
    if payload.get("as_of") != str(as_of) or payload.get("candidate_set_hash") != candidate_hash:
        return {
            **fallback,
            "source": "deterministic_recommendation",
            "reason": "Existing agent decision is stale for this board.",
        }
    candidate_id = str(payload.get("candidate_id", ""))
    matches = board[board["candidate_id"] == candidate_id]
    if matches.empty or not bool(matches.iloc[0]["eligible"]):
        return {
            **fallback,
            "source": "deterministic_recommendation",
            "reason": "Existing agent decision is unavailable or ineligible.",
        }
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


def run_strategy_selection(
    panel: Panel,
    output_root: str | Path,
    *,
    policy: SelectionPolicy | None = None,
    tag: str | None = None,
    activate: bool = False,
    current_weights_override: pd.Series | None = None,
    current_position_source: str = "canonical_target",
) -> SelectionRun:
    policy = policy or load_policy(output_root)
    policy.validate()
    as_of = panel.close.index[-1].date()
    use_tag = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    state = _load_state(output_root)
    current_strategy_id = state.get("selected_strategy_id")
    current = (
        current_weights_override.astype(float).copy()
        if current_weights_override is not None
        else current_weights(output_root)
    )
    current.index = current.index.astype(str)

    specs = [get_strategy(strategy_id) for strategy_id in policy.enabled_strategy_ids]
    caches = _factor_caches(panel, specs)
    results: dict[str, RunResult] = {}
    rows: list[dict[str, Any]] = []
    for spec in specs:
        cfg = spec.build_config()
        result = run_pipeline(
            panel,
            cfg,
            output_root=output_root,
            tag=use_tag,
            write_artifacts=True,
            factor_names=spec.factor_names,
            precomputed_factors=caches[spec.strategy_id],
            run_context={
                "candidate_strategy_id": spec.strategy_id,
                "strategy_family": spec.family,
                "strategy_maturity": spec.maturity,
                "current_position_source": current_position_source,
            },
        )
        results[spec.strategy_id] = result
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
                current_position_source,
            )
        )

    rows.append(
        _hold_row(
            current_strategy_id,
            current,
            results,
            panel,
            policy,
            current_position_source,
        )
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
    (board_dir / "agent_decision_template.json").write_text(
        json.dumps(
            {
                "as_of": str(as_of),
                "candidate_set_hash": candidate_hash,
                "candidate_id": "hold_current",
                "confidence": 0.0,
                "reason": "Choose only an eligible candidate_id from candidate_board.csv.",
            },
            indent=2,
        )
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
        if policy.mode == "agent":
            raise RuntimeError(
                "Agent mode requires two-phase activation with `python -m svyable.strategy_activate`."
            )
        from svyable.strategy_activation import activate_latest_selection

        activation = activate_latest_selection(output_root)
        canonical_dir = Path(activation["canonical_output_dir"])
        decision = activation

    return SelectionRun(
        board=board,
        decision=decision,
        candidate_results=results,
        canonical_output_dir=canonical_dir,
        board_dir=board_dir,
    )
