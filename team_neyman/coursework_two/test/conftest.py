import pandas as pd
import pytest


@pytest.fixture
def sample_holdings():
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "currency": "USD",
                "current_shares": 100,
                "total_investment": 15000.0,
                "avg_cost": 150.0,
                "current_price": 160.0,
                "fx_rate": 1.0,
                "current_value": 16000.0,
            }
        ]
    )


@pytest.fixture
def sample_factors():
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "total_score": 0.8,
                "momentum_score": 0.7,
                "fey_score": 0.5,
                "trend_score": 0.6,
                "risk_score": 0.4,
                "liquidity_score": 0.9,
                "gics_sector": "Technology",
                "weight": 0.1,
            }
        ]
    )


@pytest.fixture
def sample_performance_df():
    """Simulates a strategy growing from 100k to 110k over 4 days."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]
            ),
            "net_capital": [100000.0, 102000.0, 101000.0, 110000.0],
            "initial_capital": [100000.0] * 4,
        }
    )


@pytest.fixture
def mock_benchmark_data():
    """Simulates a benchmark (e.g., SPY) for return/volatility tests."""
    return pd.DataFrame(
        {
            "price_date": pd.to_datetime(["2024-12-25", "2025-01-01", "2025-01-04"]),
            "close_price": [100.0, 100.0, 105.0],  # 5% return
            "symbol": ["SPY"] * 3,
        }
    )
