"""Tests for EWMA volatility calculation."""

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from modules.portfolio.ewma_volatility import (
    EWMAConfig,
    compute_ewma_vol,
    run_ewma_volatility,
)

# ---------------------------------------------------------------------------
# compute_ewma_vol
# ---------------------------------------------------------------------------


class TestComputeEwmaVol:

    def test_basic_computation(self):
        """EWMA vol is computed and positive for a stock with enough data."""
        np.random.seed(42)
        n = 60
        prices = pd.DataFrame(
            {
                "symbol": ["A"] * n,
                "trade_date": pd.bdate_range("2023-01-02", periods=n),
                "adjusted_close": 100 * np.cumprod(1 + np.random.randn(n) * 0.01),
            }
        )
        result = compute_ewma_vol(prices, ewma_lambda=0.94, seed_days=20)
        assert len(result) == 1
        assert result.iloc[0]["ewma_vol"] > 0

    def test_annualised_range(self):
        """EWMA vol should be in a reasonable annualised range (5-100%)."""
        np.random.seed(42)
        n = 252
        daily_returns = np.random.randn(n) * 0.01  # ~1% daily vol
        prices_arr = 100 * np.cumprod(1 + daily_returns)
        prices = pd.DataFrame(
            {
                "symbol": ["A"] * n,
                "trade_date": pd.bdate_range("2023-01-02", periods=n),
                "adjusted_close": prices_arr,
            }
        )
        result = compute_ewma_vol(prices, ewma_lambda=0.94, seed_days=20)
        vol = result.iloc[0]["ewma_vol"]
        # 1% daily * sqrt(252) ~ 15.9% annualised, should be in 5-50% range
        assert 0.05 < vol < 0.50

    def test_insufficient_data_returns_empty(self):
        """Stock with fewer prices than seed_days is skipped."""
        prices = pd.DataFrame(
            {
                "symbol": ["A"] * 10,
                "trade_date": pd.bdate_range("2023-01-02", periods=10),
                "adjusted_close": [100 + i for i in range(10)],
            }
        )
        result = compute_ewma_vol(prices, ewma_lambda=0.94, seed_days=20)
        assert result.empty

    def test_multiple_symbols(self):
        """Computes vol independently for each symbol."""
        np.random.seed(42)
        n = 60
        dates = pd.bdate_range("2023-01-02", periods=n)
        prices = pd.concat(
            [
                pd.DataFrame(
                    {
                        "symbol": [sym] * n,
                        "trade_date": dates,
                        "adjusted_close": 100
                        * np.cumprod(1 + np.random.randn(n) * 0.01),
                    }
                )
                for sym in ["A", "B", "C"]
            ],
            ignore_index=True,
        )
        result = compute_ewma_vol(prices, ewma_lambda=0.94, seed_days=20)
        assert len(result) == 3
        assert set(result["symbol"]) == {"A", "B", "C"}

    def test_higher_lambda_smoother(self):
        """Higher lambda produces smoother (less reactive) vol estimates.

        A spike in returns should have less impact with lambda=0.97 vs 0.90.
        """
        np.random.seed(42)
        n = 60
        returns = np.random.randn(n) * 0.01
        # Add a large spike near the end
        returns[-5] = 0.10
        prices_arr = 100 * np.cumprod(1 + returns)
        prices = pd.DataFrame(
            {
                "symbol": ["A"] * n,
                "trade_date": pd.bdate_range("2023-01-02", periods=n),
                "adjusted_close": prices_arr,
            }
        )

        vol_high_lambda = compute_ewma_vol(prices, ewma_lambda=0.97, seed_days=20).iloc[
            0
        ]["ewma_vol"]
        vol_low_lambda = compute_ewma_vol(prices, ewma_lambda=0.90, seed_days=20).iloc[
            0
        ]["ewma_vol"]

        # Low lambda reacts more to the spike, so its vol should be higher
        assert vol_low_lambda > vol_high_lambda

    def test_empty_prices_returns_empty(self):
        """Empty price DataFrame returns empty result."""
        prices = pd.DataFrame(columns=["symbol", "trade_date", "adjusted_close"])
        result = compute_ewma_vol(prices)
        assert result.empty

    def test_fewer_prices_than_seed_days_excluded(self):
        """Stock with fewer log returns than seed_days is excluded from output."""
        # seed_days default is 20; give only 5 prices → 4 log returns < 20
        prices = pd.DataFrame(
            {
                "symbol": ["A"] * 5,
                "trade_date": pd.bdate_range("2023-01-02", periods=5),
                "adjusted_close": [100.0, 101.0, 102.0, 101.5, 103.0],
            }
        )
        result = compute_ewma_vol(prices, seed_days=20)
        assert result.empty


# ---------------------------------------------------------------------------
# run_ewma_volatility (orchestrator with mocked DB)
# ---------------------------------------------------------------------------


class TestRunEwmaVolatility:

    def test_empty_symbols_returns_empty(self):
        """No symbols to process returns empty DataFrame."""
        db = MagicMock()
        result = run_ewma_volatility(db, [], date(2024, 1, 31), EWMAConfig())
        assert result.empty
        db.read_query.assert_not_called()

    def test_empty_prices_from_db(self):
        """DB returns no price data, result is empty."""
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        result = run_ewma_volatility(db, ["A", "B"], date(2024, 1, 31), EWMAConfig())
        assert result.empty

    def test_full_flow_with_mock(self):
        """Mocked DB returns prices, EWMA vol is computed."""
        np.random.seed(42)
        n = 60
        prices = pd.DataFrame(
            {
                "symbol": ["A"] * n,
                "trade_date": pd.bdate_range("2023-01-02", periods=n),
                "adjusted_close": 100 * np.cumprod(1 + np.random.randn(n) * 0.01),
            }
        )
        db = MagicMock()
        db.read_query.return_value = prices

        result = run_ewma_volatility(db, ["A"], date(2024, 1, 31), EWMAConfig())
        assert len(result) == 1
        assert result.iloc[0]["ewma_vol"] > 0
