import pandas as pd

from modules.backtest import run_monthly_backtest


def test_run_monthly_backtest_applies_initial_transaction_cost():
    portfolio = pd.DataFrame({"symbol": ["AAA", "BBB"], "weight": [0.5, 0.5]})
    price_history = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "BBB", "BBB", "BBB"],
            "date": pd.to_datetime(
                ["2025-01-31", "2025-02-28", "2025-03-31", "2025-01-31", "2025-02-28", "2025-03-31"]
            ),
            "close": [100, 110, 121, 100, 100, 100],
        }
    )
    config = {"costs": {"transaction_cost_bps": 10}}

    results = run_monthly_backtest(portfolio, price_history, config)

    first_valid = results.returns.iloc[0]
    assert round(first_valid["turnover"], 4) == 1.0
    assert round(first_valid["transaction_cost"], 4) == 0.001


def test_run_monthly_backtest_supports_quarterly_rebalance_frequency():
    portfolio = pd.DataFrame({"symbol": ["AAA"], "weight": [1.0]})
    price_history = pd.DataFrame(
        {
            "symbol": ["AAA"] * 6,
            "date": pd.to_datetime(
                ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-31", "2025-06-30"]
            ),
            "close": [100, 105, 110, 115, 120, 125],
        }
    )
    config = {"backtest": {"rebalance_freq": "quarterly"}, "costs": {"transaction_cost_bps": 10}}

    results = run_monthly_backtest(portfolio, price_history, config)

    assert results.returns["date"].dt.month.tolist() == [3, 6]
