from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture
def mock_engine(monkeypatch):
    """
    Standardized mock for the SQLAlchemy engine.
    Mocks the context manager so 'with engine.connect() as conn' works in tests.
    """
    mock = MagicMock()

    mock_conn = MagicMock()
    mock.connect.return_value.__enter__.return_value = mock_conn
    mock.begin.return_value.__enter__.return_value = mock_conn

    monkeypatch.setattr("a_pipeline.modules.db_loader.postgres.engine", mock)
    return mock


@pytest.fixture
def sample_eps_data():
    """Provides a standardized DataFrame for testing EPS deduplication and upserts."""
    return pd.DataFrame(
        {
            "estimate_date": ["2024-03-12", "2024-03-12"],
            "symbol": ["AAPL", "AAPL"],
            "period": ["Current Year", "Current Year"],
            "period_end_date": ["2024-12-31", "2024-12-31"],
            "consensus_eps": [3.50, 3.55],
            "recent_eps": [3.40, 3.45],
            "estimate_count": [10, 10],
            "estimate_high": [3.60, 3.65],
            "estimate_low": [3.30, 3.35],
            "year_ago_eps": [3.00, 3.00],
        }
    )


@pytest.fixture
def sample_price_data():
    """Standardized OHLCV data for factor math and pipeline cleaning tests."""
    return pd.DataFrame(
        {
            "symbol": ["AAPL"] * 5,
            "price_date": pd.date_range("2024-01-01", periods=5),
            "open_price": [99.0, 101.0, 100.0, 104.0, 109.0],
            "high_price": [101.0, 103.0, 102.0, 106.0, 111.0],
            "low_price": [98.0, 100.0, 99.0, 103.0, 108.0],
            "close_price": [100.0, 102.0, 101.0, 105.0, 110.0],
            "volume": [1000, 1100, 900, 1200, 1500],
        }
    )
