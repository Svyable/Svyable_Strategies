"""Tests for the ported analytics/agent dashboard helpers.

These cover the pure data + figure-building logic (no Streamlit runtime), which
is where the Q23 → Svyable port could silently break.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matplotlib.figure import Figure

from svyable import dashboard_charts as charts
from svyable.dashboard_analytics import _period_return, _rolling_frame
from svyable.dashboard_data import (
    clean_returns,
    load_candidate_returns,
    load_candidate_weights,
    numeric_timeseries,
)
from svyable.dashboard_factors import _combined_factor_health
from svyable.dashboard_positions import (
    position_analytics,
    position_pnl,
    target_vs_actual,
)


def _book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            dict(symbol="AMD", quantity=100, mark=110.0, market_value=11000.0, average_open_price=100.0, realized_today=5.0),
            dict(symbol="AMAT", quantity=50, mark=90.0, market_value=4500.0, average_open_price=100.0, realized_today=0.0),
        ]
    )


@pytest.fixture
def returns() -> pd.Series:
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2022-01-03", periods=400)
    return pd.Series(rng.normal(0.0004, 0.01, len(idx)), index=idx)


def _pnl_frame(returns: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame({"net_ret": returns.values}, index=returns.index.strftime("%Y-%m-%d"))
    frame["turnover"] = 0.05
    frame["gross_exposure"] = 1.0
    return frame


def test_returns_from_pnl_parses_string_index(returns):
    parsed = clean_returns(_pnl_frame(returns))
    assert isinstance(parsed.index, pd.DatetimeIndex)
    assert len(parsed) == len(returns)


def test_returns_from_pnl_empty_when_no_net_ret():
    assert clean_returns(pd.DataFrame({"x": [1, 2]})).empty


def test_rolling_frame_has_sharpe_and_vol(returns):
    frame = _rolling_frame(returns, 63)
    assert list(frame.columns) == ["rolling_sharpe", "rolling_vol"]
    assert not frame.empty
    assert frame["rolling_vol"].ge(0).all()


def test_period_return_compounds(returns):
    total = _period_return(returns, returns.index[0])
    expected = float((1.0 + returns).prod() - 1.0)
    assert total == pytest.approx(expected)


def test_period_return_nan_when_window_empty(returns):
    future = returns.index[-1] + pd.Timedelta(days=30)
    assert np.isnan(_period_return(returns, future))


def test_weights_frame_coerces_numeric():
    raw = pd.DataFrame({"AAPL": [0.1, 0.2], "MSFT": ["0.3", "x"]}, index=["2022-01-03", "2022-01-04"])
    frame = numeric_timeseries(raw)
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.loc[frame.index[1], "MSFT"] == 0.0  # non-numeric -> 0


@pytest.mark.parametrize(
    "builder",
    [
        charts.cumulative_return_chart,
        charts.drawdown_chart,
        charts.return_distribution_chart,
        charts.monthly_returns_heatmap,
        charts.calendar_heatmap,
    ],
)
def test_single_series_charts_return_figures(returns, builder):
    fig = builder(returns)
    assert isinstance(fig, Figure)


def test_rolling_and_ranking_charts(returns):
    rolling = _rolling_frame(returns, 63)
    assert isinstance(charts.rolling_metrics_chart(rolling, ["rolling_sharpe"]), Figure)
    board = pd.DataFrame(
        {
            "candidate_id": ["hold_current", "q23_a", "q23_b"],
            "utility_bps": [5.0, -3.0, 1.0],
            "expected_alpha_bps": [5.0, 6.0, 5.5],
            "one_way_turnover": [0.0, 0.15, 0.08],
            "eligible": [True, False, True],
        }
    )
    assert isinstance(charts.candidate_ranking_chart(board, "utility_bps"), Figure)
    assert isinstance(charts.alpha_vs_cost_scatter(board), Figure)


def test_multi_equity_chart_skips_empty(returns):
    curves = {"a": returns, "b": pd.Series(dtype=float)}
    assert isinstance(charts.multi_equity_chart(curves, highlight="a"), Figure)


def _full_frontier_board(n: int = 20) -> pd.DataFrame:
    families = ["momentum", "reversal", "defensive", "flow", "behavioral", "trend"]
    return pd.DataFrame(
        {
            "candidate_id": ["hold_current"] + [f"q23_s{i}" for i in range(1, n)],
            "family": ["no-trade baseline"] + [families[i % len(families)] for i in range(1, n)],
            "one_way_turnover": [0.0] + [0.05 + 0.005 * i for i in range(1, n)],
            "expected_alpha_bps": [0.0] + [2.0 + 0.2 * i for i in range(1, n)],
            "net_expected_alpha_bps": [0.0] + [1.0 + 0.2 * i for i in range(1, n)],
            "utility_bps": [0.0] + [-40.0 + 2.0 * i for i in range(1, n)],
            "eligible": [True] + [bool(i % 4) for i in range(1, n)],
        }
    )


def test_categorical_colors_are_stable_and_distinct():
    labels = ["momentum", "reversal", "defensive", "reversal"]
    first = charts.categorical_colors(labels)
    second = charts.categorical_colors(list(reversed(labels)))
    assert first == second  # deterministic regardless of input order
    assert len(first) == 3  # one color per distinct label
    assert len(set(first.values())) == 3  # colors are distinct


def test_categorical_colors_scale_past_twenty():
    labels = [f"strat_{i}" for i in range(30)]
    colors = charts.categorical_colors(labels)
    assert len(colors) == 30
    assert len(set(colors.values())) >= 25  # continuous colormap keeps them distinct


def test_alpha_vs_cost_scatter_plots_every_candidate():
    board = _full_frontier_board(20)
    fig = charts.alpha_vs_cost_scatter(board, highlight="q23_s3")
    plotted = sum(len(coll.get_offsets()) for coll in fig.axes[0].collections)
    # Every one of the 20 candidates is drawn (plus a highlight ring for the held one).
    assert plotted >= 20


def test_alpha_vs_cost_scatter_handles_empty_board():
    assert isinstance(charts.alpha_vs_cost_scatter(pd.DataFrame()), Figure)


def test_alpha_vs_cost_scatter_coerces_non_finite_coordinates():
    board = _full_frontier_board(6)
    board.loc[2, "one_way_turnover"] = None
    board.loc[3, "expected_alpha_bps"] = float("nan")
    fig = charts.alpha_vs_cost_scatter(board)
    plotted = sum(len(coll.get_offsets()) for coll in fig.axes[0].collections)
    assert plotted >= 6  # no candidate silently dropped for a missing coordinate


def test_candidate_ranking_chart_draws_a_bar_per_candidate():
    board = _full_frontier_board(20)
    fig = charts.candidate_ranking_chart(board, "utility_bps")
    assert len(fig.axes[0].patches) == 20


def test_candidate_returns_loads_from_output_dir(tmp_path, returns):
    root = tmp_path / "outputs"
    run = root / "candidate_q23_a" / "20260101_000000"
    run.mkdir(parents=True)
    _pnl_frame(returns).to_csv(run / "pnl_diag.csv")
    board = pd.DataFrame(
        {
            "candidate_id": ["q23_a"],
            "strategy_id": ["q23_a"],
            "output_dir": ["candidate_q23_a/20260101_000000"],
        }
    )
    curves = load_candidate_returns(root, board)
    assert "q23_a" in curves
    assert isinstance(curves["q23_a"].index, pd.DatetimeIndex)


def test_candidate_returns_glob_fallback(tmp_path, returns):
    root = tmp_path / "outputs"
    run = root / "candidate_q23_b" / "20260101_000000"
    run.mkdir(parents=True)
    _pnl_frame(returns).to_csv(run / "pnl_diag.csv")
    board = pd.DataFrame(
        {"candidate_id": ["q23_b"], "strategy_id": ["q23_b"], "output_dir": [""]}
    )
    curves = load_candidate_returns(root, board)
    assert "q23_b" in curves


def _health(**cols) -> pd.DataFrame:
    frame = pd.DataFrame(cols)
    return frame.set_index("factor")


def test_combined_factor_health_labels_sleeve_and_dedupes_horizon():
    health = {
        "momentum": _health(
            factor=["mom_12_1", "mom_12_1", "breakout"],
            horizon=[21, 63, 21],
            ic_ir=[2.9, 4.4, 0.7],
        ),
        "defensive": _health(factor=["low_beta"], horizon=[21], ic_ir=[-1.2]),
    }
    combined = _combined_factor_health(health)
    # 3 unique factors, shortest horizon kept for mom_12_1
    assert combined["factor"].nunique() == 3
    mom = combined[combined["factor"] == "mom_12_1"].iloc[0]
    assert mom["horizon"] == 21
    assert set(combined["sleeve"]) == {"momentum", "defensive"}


def test_combined_factor_health_empty():
    assert _combined_factor_health({}).empty
    assert _combined_factor_health({"x": pd.DataFrame()}).empty


def test_signed_bar_and_sleeve_area_charts():
    values = pd.Series({"momentum": 2.4, "defensive": -1.3, "meanrev": 0.4})
    assert isinstance(charts.signed_bar_chart(values, title="IC-IR"), Figure)
    idx = pd.bdate_range("2022-01-03", periods=50)
    sleeves = pd.DataFrame(
        {"momentum": 0.7, "defensive": 0.1, "meanrev": 0.1, "micro": 0.1},
        index=idx.strftime("%Y-%m-%d"),
    )
    assert isinstance(charts.sleeve_trust_area_chart(sleeves), Figure)


def test_position_pnl_computes_unrealized():
    frame = position_pnl(_book())
    amd = frame[frame["symbol"] == "AMD"].iloc[0]
    assert amd["unrealized_pl"] == pytest.approx(1000.0)  # (110-100)*100
    amat = frame[frame["symbol"] == "AMAT"].iloc[0]
    assert amat["unrealized_pl"] == pytest.approx(-500.0)  # (90-100)*50
    assert frame["book_weight"].sum() == pytest.approx(1.0)


def test_position_pnl_empty_passthrough():
    assert position_pnl(pd.DataFrame()).empty


def test_position_analytics_rollup():
    stats = position_analytics(_book())
    assert stats["positions"] == 2
    assert stats["gross_exposure"] == pytest.approx(15500.0)
    assert stats["net_exposure"] == pytest.approx(15500.0)
    assert stats["short_exposure"] == pytest.approx(0.0)
    assert stats["unrealized_pl"] == pytest.approx(500.0)  # 1000 - 500
    assert stats["realized_today"] == pytest.approx(5.0)
    assert 1.0 <= stats["effective_n"] <= 2.0


def test_position_analytics_empty():
    assert position_analytics(pd.DataFrame()) == {}


def test_target_vs_actual_nav_normalized_is_honest():
    targets = pd.Series({"AMD": 0.048, "INTC": 0.048})
    table = target_vs_actual(_book(), targets, net_liq=1_000_000)
    # actual is fraction of NAV, so tiny book -> tiny actual weights
    assert table["actual_weight"].sum() == pytest.approx(15500.0 / 1_000_000)
    # INTC targeted but not held -> negative drift equal to -target
    assert table.loc["INTC", "drift"] == pytest.approx(-0.048)
    # sorted by |drift| descending
    assert table["drift"].abs().is_monotonic_decreasing


def test_target_vs_actual_gross_fallback_without_net_liq():
    targets = pd.Series({"AMD": 0.5, "AMAT": 0.5})
    table = target_vs_actual(_book(), targets)
    assert table["actual_weight"].sum() == pytest.approx(1.0)


def test_target_vs_actual_flags_off_target_holdings():
    targets = pd.Series({"NVDA": 1.0})  # book holds AMD/AMAT, none targeted
    table = target_vs_actual(_book(), targets, net_liq=100000)
    assert "NVDA" in table.index and "AMD" in table.index
    assert table.loc["AMD", "target_weight"] == 0.0


def _two_curves():
    idx = pd.bdate_range("2022-01-03", periods=300)
    rng = np.random.default_rng(11)
    a = pd.Series(rng.normal(0.0006, 0.010, len(idx)), index=idx)
    b = pd.Series(rng.normal(0.0002, 0.013, len(idx)), index=idx)
    return {"alpha": a, "beta": b}


def test_metrics_matrix_scores_each_strategy():
    from svyable.dashboard_compare import metrics_matrix

    matrix = metrics_matrix(_two_curves())
    assert set(matrix.index) == {"alpha", "beta"}
    for col in ("ann_return", "ann_vol", "sharpe", "max_dd"):
        assert col in matrix.columns
    # sorted by sharpe descending
    assert matrix["sharpe"].is_monotonic_decreasing


def test_metrics_matrix_enriches_from_registry():
    from svyable.dashboard_compare import metrics_matrix

    registry = pd.DataFrame(
        {"family": ["momentum"], "regime_profile": ["balanced"]}, index=["alpha"]
    )
    matrix = metrics_matrix(_two_curves(), registry)
    assert matrix.loc["alpha", "family"] == "momentum"
    assert pd.isna(matrix.loc["beta", "family"])  # not in registry


def test_metrics_matrix_skips_short_history():
    from svyable.dashboard_compare import metrics_matrix

    short = pd.Series([0.01, -0.01], index=pd.bdate_range("2022-01-03", periods=2))
    assert metrics_matrix({"tiny": short}).empty


def test_correlation_matrix_and_average():
    from svyable.dashboard_compare import average_pairwise_correlation, correlation_matrix

    curves = _two_curves()
    corr = correlation_matrix(curves)
    assert corr.shape == (2, 2)
    assert corr.loc["alpha", "alpha"] == pytest.approx(1.0)
    avg = average_pairwise_correlation(corr)
    assert -1.0 <= avg <= 1.0
    assert avg == pytest.approx(corr.loc["alpha", "beta"])  # only one off-diagonal pair


def test_correlation_matrix_needs_two_series():
    from svyable.dashboard_compare import correlation_matrix

    assert correlation_matrix({"only": _two_curves()["alpha"]}).empty


def test_relative_performance_zero_against_self():
    from svyable.dashboard_compare import relative_performance

    a = _two_curves()["alpha"]
    spread = relative_performance(a, a)
    assert (spread.abs() < 1e-9).all()


def test_rolling_correlation_length():
    from svyable.dashboard_compare import rolling_correlation

    curves = _two_curves()
    roll = rolling_correlation(curves["alpha"], curves["beta"], window=63)
    assert len(roll) == 300 - 63 + 1  # first full window yields one value


def test_aligned_returns_inner_join():
    from svyable.dashboard_compare import aligned_returns

    idx1 = pd.bdate_range("2022-01-03", periods=100)
    idx2 = pd.bdate_range("2022-02-01", periods=100)
    curves = {"a": pd.Series(0.01, index=idx1), "b": pd.Series(0.01, index=idx2)}
    frame = aligned_returns(curves)
    assert list(frame.columns) == ["a", "b"]
    assert frame.index.min() >= idx2.min()  # inner join


def _wh() -> pd.DataFrame:
    idx = pd.bdate_range("2022-01-03", periods=100).strftime("%Y-%m-%d")
    frame = pd.DataFrame(index=idx)
    frame["AAA"] = 0.4          # always held
    frame["BBB"] = 0.3          # always held
    frame["CCC"] = [0.3 if i % 2 else 0.0 for i in range(100)]  # held half the time
    frame["DDD"] = 0.0          # never held
    return frame


def test_weights_matrix_datetime_and_numeric():
    from svyable.dashboard_stack import weights_matrix

    m = weights_matrix(_wh())
    assert isinstance(m.index, pd.DatetimeIndex)
    assert m.shape == (100, 4)


def test_participation_frequency_ranks_consistency():
    from svyable.dashboard_stack import participation_frequency, weights_matrix

    freq = participation_frequency(weights_matrix(_wh()))
    assert freq["AAA"] == pytest.approx(1.0)
    assert freq["CCC"] == pytest.approx(0.5, abs=0.02)
    assert "DDD" not in freq.index  # never held is dropped
    assert freq.is_monotonic_decreasing


def test_cash_exposure_complements_gross():
    from svyable.dashboard_stack import cash_exposure, weights_matrix

    cash = cash_exposure(weights_matrix(_wh()))
    # gross when CCC held = 1.0 -> cash 0; when not held = 0.7 -> cash 0.3
    assert set(cash.columns) == {"invested", "cash"}
    assert (cash["invested"] + cash["cash"]).round(6).eq(1.0).all()
    assert cash["cash"].max() == pytest.approx(0.3, abs=1e-6)


def test_top_names_matrix_keeps_biggest():
    from svyable.dashboard_stack import top_names_matrix, weights_matrix

    trimmed = top_names_matrix(weights_matrix(_wh()), top_n=2, tail_days=100)
    assert list(trimmed.columns) == ["AAA", "BBB"]  # largest peak weights


def test_jaccard_overlap_identical_and_disjoint():
    from svyable.dashboard_stack import jaccard_overlap

    a = pd.Series({"X": 0.5, "Y": 0.5})
    assert jaccard_overlap(a, a) == pytest.approx(1.0)
    b = pd.Series({"Z": 1.0})
    assert jaccard_overlap(a, b) == pytest.approx(0.0)
    c = pd.Series({"X": 0.5, "Z": 0.5})  # shares X only: 1/3
    assert jaccard_overlap(a, c) == pytest.approx(1 / 3)


def test_overlap_matrix_symmetric_with_unit_diagonal():
    from svyable.dashboard_stack import overlap_matrix

    books = {
        "a": pd.Series({"X": 0.5, "Y": 0.5}),
        "b": pd.Series({"X": 0.5, "Z": 0.5}),
        "c": pd.Series({"Q": 1.0}),
    }
    table = overlap_matrix(books)
    assert table.shape == (3, 3)
    assert list(table.values.diagonal()) == pytest.approx([1.0, 1.0, 1.0])
    assert table.loc["a", "b"] == table.loc["b", "a"]  # symmetric
    assert table.loc["a", "c"] == pytest.approx(0.0)


def test_candidate_latest_weights_loads(tmp_path):
    from svyable.dashboard_data import load_candidate_weights

    root = tmp_path / "outputs"
    run = root / "candidate_q23_a" / "20260101_000000"
    run.mkdir(parents=True)
    pd.DataFrame({"weight": [0.6, 0.4]}, index=["AAA", "BBB"]).to_csv(run / "weights_today.csv")
    board = pd.DataFrame({"candidate_id": ["q23_a"], "strategy_id": ["q23_a"], "output_dir": [""]})
    books = load_candidate_weights(root, board)
    assert "q23_a" in books
    assert books["q23_a"].sum() == pytest.approx(1.0)
