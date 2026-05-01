"""Unit tests for CW2 analysis scorecard criteria."""

from __future__ import annotations

import pandas as pd
from team_Pearson.coursework_two.modules.analysis.scorecard import (
    _compute_baseline_stats,
    compute_scorecard,
)


def test_criterion_1_passes_when_positive_excess_return(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_relative_metric_lookup",
        lambda conn, run_id: {("SPY", "excess_return_annualized"): 1.5},
    )

    rows = compute_scorecard(
        None,
        "run-1",
        config={"backtest": {"analysis": {"primary_benchmark": "SPY"}}},
    )
    assert _criterion(rows, 1)["passed"] is True


def test_criterion_1_fails_when_negative_excess_return(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_relative_metric_lookup",
        lambda conn, run_id: {("SPY", "excess_return_annualized"): -0.5},
    )

    rows = compute_scorecard(
        None,
        "run-1",
        config={"backtest": {"analysis": {"primary_benchmark": "SPY"}}},
    )
    assert _criterion(rows, 1)["passed"] is False


def test_criterion_3_requires_two_of_three(monkeypatch):
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_metric_lookup",
        lambda conn, run_id: {
            ("risk_adjusted", "sharpe_ratio"): 0.90,
            ("risk_adjusted", "sortino_ratio"): 0.80,
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_relative_metric_lookup",
        lambda conn, run_id: {
            ("SPY", "excess_return_annualized"): 1.0,
            ("SPY", "information_ratio"): 0.10,
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_regime_lookup",
        lambda conn, run_id: {},
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._compute_baseline_stats",
        lambda conn, run_id, primary_benchmark: {
            "sharpe": 0.80,
            "sortino": 0.85,
            "information_ratio_vs_primary": 0.20,
        },
    )

    rows = compute_scorecard(
        None,
        "run-1",
        config={"backtest": {"analysis": {"primary_benchmark": "SPY"}}},
    )
    assert _criterion(rows, 3)["passed"] is False


def test_criterion_4_skipped_when_no_robustness_run(monkeypatch):
    _patch_common(monkeypatch)
    rows = compute_scorecard(
        None,
        "run-1",
        config={"backtest": {"analysis": {"primary_benchmark": "SPY"}}},
    )
    assert _criterion(rows, 4)["passed"] is None


def test_criterion_5_uses_stress_regime_only(monkeypatch):
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_metric_lookup",
        lambda conn, run_id: {
            ("risk_adjusted", "sharpe_ratio"): 1.0,
            ("risk_adjusted", "sortino_ratio"): 1.1,
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_relative_metric_lookup",
        lambda conn, run_id: {
            ("SPY", "excess_return_annualized"): 2.0,
            ("SPY", "information_ratio"): 0.4,
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_regime_lookup",
        lambda conn, run_id: {
            ("normal", "static_baseline"): {
                "strategy_max_dd": 12.0,
                "versus_max_dd": 10.0,
                "excess_ann_return": -3.0,
            },
            ("stress", "static_baseline"): {
                "strategy_max_dd": 8.0,
                "versus_max_dd": 9.0,
                "excess_ann_return": 1.5,
            },
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._compute_baseline_stats",
        lambda conn, run_id, primary_benchmark: {
            "sharpe": 0.5,
            "sortino": 0.6,
            "information_ratio_vs_primary": 0.1,
        },
    )

    rows = compute_scorecard(
        None,
        "run-1",
        config={"backtest": {"analysis": {"primary_benchmark": "SPY"}}},
    )
    assert _criterion(rows, 5)["passed"] is True


def test_compute_baseline_stats_uses_risk_free_adjusted_sharpe_and_sortino(
    monkeypatch,
):
    idx = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"], errors="coerce")
    static_baseline = pd.DataFrame(
        {
            "period_return": [0.020, 0.015, -0.010, 0.012],
            "risk_free_return": [0.006, 0.006, 0.006, 0.006],
        },
        index=idx,
    )
    spy = pd.DataFrame(
        {
            "period_return": [0.010, 0.011, -0.006, 0.009],
            "risk_free_return": [0.006, 0.006, 0.006, 0.006],
        },
        index=idx,
    )

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_benchmark_returns",
        lambda conn, run_id, series_name: (
            static_baseline if series_name == "static_baseline" else spy
        ),
    )

    stats = _compute_baseline_stats(None, "run-1", "SPY")

    assert stats["sharpe"] is not None
    assert stats["sortino"] is not None
    assert stats["information_ratio_vs_primary"] is not None
    assert round(float(stats["sharpe"]), 6) == round(0.8496348918530832, 6)
    assert round(float(stats["sortino"]), 6) == round(1.407291281149713, 6)
    assert round(float(stats["information_ratio_vs_primary"]), 6) == round(1.9623029611638478, 6)


def _patch_common(monkeypatch):
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_metric_lookup",
        lambda conn, run_id: {
            ("risk_adjusted", "sharpe_ratio"): 1.0,
            ("risk_adjusted", "sortino_ratio"): 1.0,
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_relative_metric_lookup",
        lambda conn, run_id: {
            ("SPY", "excess_return_annualized"): 1.0,
            ("SPY", "information_ratio"): 0.4,
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._load_regime_lookup",
        lambda conn, run_id: {},
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.scorecard._compute_baseline_stats",
        lambda conn, run_id, primary_benchmark: {
            "sharpe": 0.5,
            "sortino": 0.5,
            "information_ratio_vs_primary": 0.2,
        },
    )


def _criterion(rows, criterion_id: int):
    for row in rows:
        if int(row["criterion_id"]) == int(criterion_id):
            return row
    raise AssertionError(f"criterion {criterion_id} not found")
