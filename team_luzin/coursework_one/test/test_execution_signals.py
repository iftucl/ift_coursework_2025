"""
Unit tests for ExecutionSignals module.

Tests pure signal generation functions without external dependencies.
"""

import numpy as np
import pandas as pd
import pytest

from modules.signals.execution_signals import ExecutionSignals


class TestExtractClosePrices:
    """Test extract_close_prices() method."""

    def test_extract_close_prices_valid(self):
        """Extract close prices from valid DataFrame."""
        df = pd.DataFrame(
            {
                "Close": [100.0, 101.5, 102.0, 103.5, 104.0],
                "Volume": [1000000, 1100000, 1200000, 1150000, 1300000],
            }
        )

        result = ExecutionSignals.extract_close_prices(df)

        assert result is not None
        assert isinstance(result, pd.Series)
        assert len(result) == 5
        assert result[0] == 100.0

    def test_extract_close_prices_none_dataframe(self):
        """Handle None DataFrame."""
        result = ExecutionSignals.extract_close_prices(None)
        assert result is None

    def test_extract_close_prices_empty_dataframe(self):
        """Handle empty DataFrame."""
        df = pd.DataFrame()
        result = ExecutionSignals.extract_close_prices(df)
        assert result is None

    def test_extract_close_prices_missing_column(self):
        """Handle missing Close column."""
        df = pd.DataFrame({"Volume": [1000000, 1100000]})
        result = ExecutionSignals.extract_close_prices(df)
        assert result is None

    def test_extract_close_prices_all_nan(self):
        """Handle DataFrame with all NaN Close prices."""
        df = pd.DataFrame({"Close": [np.nan, np.nan, np.nan]})
        result = ExecutionSignals.extract_close_prices(df)
        assert result is None


class TestGenerateMACDSignal:
    """Test generate_macd_signal() method."""

    def test_generate_macd_signal_valid(self):
        """Generate MACD signal from valid close prices."""
        close_prices = pd.Series(
            [
                100,
                101,
                102,
                103,
                104,
                105,
                104,
                103,
                102,
                101,
                100,
                99,
                98,
                97,
                96,
                97,
                98,
                99,
                100,
                101,
                102,
                103,
                104,
                105,
                106,
                107,
                108,
                109,
                110,
                111,
            ]
        )

        result = ExecutionSignals.generate_macd_signal(close_prices)

        assert isinstance(result, pd.Series)
        assert len(result) == len(close_prices)
        assert all(v in [-1, 0, 1] for v in result.values)

    def test_generate_macd_signal_from_dataframe(self):
        """Generate MACD signal from DataFrame with Close column."""
        df = pd.DataFrame({"Close": [100 + i for i in range(30)]})

        result = ExecutionSignals.generate_macd_signal(df)

        assert isinstance(result, pd.Series)
        assert len(result) == 30

    def test_generate_macd_signal_empty_series(self):
        """Handle empty close prices."""
        close_prices = pd.Series([])

        with pytest.raises(ValueError):
            ExecutionSignals.generate_macd_signal(close_prices)

    def test_generate_macd_signal_uptrend(self):
        """MACD should detect uptrend."""
        close_prices = pd.Series(
            [
                100,
                101,
                102,
                103,
                104,
                105,
                106,
                107,
                108,
                109,
                110,
                111,
                112,
                113,
                114,
                115,
                116,
                117,
                118,
                119,
                120,
                121,
                122,
                123,
                124,
                125,
                126,
                127,
                128,
                129,
            ]
        )

        result = ExecutionSignals.generate_macd_signal(close_prices)

        # Most recent values should be bullish (1) in strong uptrend
        recent_bullish = sum(1 for v in result.iloc[-5:] if v == 1)
        assert recent_bullish > 0


class TestGenerateATRSignal:
    """Test generate_atr_signal() method."""

    def test_generate_atr_signal_valid(self):
        """Generate ATR signal from valid OHLC data."""
        df = pd.DataFrame(
            {
                "High": [101, 102, 103, 104, 105] * 6,
                "Low": [99, 100, 101, 102, 103] * 6,
                "Close": [100, 101, 102, 103, 104] * 6,
                "Volume": [1000000] * 30,
            }
        )

        result = ExecutionSignals.generate_atr_signal(df, period=14, threshold=2.0)

        assert isinstance(result, pd.Series)
        assert len(result) == len(df)
        assert all(v in [-1, 1] for v in result.values)

    def test_generate_atr_signal_custom_period(self):
        """Generate ATR signal with custom period."""
        df = pd.DataFrame(
            {
                "High": [101, 102, 103, 104, 105] * 6,
                "Low": [99, 100, 101, 102, 103] * 6,
                "Close": [100, 101, 102, 103, 104] * 6,
                "Volume": [1000000] * 30,
            }
        )

        result = ExecutionSignals.generate_atr_signal(df, period=5, threshold=1.5)

        assert isinstance(result, pd.Series)
        assert len(result) == len(df)

    def test_generate_atr_signal_missing_column(self):
        """Handle missing OHLC column."""
        df = pd.DataFrame(
            {
                "High": [101, 102, 103],
                "Low": [99, 100, 101]
                # Missing Close
            }
        )

        with pytest.raises(KeyError):
            ExecutionSignals.generate_atr_signal(df)


