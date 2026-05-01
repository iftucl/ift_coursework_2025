"""
Pytest fixtures for CW1 Value + Sentiment pipeline tests.
"""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_price_df():
    """Sample Yahoo Finance price DataFrame for testing."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {
            "Open": [150.0, 151.5, 149.0],
            "High": [152.0, 153.0, 151.0],
            "Low": [149.0, 150.0, 148.0],
            "Close": [151.0, 152.0, 150.0],
            "Adj Close": [150.5, 151.5, 149.5],
            "Volume": [1000000, 1100000, 950000],
        },
        index=idx,
    )


@pytest.fixture
def sample_price_df_with_nans():
    """Price DataFrame containing NaN values for edge-case testing."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {
            "Open": [150.0, np.nan],
            "High": [152.0, 153.0],
            "Low": [np.nan, 150.0],
            "Close": [151.0, np.nan],
            "Adj Close": [150.5, np.nan],
            "Volume": [1000000, np.nan],
        },
        index=idx,
    )


@pytest.fixture
def sample_fx_df():
    """Sample FX rate DataFrame for testing."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {
            "Open": [1.2650, 1.2700],
            "High": [1.2700, 1.2750],
            "Low": [1.2600, 1.2650],
            "Close": [1.2680, 1.2720],
        },
        index=idx,
    )


@pytest.fixture
def sample_company_infos():
    """List of company info dicts from fetch_company_info.

    Note: yfinance returns dividendYield and debtToEquity as PERCENTAGES.
    E.g. dividend_yield=0.5 means 0.5%, debt_equity=150 means 150%.
    The value_scorer converts both by dividing by 100.
    """
    return [
        {
            "symbol": "AAPL",
            "pe_ratio": 28.5,
            "pb_ratio": 40.1,
            "ev_ebitda": 22.0,
            "dividend_yield": 0.5,  # 0.5% from yfinance → 0.005 after /100
            "debt_equity": 150.0,  # 150% from yfinance → 1.5 after /100
        },
        {
            "symbol": "MSFT",
            "pe_ratio": 35.0,
            "pb_ratio": 12.3,
            "ev_ebitda": 25.0,
            "dividend_yield": 0.8,  # 0.8% from yfinance → 0.008 after /100
            "debt_equity": 50.0,  # 50% from yfinance → 0.5 after /100
        },
        {
            "symbol": "JPM",
            "pe_ratio": 12.0,
            "pb_ratio": 1.8,
            "ev_ebitda": 8.0,
            "dividend_yield": 2.5,  # 2.5% from yfinance → 0.025 after /100
            "debt_equity": 250.0,  # 250% from yfinance → 2.5 after /100
        },
        {
            "symbol": "XOM",
            "pe_ratio": 15.0,
            "pb_ratio": 2.1,
            "ev_ebitda": 6.5,
            "dividend_yield": 3.5,  # 3.5% from yfinance → 0.035 after /100
            "debt_equity": 30.0,  # 30% from yfinance → 0.3 after /100
        },
    ]


@pytest.fixture
def sample_articles():
    """Sample news article dicts for sentiment testing."""
    return [
        {
            "headline": "Apple posts record quarterly revenue, beating analyst expectations",
            "company_id": "AAPL",
            "source": "gdelt",
        },
        {"headline": "Apple faces antitrust probe in European Union", "company_id": "AAPL", "source": "gdelt"},
        {"headline": "Apple announces new product line for 2025", "company_id": "AAPL", "source": "yahoo_finance"},
    ]


@pytest.fixture
def sample_value_records():
    """Value metric records for composite scoring tests."""
    return [
        {"company_id": "AAPL", "value_score": 65.0, "debt_equity": 1.5},
        {"company_id": "MSFT", "value_score": 45.0, "debt_equity": 0.5},
        {"company_id": "XOM", "value_score": 80.0, "debt_equity": 0.3},
        {"company_id": "JPM", "value_score": 55.0, "debt_equity": 2.5},
    ]


@pytest.fixture
def sample_sentiment_records():
    """Sentiment score records for composite scoring tests."""
    return [
        {"company_id": "AAPL", "sentiment_score": 72.0, "avg_sentiment": 0.15, "total_articles": 10},
        {"company_id": "MSFT", "sentiment_score": 60.0, "avg_sentiment": 0.05, "total_articles": 8},
        {"company_id": "XOM", "sentiment_score": 55.0, "avg_sentiment": 0.02, "total_articles": 5},
        {"company_id": "JPM", "sentiment_score": 40.0, "avg_sentiment": -0.10, "total_articles": 12},
    ]


@pytest.fixture
def mock_db_client():
    """Mock DatabaseClient for testing without real PostgreSQL."""
    client = MagicMock()
    session = MagicMock()
    client.session = session
    return client


@pytest.fixture
def mock_mongo_client():
    """Mock MongoDBClient for testing without real MongoDB."""
    client = MagicMock()
    client.db = MagicMock()
    return client
