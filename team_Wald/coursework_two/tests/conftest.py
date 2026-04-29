"""Shared pytest fixtures for the CW2 test suite.

Provides reusable fixtures so individual test modules can stay focused on
the behaviour under test rather than synthetic-data plumbing:

    * ``base_config``      — realistic backtest_config.yaml dict
    * ``sector_map``       — 10-ticker × 2-sector map
    * ``small_value_df``   — minimal but non-degenerate value-metrics frame
    * ``small_sentiment_df`` — minimal aggregated sentiment frame
    * ``synthetic_returns`` — 504 trading days of GBM returns (~2 years)
    * ``synthetic_price_panel`` — 504-day × 10-ticker price panel for
      backtester / weighting / random-portfolio tests
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def base_config() -> dict:
    """Mirror the production backtest_config.yaml for unit tests."""
    return {
        'backtest': {
            'start_date': '2023-01-01',
            'end_date': '2024-12-31',
            'rebalance_frequency': 'quarterly',
            'rebalance_months': [1, 4, 7, 10],
            'reporting_lag_days': 90,
            'execution_delay': 1,
        },
        'scoring': {
            'value_weight': 0.6,
            'sentiment_weight': 0.4,
            'max_debt_equity': 2.0,
            'min_sentiment_confidence': 0.3,
            'selection_percentile': 0.20,
            'winsorize_lower': 0.025,
            'winsorize_upper': 0.975,
            'zscore_cap': 3.0,
            'shrinkage_k_sector': 20,
            'shrinkage_k_sentiment': 5,
        },
        'sentiment': {
            'half_life_days': 7,
            'source_tiers': {
                'tier1': ['reuters.com', 'bloomberg.com'],
                'tier2': ['cnbc.com'],
                'tier3': ['seekingalpha.com'],
            },
            'tier_weights': {'tier1': 1.0, 'tier2': 0.7, 'tier3': 0.4, 'default': 0.3},
        },
        'portfolio': {
            'weighting_scheme': 'equal_weight',
            'max_position_weight': 0.05,
            'max_sector_weight': 0.25,
            'min_holdings': 5,
            'target_holdings': 10,
            'buffer_buy_pctl': 0.60,
            'buffer_sell_pctl': 0.40,
        },
        'costs': {
            'transaction_cost_bps': 25,
            'stress_test_bps': 50,
        },
        'benchmark': {
            'primary': '^GSPC',
            'secondary': 'IWVL.L',
        },
        'risk_free': {'annual_rate': 0.04},
    }


@pytest.fixture
def sector_map() -> dict:
    return {
        'A': 'Technology', 'B': 'Technology', 'C': 'Technology',
        'D': 'Technology', 'E': 'Technology',
        'F': 'Health Care', 'G': 'Health Care', 'H': 'Health Care',
        'I': 'Health Care', 'J': 'Health Care',
    }


@pytest.fixture
def small_value_df() -> pd.DataFrame:
    return pd.DataFrame({
        'company_id': list('ABCDEFGHIJ'),
        'pe_ratio': [15, 20, 25, 10, 30, 12, 18, 22, 8, 35],
        'pb_ratio': [1.5, 2.0, 3.0, 1.0, 4.0, 1.2, 1.8, 2.5, 0.8, 5.0],
        'ev_ebitda': [10, 12, 15, 8, 20, 9, 11, 14, 7, 25],
        'dividend_yield': [0.03, 0.02, 0.01, 0.04, 0.005, 0.035, 0.025, 0.015, 0.05, 0.003],
        'debt_equity': [1.0, 1.5, 2.0, 0.5, 2.5, 0.8, 1.2, 1.8, 0.3, 3.0],
    })


@pytest.fixture
def small_sentiment_df() -> pd.DataFrame:
    dates = pd.to_datetime(['2024-01-15'] * 10)
    return pd.DataFrame({
        'company_id': list('ABCDEFGHIJ'),
        'date': dates,
        'avg_sentiment': [0.30, 0.10, -0.10, 0.50, -0.20,
                          0.40, 0.05, -0.05, 0.25, -0.30],
        'positive_count': [8, 5, 3, 12, 2, 10, 6, 4, 9, 1],
        'negative_count': [2, 4, 6, 1, 7, 3, 5, 6, 4, 8],
        'neutral_count': [5, 6, 6, 2, 6, 4, 4, 5, 7, 6],
        'total_articles': [15, 15, 15, 15, 15, 17, 15, 15, 20, 15],
        'positive_ratio': [0.53, 0.33, 0.20, 0.80, 0.13,
                           0.59, 0.40, 0.27, 0.45, 0.07],
        'sentiment_score': [65, 52, 40, 78, 35, 70, 50, 45, 60, 30],
    })


@pytest.fixture
def synthetic_returns() -> pd.Series:
    """504-day daily return series with realistic volatility and a drawdown."""
    rng = np.random.RandomState(7)
    rets = rng.normal(loc=0.0006, scale=0.012, size=504)
    # Inject a drawdown event in days 200–230 so MaxDD tests have material
    rets[200:230] = rng.normal(loc=-0.005, scale=0.018, size=30)
    dates = pd.bdate_range('2023-01-02', periods=504)
    return pd.Series(rets, index=dates, name='ret')


@pytest.fixture
def synthetic_price_panel() -> pd.DataFrame:
    """Geometric-Brownian-motion price panel for 10 stocks across 504 days."""
    rng = np.random.RandomState(11)
    n_days, n_tickers = 504, 10
    daily_ret = rng.normal(loc=0.0005, scale=0.014, size=(n_days, n_tickers))
    cum = np.cumprod(1.0 + daily_ret, axis=0) * 100.0
    dates = pd.bdate_range('2023-01-02', periods=n_days)
    tickers = list('ABCDEFGHIJ')
    return pd.DataFrame(cum, index=dates, columns=tickers)
