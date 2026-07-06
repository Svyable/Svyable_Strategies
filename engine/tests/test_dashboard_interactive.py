"""Tests for optional Plotly PM decision charts."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable import dashboard_interactive as interactive
from svyable.strategy_decision_scorecard import (
    best_play,
    build_decision_scorecard,
    decision_reason,
    render_decision_ticket,
)


def _board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "candidate_id": "q23_hybrid_alpha",
                "name": "Q23 Hybrid Alpha",
                "family": "core",
                "eligible": True,
                "utility_bps": 4.2,
                "expected_alpha_bps": 6.1,
                "net_expected_alpha_bps": 5.5,
                "estimated_cost_bps": 0.6,
                "one_way_turnover": 0.05,
                "current_overlap": 0.80,
                "recent_vol": 0.12,
                "recent_max_drawdown": 0.03,
                "sharpe_252d": 1.1,
                "action": "rebalance",
            },
            {
                "candidate_id": "blocked_high_turnover",
                "name": "Blocked High Turnover",
                "family": "stress",
                "eligible": False,
                "utility_bps": 8.0,
                "expected_alpha_bps": 9.0,
                "net_expected_alpha_bps": 7.0,
                "estimated_cost_bps": 2.5,
                "one_way_turnover": 0.60,
                "current_overlap": 0.10,
                "recent_vol": 0.45,
                "recent_max_drawdown": 0.25,
                "sharpe_252d": 0.1,
                "action": "switch",
            },
            {
                "candidate_id": "hold_current",
                "name": "Hold current",
                "family": "baseline",
                "eligible": True,
                "utility_bps": 0.2,
                "expected_alpha_bps": 0.2,
                "net_expected_alpha_bps": 0.2,
                "estimated_cost_bps": 0.0,
                "one_way_turnover": 0.0,
                "current_overlap": 1.0,
                "recent_vol": 0.10,
                "recent_max_drawdown": 0.02,
                "sharpe_252d": 0.5,
                "action": "hold",
            },
        ]
    )


def test_decision_scorecard_labels_best_clean_edge():
    scorecard = build_decision_scorecard(_board())
    top = best_play(scorecard)
    assert top["candidate_id"] == "q23_hybrid_alpha"
    assert top["play_call"] == "GREENLIGHT"
    blocked = scorecard[scorecard["candidate_id"] == "blocked_high_turnover"].iloc[0]
    assert blocked["play_call"] == "BLOCK"
    assert "high turnover" in blocked["risk_flags"]


def test_decision_ticket_includes_rationale_and_rails():
    scorecard = build_decision_scorecard(_board())
    top = best_play(scorecard)
    reason = decision_reason(top)
    ticket = render_decision_ticket(scorecard)
    assert "q23_hybrid_alpha" in reason
    assert "edge versus hold" in reason
    assert "Svyable PM decision ticket" in ticket
    assert "Draft guarded-decision rationale" in ticket
    assert "Only write a guarded decision" in ticket


@pytest.mark.skipif(not interactive.available(), reason="Plotly is not installed")
def test_candidate_ranking_returns_plotly_figure():
    fig = interactive.candidate_ranking(_board(), "utility_bps")
    assert len(fig.data) >= 1
    assert "Candidate ranking" in fig.layout.title.text


@pytest.mark.skipif(not interactive.available(), reason="Plotly is not installed")
def test_alpha_cost_map_has_candidate_points():
    fig = interactive.alpha_cost_map(_board(), highlight="q23_hybrid_alpha")
    assert len(fig.data) >= 1
    assert fig.layout.xaxis.title.text == "One-way turnover (%)"


@pytest.mark.skipif(not interactive.available(), reason="Plotly is not installed")
def test_decision_scorecard_map_has_edge_axis():
    scorecard = build_decision_scorecard(_board())
    fig = interactive.decision_scorecard_map(scorecard)
    assert len(fig.data) >= 1
    assert fig.layout.yaxis.title.text == "Edge versus hold-current utility (bps)"


@pytest.mark.skipif(not interactive.available(), reason="Plotly is not installed")
def test_signed_bar_builds_positive_negative_trace_groups():
    fig = interactive.signed_bar(pd.Series({"a": -0.02, "b": 0.01}), title="Stress", xlabel="Return")
    assert len(fig.data) >= 1
    assert fig.layout.xaxis.title.text == "Return"


@pytest.mark.skipif(not interactive.available(), reason="Plotly is not installed")
def test_matrix_heatmap_builds_heatmap():
    matrix = pd.DataFrame([[0.1, -0.2], [0.0, 0.3]], index=["s1", "s2"], columns=["m1", "m2"])
    fig = interactive.matrix_heatmap(matrix, title="Monthly candidate returns")
    assert len(fig.data) == 1
    assert "Monthly" in fig.layout.title.text


@pytest.mark.skipif(not interactive.available(), reason="Plotly is not installed")
def test_drawdown_tape_builds_traces():
    idx = pd.bdate_range("2026-01-01", periods=4)
    drawdowns = pd.DataFrame({"a": [0.0, -0.01, -0.02, -0.005], "b": [0.0, 0.0, -0.01, -0.02]}, index=idx)
    fig = interactive.drawdown_tape(drawdowns)
    assert len(fig.data) == 2
    assert fig.layout.hovermode == "x unified"


@pytest.mark.skipif(not interactive.available(), reason="Plotly is not installed")
def test_multi_equity_builds_traces():
    idx = pd.bdate_range("2026-01-01", periods=5)
    curves = {
        "q23_hybrid_alpha": pd.Series([0.01, -0.002, 0.003, 0.004, -0.001], index=idx),
        "hold_current": pd.Series([0.002, 0.001, -0.001, 0.002, 0.0], index=idx),
    }
    fig = interactive.multi_equity(curves, highlight="q23_hybrid_alpha")
    assert len(fig.data) == 2
    assert fig.layout.hovermode == "x unified"