class TestGenerateLiquiditySignal:
    """Test generate_liquidity_signal() method."""

    def test_generate_liquidity_signal_valid(self):
        """Generate liquidity signal from valid data."""
        df = pd.DataFrame(
            {
                "Volume": [2000000, 1500000, 500000, 800000, 2500000] * 6,
                "Close": [50, 60, 45, 70, 100] * 6,
            }
        )

        result = ExecutionSignals.generate_liquidity_signal(
            df, volume_threshold=1000000, price_threshold=5.0
        )

        assert isinstance(result, pd.Series)
        assert len(result) == len(df)
        assert all(v in [-1, 1] for v in result.values)

    def test_generate_liquidity_signal_custom_thresholds(self):
        """Generate liquidity signal with custom thresholds."""
        df = pd.DataFrame(
            {"Volume": [1000000, 500000, 2000000] * 10, "Close": [10, 5, 50] * 10}
        )

        result = ExecutionSignals.generate_liquidity_signal(
            df, volume_threshold=500000, price_threshold=1.0
        )

        assert isinstance(result, pd.Series)
        # Should have liquid signals for first and third values
        liquid_count = sum(1 for v in result.iloc[0::3] if v == 1)
        assert liquid_count >= 2

    def test_generate_liquidity_signal_low_volume_stocks(self):
        """Identify low-volume stocks."""
        df = pd.DataFrame(
            {
                "Volume": [50000, 100000, 75000] * 10,  # All below 1M threshold
                "Close": [100, 150, 200] * 10,
            }
        )

        result = ExecutionSignals.generate_liquidity_signal(
            df, volume_threshold=1000000, price_threshold=5.0
        )

        # All should be illiquid (-1)
        assert all(v == -1 for v in result.values)


class TestCombineSignals:
    """Test combine_signals() method."""

    def test_combine_signals_equal_weights(self):
        """Combine signals with equal weights."""
        macd = pd.Series([1, 1, 1, 0, -1, -1] * 5)
        atr = pd.Series([1, 1, 0, 0, -1, -1] * 5)
        liquidity = pd.Series([1, 1, 1, 1, 1, 1] * 5)

        result = ExecutionSignals.combine_signals(macd, atr, liquidity)

        assert isinstance(result, pd.Series)
        assert len(result) == len(macd)
        assert all(v in [-1, 0, 1] for v in result.values)

    def test_combine_signals_custom_weights(self):
        """Combine signals with custom weights."""
        macd = pd.Series([1, 1, -1, -1] * 7 + [1, 1])
        atr = pd.Series([1, -1, 1, -1] * 7 + [1, -1])
        liquidity = pd.Series([1, 1, 1, 1] * 7 + [1, 1])

        weights = {"macd": 0.6, "atr": 0.2, "liquidity": 0.2}
        result = ExecutionSignals.combine_signals(macd, atr, liquidity, weights)

        assert isinstance(result, pd.Series)
        assert len(result) == 30

    def test_combine_signals_bullish_consensus(self):
        """When all signals bullish, should generate BUY."""
        macd = pd.Series([1, 1, 1, 1, 1])
        atr = pd.Series([1, 1, 1, 1, 1])
        liquidity = pd.Series([1, 1, 1, 1, 1])

        result = ExecutionSignals.combine_signals(macd, atr, liquidity)

        # All should be BUY (1)
        assert all(v == 1 for v in result.values)

    def test_combine_signals_bearish_consensus(self):
        """When all signals bearish, should generate SELL."""
        macd = pd.Series([-1, -1, -1, -1, -1])
        atr = pd.Series([-1, -1, -1, -1, -1])
        liquidity = pd.Series([-1, -1, -1, -1, -1])

        result = ExecutionSignals.combine_signals(macd, atr, liquidity)

        # All should be SELL (-1)
        assert all(v == -1 for v in result.values)

    def test_combine_signals_mixed(self):
        """Mixed signals should generate mixed results."""
        # Neutral signals that will mix BUY/SELL/HOLD outputs
        macd = pd.Series([1, 0, -1, 0, 1])
        atr = pd.Series([0, 1, 0, -1, 0])
        liquidity = pd.Series([1, 1, -1, 1, 1])

        result = ExecutionSignals.combine_signals(macd, atr, liquidity)

        # Should have variety in signals, not all same value
        unique_signals = set(result.values)
        assert len(unique_signals) > 1, "Should have mixed signals"
