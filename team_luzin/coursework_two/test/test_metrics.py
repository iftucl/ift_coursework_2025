import pandas as pd

from modules.metrics import evaluate_strategy


def test_evaluate_strategy_returns_summary_metrics():
    strategy_returns = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
            "strategy_return": [0.01, 0.02, -0.01],
        }
    )
    benchmarks = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
            "equal_weight_universe": [0.005, 0.01, -0.005],
        }
    )

    summary = evaluate_strategy(strategy_returns, benchmarks, {})

    assert "strategy" in summary["series"].tolist()
    assert "equal_weight_universe" in summary["series"].tolist()
    expected_columns = {
        "sortino_ratio",
        "calmar_ratio",
        "downside_deviation",
        "average_monthly_return",
        "median_monthly_return",
        "best_month",
        "worst_month",
        "positive_month_ratio",
    }
    assert expected_columns.issubset(set(summary.columns))
