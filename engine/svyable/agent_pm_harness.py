"""Agent PM context-pack harness for strategy selection.

The harness keeps the daily research/execution loop separate from repository
self-improvement. It packages the latest immutable candidate board, decision
rails, artifact health, factor warnings, and a visible meta decision trace for an
agent or human PM. The only valid agent output remains
``strategy_selection/agent_decision.json``; this module never emits orders and
never modifies strategy code.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from svyable.agent_meta_trace import build_meta_trace
from svyable.calendar import expected_last_close
from svyable.factor_health_tools import factor_review_summary, factor_trend_alerts
from svyable.strategy_selector import load_policy


@dataclass(frozen=True)
class AgentPmPack:
    context_path: Path
    memo_path: Path
    template_path: Path
    board_dir: Path
    candidate_set_hash: str
    as_of: str
    allowed_candidate_ids: list[str]


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _latest_board_dir(output_root: str | Path) -> Path:
    root = Path(output_root) / "strategy_selection"
    candidates = sorted(
        path for path in root.iterdir()
        if path.is_dir() and (path / "candidate_board.csv").exists()
    ) if root.exists() else []
    if not candidates:
        raise FileNotFoundError("No strategy candidate board exists.")
    return candidates[-1]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"error": f"malformed json: {path}"}


def _read_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, index_col=0)
    except Exception as exc:  # defensive artifact reader
        return pd.DataFrame({"error": [str(exc)]})


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def _candidate_table(board: pd.DataFrame, max_candidates: int) -> list[dict[str, Any]]:
    columns = [
        "candidate_id", "strategy_id", "action", "eligible", "utility_bps",
        "expected_alpha_bps", "net_expected_alpha_bps", "one_way_turnover",
        "estimated_cost_bps", "risk_penalty_bps", "current_overlap",
        "rebalance_required", "cadence_due", "hold_lock", "kill_switch",
        "family", "maturity", "output_dir",
    ]
    keep = [col for col in columns if col in board.columns]
    view = board[keep].head(max_candidates).copy()
    return view.to_dict(orient="records")


def _blocked_reasons(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    checks = {
        "hold_lock": "minimum hold still active",
        "kill_switch": "candidate risk kill switch is active",
        "cadence_due": "rebalance cadence not due",
        "rebalance_required": "target drift is below rebalance threshold",
    }
    for column, label in checks.items():
        if column not in row:
            continue
        value = row[column]
        truthy = str(value).lower() in {"true", "1", "yes"}
        if column in {"cadence_due", "rebalance_required"}:
            if not truthy:
                reasons.append(label)
        elif truthy:
            reasons.append(label)
    if "one_way_turnover" in row:
        try:
            if float(row["one_way_turnover"]) > 0.35:
                reasons.append("turnover exceeds policy limit")
        except (TypeError, ValueError):
            pass
    if not reasons and not bool(str(row.get("eligible", "false")).lower() in {"true", "1", "yes"}):
        reasons.append("not eligible under selector policy")
    return reasons


def _decision_rails(board: pd.DataFrame) -> dict[str, Any]:
    eligible = board[_bool_series(board.get("eligible", pd.Series(False, index=board.index)))]
    allowed = eligible["candidate_id"].astype(str).tolist() if "candidate_id" in eligible else []
    blocked: list[dict[str, Any]] = []
    for _, row in board.iterrows():
        cid = str(row.get("candidate_id", ""))
        if cid in allowed:
            continue
        blocked.append({"candidate_id": cid, "reasons": _blocked_reasons(row)})
    return {
        "allowed_candidate_ids": allowed,
        "blocked_candidates": blocked,
        "required_agent_decision_path": "strategy_selection/agent_decision.json",
        "required_fields": ["as_of", "candidate_set_hash", "candidate_id", "confidence", "reason"],
        "hard_rules": [
            "Choose exactly one candidate_id from allowed_candidate_ids.",
            "Do not edit repository code during the same decision cycle.",
            "Do not invent weights, symbols, quantities, or orders.",
            "If no allowed candidate improves the state, choose hold_current when allowed.",
            "Activation and order planning remain separate validated steps.",
        ],
    }


def _artifact_health(output_dir: str | Path | None) -> dict[str, Any]:
    if not output_dir:
        return {"status": "missing_output_dir"}
    path = Path(str(output_dir))
    if not path.exists():
        return {"status": "missing_output_dir", "output_dir": str(path)}
    meta = _read_json(path / "meta.json")
    inputs = _read_frame(path / "execution_inputs.csv")
    ic = _read_frame(path / "ic_health.csv")
    expected = str(expected_last_close(datetime.now().date()))
    artifact_date = str(
        ((meta.get("execution_inputs") or {}).get("date"))
        or ((meta.get("data") or {}).get("last_date"))
        or ""
    )
    required_inputs = {"price", "adv_dollars", "is_liquid"}
    missing_columns = sorted(required_inputs - set(inputs.columns)) if not inputs.empty else sorted(required_inputs)
    trends = factor_trend_alerts(ic) if not ic.empty else pd.DataFrame()
    summary = factor_review_summary(trends, pd.DataFrame())
    return {
        "status": "ok" if path.exists() else "missing_output_dir",
        "output_dir": str(path),
        "artifact_date": artifact_date,
        "expected_date": expected,
        "inputs_stale": bool(not artifact_date or artifact_date < expected),
        "execution_input_rows": int(len(inputs)) if not inputs.empty else 0,
        "missing_execution_columns": missing_columns,
        "factor_trend_summary": summary,
        "factor_trend_alerts": trends.head(20).to_dict(orient="records") if not trends.empty else [],
    }


def _pick_focus_candidate(board: pd.DataFrame, selection: dict[str, Any]) -> pd.Series | None:
    cid = str(selection.get("candidate_id", ""))
    if cid and "candidate_id" in board.columns:
        matches = board[board["candidate_id"].astype(str) == cid]
        if not matches.empty:
            return matches.iloc[0]
    eligible = board[_bool_series(board.get("eligible", pd.Series(False, index=board.index)))]
    rebalances = eligible[eligible.get("action", pd.Series(index=eligible.index, dtype=object)).astype(str) == "rebalance"]
    if not rebalances.empty:
        return rebalances.sort_values("utility_bps", ascending=False).iloc[0]
    hold = board[board.get("candidate_id", pd.Series(index=board.index, dtype=object)).astype(str) == "hold_current"]
    if not hold.empty:
        return hold.iloc[0]
    return board.iloc[0] if not board.empty else None


def _focus_candidate_id(board: pd.DataFrame, selection: dict[str, Any]) -> str | None:
    focus = _pick_focus_candidate(board, selection)
    return str(focus.get("candidate_id")) if focus is not None else None


def build_agent_context(
    output_root: str | Path,
    *,
    board_dir: str | Path | None = None,
    max_candidates: int = 15,
) -> dict[str, Any]:
    root = Path(output_root)
    board_path = Path(board_dir) if board_dir is not None else _latest_board_dir(root)
    board = pd.read_csv(board_path / "candidate_board.csv")
    if board.empty:
        raise RuntimeError("Latest candidate board is empty.")
    as_of = str(board.iloc[0].get("as_of", ""))
    candidate_hash = str(board.iloc[0].get("candidate_set_hash", ""))
    selection = _read_json(board_path / "selection.json")
    policy = load_policy(root)
    rails = _decision_rails(board)
    focus = _pick_focus_candidate(board, selection)
    focus_health = _artifact_health(focus.get("output_dir") if focus is not None else None)
    trace = build_meta_trace(
        board,
        selected_candidate_id=_focus_candidate_id(board, selection),
        artifact_health=focus_health,
        max_candidates=max(8, min(max_candidates, 15)),
    )
    current_positions = _read_json(root / "strategy_selection" / "current_positions.json")

    top_eligible = board[
        _bool_series(board.get("eligible", pd.Series(False, index=board.index)))
    ].sort_values("utility_bps", ascending=False) if "utility_bps" in board.columns else pd.DataFrame()
    context = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_root": str(root),
        "board_dir": str(board_path),
        "as_of": as_of,
        "candidate_set_hash": candidate_hash,
        "policy": asdict(policy),
        "current_positions": current_positions,
        "current_selection_state": _read_json(root / "strategy_selection" / "state.json"),
        "planned_selection": selection,
        "rails": rails,
        "summary": {
            "candidate_count": int(len(board)),
            "eligible_count": int(len(rails["allowed_candidate_ids"])),
            "top_eligible_candidate": str(top_eligible.iloc[0]["candidate_id"]) if not top_eligible.empty else None,
            "planned_candidate": selection.get("candidate_id"),
            "mode": policy.mode,
            "visible_regime_state": trace.get("visible_regime", {}).get("state"),
        },
        "focus_candidate_artifact_health": focus_health,
        "meta_decision_trace": trace,
        "candidates": _candidate_table(board, max_candidates),
        "agent_contract": {
            "repo_to_agent": "Immutable board, current state, artifact health, visible score tree, and allowed candidate IDs.",
            "agent_to_repo": "A hash-matched agent_decision.json selecting one allowed candidate with confidence and reason.",
            "repo_to_order_plan": "Only activated canonical weights feed rebalance planning, preflight, and any sandbox submission.",
            "self_improvement_rule": "Code changes belong in separate PR/dev cycles and must not alter the same morning decision run.",
            "visibility_rule": "The trace is an auditable rationale tree, not private chain-of-thought.",
        },
    }
    return context


def _candidate_markdown(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "No candidates available."
    rows = []
    headers = ["candidate_id", "eligible", "utility_bps", "expected_alpha_bps", "one_way_turnover", "estimated_cost_bps", "family"]
    rows.append("| " + " | ".join(headers) + " |")
    rows.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for item in candidates:
        rows.append("| " + " | ".join(str(item.get(header, "")) for header in headers) + " |")
    return "\n".join(rows)


def _node_markdown(nodes: list[dict[str, Any]]) -> str:
    if not nodes:
        return "No decision nodes available."
    rows = ["| node | state | value | detail |", "| --- | --- | --- | --- |"]
    for item in nodes:
        rows.append(
            "| "
            + " | ".join(
                str(item.get(key, "")) for key in ["node", "state", "value", "detail"]
            )
            + " |"
        )
    return "\n".join(rows)


def render_agent_memo(context: dict[str, Any]) -> str:
    rails = context["rails"]
    health = context.get("focus_candidate_artifact_health", {})
    trace = context.get("meta_decision_trace", {})
    regime = trace.get("visible_regime", {}) or {}
    score = trace.get("selected_score_breakdown", {}) or {}
    summary = health.get("factor_trend_summary", {}) or {}
    lines = [
        "# Svyable Agent PM Context Pack",
        "",
        f"- Generated: `{context['generated_at']}`",
        f"- Board date: `{context['as_of']}`",
        f"- Candidate hash: `{context['candidate_set_hash']}`",
        f"- Mode: `{context['summary']['mode']}`",
        f"- Visible regime proxy: `{regime.get('state')}` with probabilities `{regime.get('probabilities')}`",
        f"- Eligible candidates: **{context['summary']['eligible_count']} / {context['summary']['candidate_count']}**",
        f"- Planned candidate: `{context['summary'].get('planned_candidate')}`",
        f"- Top eligible candidate: `{context['summary'].get('top_eligible_candidate')}`",
        "",
        "## Hard rails",
    ]
    lines.extend(f"- {rule}" for rule in rails["hard_rules"])
    lines.extend([
        "",
        "## Visible decision tree for focus candidate",
        f"- Selected/focus candidate: `{trace.get('selected_candidate_id')}`",
        f"- Score formula: `{score.get('formula')}`",
        f"- Expected alpha: `{score.get('expected_alpha_bps')}` bps",
        f"- Estimated cost: `{score.get('estimated_cost_bps')}` bps",
        f"- Turnover penalty: `{score.get('turnover_penalty_bps')}` bps",
        f"- Risk penalty: `{score.get('risk_penalty_bps')}` bps",
        f"- Utility: `{score.get('utility_bps')}` bps",
        "",
        _node_markdown(trace.get("selected_decision_nodes", [])),
        "",
        "## Weight provenance",
        f"- Status: `{(trace.get('weight_provenance') or {}).get('status')}`",
        f"- Provenance: {(trace.get('weight_provenance') or {}).get('provenance', 'n/a')}",
        f"- Gross/net/effective N: `{(trace.get('weight_provenance') or {}).get('gross')}` / `{(trace.get('weight_provenance') or {}).get('net')}` / `{(trace.get('weight_provenance') or {}).get('effective_n')}`",
        "",
        "## Allowed candidate IDs",
        ", ".join(f"`{cid}`" for cid in rails["allowed_candidate_ids"]) or "None",
        "",
        "## Focus artifact health",
        f"- Status: `{health.get('status')}`",
        f"- Artifact date: `{health.get('artifact_date')}` expected `{health.get('expected_date')}`",
        f"- Inputs stale: `{health.get('inputs_stale')}`",
        f"- Missing execution columns: `{health.get('missing_execution_columns')}`",
        f"- Factor review: `{summary.get('headline')}`; deteriorating={summary.get('deteriorating')}, watch={summary.get('watch')}, improving={summary.get('improving')}",
        "",
        "## Regime proxy drivers",
    ])
    lines.extend(f"- {driver}" for driver in regime.get("drivers", []))
    lines.extend([
        "",
        "## Top candidates",
        _candidate_markdown(context["candidates"]),
        "",
        "## Required agent output",
        "Write `strategy_selection/agent_decision.json` with exactly:",
        "",
        "```json",
        json.dumps(_decision_template(context), indent=2),
        "```",
    ])
    return "\n".join(lines) + "\n"


def _decision_template(context: dict[str, Any]) -> dict[str, Any]:
    allowed = context["rails"]["allowed_candidate_ids"]
    default = context["summary"].get("top_eligible_candidate") or (allowed[0] if allowed else "hold_current")
    return {
        "as_of": context["as_of"],
        "candidate_set_hash": context["candidate_set_hash"],
        "candidate_id": default,
        "confidence": 0.0,
        "reason": "Choose only an allowed candidate_id after reviewing the context pack and visible decision tree.",
    }


def write_agent_pm_pack(
    output_root: str | Path,
    *,
    board_dir: str | Path | None = None,
    max_candidates: int = 15,
) -> AgentPmPack:
    context = build_agent_context(output_root, board_dir=board_dir, max_candidates=max_candidates)
    board_path = Path(context["board_dir"])
    root = Path(output_root) / "strategy_selection"
    root.mkdir(parents=True, exist_ok=True)

    context_text = json.dumps(context, indent=2, sort_keys=True, default=_json_default)
    memo_text = render_agent_memo(context)
    template_text = json.dumps(_decision_template(context), indent=2, sort_keys=True)

    context_path = board_path / "agent_context.json"
    memo_path = board_path / "agent_pm_memo.md"
    template_path = board_path / "agent_decision_template.json"
    context_path.write_text(context_text)
    memo_path.write_text(memo_text)
    template_path.write_text(template_text)

    # Also copy the latest read-only context to stable paths for external agents.
    (root / "latest_agent_context.json").write_text(context_text)
    (root / "latest_agent_pm_memo.md").write_text(memo_text)
    (root / "agent_decision_template.json").write_text(template_text)

    return AgentPmPack(
        context_path=context_path,
        memo_path=memo_path,
        template_path=template_path,
        board_dir=board_path,
        candidate_set_hash=context["candidate_set_hash"],
        as_of=context["as_of"],
        allowed_candidate_ids=context["rails"]["allowed_candidate_ids"],
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="svyable-agent-pm-harness")
    result.add_argument("--out", default="outputs")
    result.add_argument("--board-dir", default=None)
    result.add_argument("--max-candidates", type=int, default=15)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    pack = write_agent_pm_pack(args.out, board_dir=args.board_dir, max_candidates=args.max_candidates)
    print(json.dumps({
        "status": "ok",
        "context": str(pack.context_path),
        "memo": str(pack.memo_path),
        "decision_template": str(pack.template_path),
        "as_of": pack.as_of,
        "candidate_set_hash": pack.candidate_set_hash,
        "allowed_candidate_ids": pack.allowed_candidate_ids,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
