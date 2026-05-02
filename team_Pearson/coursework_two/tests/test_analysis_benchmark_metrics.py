from __future__ import annotations

import pandas as pd
import pytest
from team_Pearson.coursework_two.modules.analysis.benchmark_metrics import (
    compute_benchmark_absolute_metrics,
)


def test_compute_benchmark_absolute_metrics_returns_expected_rows():
    rows = compute_benchmark_absolute_metrics(
        [
            {
                "run_id": "run-1",
                "execution_date": "2026-01-01",
                "period_end_date": "2026-01-31",
                "series_name": "SPY",
                "nav": 1.02,
                "period_return": 0.02,
                "risk_free_return": 0.002,
            },
            {
                "run_id": "run-1",
                "execution_date": "2026-02-01",
                "period_end_date": "2026-02-28",
                "series_name": "SPY",
                "nav": 1.05,
                "period_return": 0.0294117647,
                "risk_free_return": 0.002,
            },
            {
                "run_id": "run-1",
                "execution_date": "2026-03-01",
                "period_end_date": "2026-03-31",
                "series_name": "SPY",
                "nav": 1.00,
                "period_return": -0.0476190476,
                "risk_free_return": 0.002,
            },
        ]
    )

    lookup = {(row["series_name"], row["metric_name"]): row for row in rows}
    assert lookup[("SPY", "total_return")]["metric_value"] == 0.0
    assert lookup[("SPY", "max_drawdown")]["metric_value"] > 4.0
    assert lookup[("SPY", "annualized_volatility")]["metric_value"] is not None
    assert lookup[("SPY", "sortino_ratio")]["metric_unit"] == "x"
    assert ("SPY", "calmar_ratio") not in lookup


def test_compute_benchmark_absolute_metrics_accepts_dataframe_without_run_id():
    df = pd.DataFrame(
        {
            "period_end_date": pd.to_datetime(["2026-01-31", "2026-02-28"]),
            "series_name": ["static_baseline", "static_baseline"],
            "nav": [1.01, 1.03],
            "period_return": [0.01, 0.0198019802],
            "risk_free_return": [0.001, 0.001],
        }
    )

    rows = compute_benchmark_absolute_metrics(df)

    assert rows
    assert all("run_id" not in row for row in rows)
    assert {row["metric_name"] for row in rows} >= {
        "annualized_return",
        "sharpe_ratio",
        "max_drawdown",
    }


def test_compute_benchmark_absolute_metrics_includes_static_execution_metrics():
    rows = compute_benchmark_absolute_metrics(
        [
            {
                "run_id": "run-1",
                "execution_date": "2026-01-01",
                "period_end_date": "2026-01-31",
                "series_name": "static_baseline",
                "nav": 1.01895,
                "period_return": 0.01895,
                "gross_return": 0.02,
                "risk_free_return": 0.002,
                "turnover": 0.20,
                "gross_turnover": 0.40,
                "transaction_cost": 0.0010,
            },
            {
                "run_id": "run-1",
                "execution_date": "2026-02-01",
                "period_end_date": "2026-02-28",
                "series_name": "static_baseline",
                "nav": 1.031164635,
                "period_return": 0.0119875,
                "gross_return": 0.0125,
                "risk_free_return": 0.002,
                "turnover": 0.15,
                "gross_turnover": 0.30,
                "transaction_cost": 0.0005,
            },
        ]
    )

    lookup = {(row["series_name"], row["metric_name"]): row for row in rows}
    assert lookup[("static_baseline", "avg_monthly_turnover_one_way")]["metric_value"] == 17.5
    assert lookup[("static_baseline", "avg_monthly_turnover_two_way")]["metric_value"] == 35.0
    assert lookup[("static_baseline", "annualized_turnover_ratio_one_way")][
        "metric_value"
    ] == pytest.approx(210.0)
    assert lookup[("static_baseline", "avg_transaction_cost_bps")]["metric_value"] == 7.5
    assert lookup[("static_baseline", "total_cost_drag")]["metric_value"] is not None
