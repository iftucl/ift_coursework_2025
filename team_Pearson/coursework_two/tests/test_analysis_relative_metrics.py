"""Unit tests for CW2 relative performance analysis metrics."""

from __future__ import annotations

import math

import pandas as pd
from team_Pearson.coursework_two.modules.analysis.relative_metrics import (
    compute_capture_metrics,
    compute_relative_metrics,
)


def test_information_ratio_calculation(monkeypatch):
    strategy_returns = _series([0.03, -0.01, 0.02, 0.01])
    universe_returns = _series([0.01, 0.00, 0.01, 0.00])
    secondary_returns = _series([0.02, -0.02, 0.01, 0.01])
    risk_free_returns = _series([0.002, 0.002, 0.002, 0.002])

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.relative_metrics._load_strategy_series",
        lambda run_id, engine: pd.DataFrame(
            {
                "strategy_return": strategy_returns,
                "risk_free_return": risk_free_returns,
                "strategy_nav": (1.0 + strategy_returns).cumprod(),
            }
        ),
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.relative_metrics._load_benchmark_series",
        lambda run_id, engine: {
            "universe_ew": pd.DataFrame(
                {
                    "period_return": universe_returns,
                    "risk_free_return": risk_free_returns,
                    "nav": (1.0 + universe_returns).cumprod(),
                }
            ),
            "SPY": pd.DataFrame(
                {
                    "period_return": secondary_returns,
                    "risk_free_return": risk_free_returns,
                    "nav": (1.0 + secondary_returns).cumprod(),
                }
            ),
        },
    )

    rows = compute_relative_metrics(
        {
            "run_id": "run-1",
            "analysis_config": {
                "primary_benchmark": "SPY",
                "secondary_benchmark": "universe_ew",
            },
        },
        db_engine=None,
    )
    ir = _metric_value(rows, "universe_ew", "information_ratio")

    excess_ann = float((strategy_returns - universe_returns).mean()) * 12.0
    tracking_error = float((strategy_returns - universe_returns).std(ddof=1)) * math.sqrt(12.0)
    expected = excess_ann / tracking_error

    assert ir == pytest_approx(expected)


def test_up_capture_only_computed_for_primary_market_benchmark(monkeypatch):
    strategy_returns = _series([0.03, -0.01, 0.02, 0.01])
    universe_returns = _series([0.01, 0.00, 0.01, 0.00])
    secondary_returns = _series([0.02, -0.02, 0.01, 0.01])
    risk_free_returns = _series([0.002, 0.002, 0.002, 0.002])

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.relative_metrics._load_strategy_series",
        lambda run_id, engine: pd.DataFrame(
            {
                "strategy_return": strategy_returns,
                "risk_free_return": risk_free_returns,
                "strategy_nav": (1.0 + strategy_returns).cumprod(),
            }
        ),
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.relative_metrics._load_benchmark_series",
        lambda run_id, engine: {
            "universe_ew": pd.DataFrame(
                {
                    "period_return": universe_returns,
                    "risk_free_return": risk_free_returns,
                    "nav": (1.0 + universe_returns).cumprod(),
                }
            ),
            "SPY": pd.DataFrame(
                {
                    "period_return": secondary_returns,
                    "risk_free_return": risk_free_returns,
                    "nav": (1.0 + secondary_returns).cumprod(),
                }
            ),
            "static_baseline": pd.DataFrame(
                {
                    "period_return": universe_returns,
                    "risk_free_return": risk_free_returns,
                    "nav": (1.0 + universe_returns).cumprod(),
                }
            ),
        },
    )

    rows = compute_relative_metrics(
        {
            "run_id": "run-1",
            "analysis_config": {
                "primary_benchmark": "SPY",
                "secondary_benchmark": "universe_ew",
            },
        },
        db_engine=None,
    )

    assert _metric_value(rows, "universe_ew", "up_capture_ratio") is None
    assert _metric_value(rows, "static_baseline", "down_capture_ratio") is None
    assert _metric_value(rows, "SPY", "up_capture_ratio") is not None


def test_up_capture_ratio_correct():
    rows = compute_capture_metrics(
        strategy_returns=[0.03, -0.01, 0.04, -0.03],
        benchmark_returns=[0.02, -0.02, 0.01, -0.01],
        run_id="run-1",
        versus_series="SPY",
    )
    up_capture = _metric_value(rows, "SPY", "up_capture_ratio")
    expected = ((0.03 + 0.04) / 2.0) / ((0.02 + 0.01) / 2.0)
    assert up_capture == pytest_approx(expected)


def test_tracking_error_annualized(monkeypatch):
    strategy_returns = _series([0.02, -0.01, 0.01, 0.03])
    universe_returns = _series([0.01, 0.00, 0.00, 0.01])
    risk_free_returns = _series([0.002, 0.002, 0.002, 0.002])

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.relative_metrics._load_strategy_series",
        lambda run_id, engine: pd.DataFrame(
            {
                "strategy_return": strategy_returns,
                "risk_free_return": risk_free_returns,
                "strategy_nav": (1.0 + strategy_returns).cumprod(),
            }
        ),
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.relative_metrics._load_benchmark_series",
        lambda run_id, engine: {
            "universe_ew": pd.DataFrame(
                {
                    "period_return": universe_returns,
                    "risk_free_return": risk_free_returns,
                    "nav": (1.0 + universe_returns).cumprod(),
                }
            )
        },
    )

    rows = compute_relative_metrics(
        {
            "run_id": "run-1",
            "analysis_config": {
                "primary_benchmark": "SPY",
                "secondary_benchmark": "universe_ew",
            },
        },
        db_engine=None,
    )
    te = _metric_value(rows, "universe_ew", "tracking_error")
    expected = float((strategy_returns - universe_returns).std(ddof=1)) * math.sqrt(12.0)
    assert te == pytest_approx(expected)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(
        values,
        index=pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]),
    )


def _metric_value(rows, versus_series: str, metric_name: str):
    for row in rows:
        if row["versus_series"] == versus_series and row["metric_name"] == metric_name:
            unit = row["metric_unit"]
            value = row["metric_value"]
            if unit == "%":
                return float(value) / 100.0
            return float(value)
    return None


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value, rel=1e-6, abs=1e-8)
