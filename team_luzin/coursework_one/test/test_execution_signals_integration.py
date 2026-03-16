"""
Smoke Tests for ExecutionSignals Module

Tests core functionality of signal generation:
- MACD signal generation
- ATR signal generation  
- Liquidity signal generation
- Signal combination logic

These are smoke tests - they verify basic operation without external dependencies.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


class TestExecutionSignalsImport:
    """Test that ExecutionSignals module can be imported and initialized."""

    def test_execution_signals_import(self):
        """Test that ExecutionSignals class can be imported."""
        from modules.signals.execution_signals import ExecutionSignals

        assert ExecutionSignals is not None
        assert hasattr(ExecutionSignals, "generate_macd_signal")
        assert hasattr(ExecutionSignals, "generate_atr_signal")
        assert hasattr(ExecutionSignals, "generate_liquidity_signal")
        assert hasattr(ExecutionSignals, "combine_signals")

    def test_execution_signals_static_methods(self):
        """Test that all signal generation methods are static."""
        from modules.signals.execution_signals import ExecutionSignals

        # Verify methods are callable without instantiation
        assert callable(ExecutionSignals.generate_macd_signal)
        assert callable(ExecutionSignals.generate_atr_signal)
        assert callable(ExecutionSignals.generate_liquidity_signal)
        assert callable(ExecutionSignals.combine_signals)

    def test_execution_signals_module_init(self):
        """Test that execution_signals module is properly initialized."""
        from modules.signals import ExecutionSignals

        assert ExecutionSignals is not None


class TestMACDSignalGeneration:
    """Test MACD-based trend signal generation."""

    def test_macd_signal_with_valid_data(self):
        """Test MACD signal generation with valid OHLCV data."""
        from modules.signals.execution_signals import ExecutionSignals

        # Create sample data with clear trend
        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "Close": np.linspace(100, 150, 100) + np.random.normal(0, 1, 100),
                "Date": dates,
            }
        )
        df.set_index("Date", inplace=True)

        signal = ExecutionSignals.generate_macd_signal(df)

        # Verify output
        assert signal is not None
        assert len(signal) == len(df)
        assert signal.dtype in [np.int64, np.float64, "int64", "float64"]
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_macd_signal_returns_series(self):
        """Test that MACD signal returns pandas Series."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame({"Close": np.linspace(100, 110, 50)}, index=dates)

        signal = ExecutionSignals.generate_macd_signal(df)

        assert isinstance(signal, pd.Series)
        assert signal.index.equals(df.index)

    def test_macd_signal_with_uptrend(self):
        """Test MACD signal with strongly uptrending data."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        # Strong uptrend
        df = pd.DataFrame({"Close": np.linspace(100, 200, 100), "Date": dates})
        df.set_index("Date", inplace=True)

        signal = ExecutionSignals.generate_macd_signal(df)

        # Should have mostly bullish signals (1)
        bullish_count = (signal == 1).sum()
        total_count = len(signal)
        assert bullish_count > total_count * 0.4  # At least 40% bullish

    def test_macd_signal_with_downtrend(self):
        """Test MACD signal with strongly downtrending data."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        # Strong downtrend
        df = pd.DataFrame({"Close": np.linspace(200, 100, 100), "Date": dates})
        df.set_index("Date", inplace=True)

        signal = ExecutionSignals.generate_macd_signal(df)

        # Should have mostly bearish signals (-1)
        bearish_count = (signal == -1).sum()
        total_count = len(signal)
        assert bearish_count > total_count * 0.4  # At least 40% bearish

    def test_macd_signal_with_insufficient_data(self):
        """Test MACD signal handling with minimal data."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = pd.DataFrame({"Close": [100, 101, 102, 103, 104]}, index=dates)

        # Should still work but may have NaN values
        signal = ExecutionSignals.generate_macd_signal(df)
        assert len(signal) == len(df)


class TestATRSignalGeneration:
    """Test ATR-based risk signal generation."""

    def test_atr_signal_with_valid_data(self):
        """Test ATR signal generation with valid OHLC data."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "High": np.linspace(105, 155, 100),
                "Low": np.linspace(95, 145, 100),
                "Close": np.linspace(100, 150, 100),
                "Date": dates,
            }
        )
        df.set_index("Date", inplace=True)

        signal = ExecutionSignals.generate_atr_signal(df, period=14, threshold=2.0)

        # Verify output
        assert signal is not None
        assert len(signal) == len(df)
        assert set(signal.unique()).issubset({-1, 1})  # ATR signal is binary

    def test_atr_signal_returns_series(self):
        """Test that ATR signal returns pandas Series."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame(
            {
                "High": np.linspace(105, 115, 50),
                "Low": np.linspace(95, 105, 50),
                "Close": np.linspace(100, 110, 50),
            },
            index=dates,
        )

        signal = ExecutionSignals.generate_atr_signal(df)

        assert isinstance(signal, pd.Series)
        assert signal.index.equals(df.index)

    def test_atr_signal_with_high_volatility(self):
        """Test ATR signal with high volatility data."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        # High volatility - wide ranges
        df = pd.DataFrame(
            {
                "High": np.linspace(120, 180, 100),
                "Low": np.linspace(80, 120, 100),
                "Close": np.linspace(100, 150, 100),
            },
            index=dates,
        )

        signal = ExecutionSignals.generate_atr_signal(df, period=14)

        # Should indicate risk
        assert len(signal) == len(df)
        assert signal.dtype in [np.int64, "int64"]

    def test_atr_signal_with_low_volatility(self):
        """Test ATR signal with low volatility data."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        # Low volatility - narrow ranges
        base = np.linspace(100, 110, 100)
        df = pd.DataFrame(
            {"High": base + 0.5, "Low": base - 0.5, "Close": base}, index=dates
        )

        signal = ExecutionSignals.generate_atr_signal(df, period=14)

        # Should indicate lower risk (1 = low risk)
        assert len(signal) == len(df)
        assert (signal == 1).sum() > (signal == -1).sum()

    def test_atr_signal_custom_period(self):
        """Test ATR signal with custom period."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "High": np.linspace(105, 155, 100),
                "Low": np.linspace(95, 145, 100),
                "Close": np.linspace(100, 150, 100),
            },
            index=dates,
        )

        # Test with different periods
        for period in [7, 14, 21]:
            signal = ExecutionSignals.generate_atr_signal(df, period=period)
            assert len(signal) == len(df)


class TestLiquiditySignalGeneration:
    """Test liquidity-based signal generation."""

    def test_liquidity_signal_with_valid_data(self):
        """Test liquidity signal generation with valid data."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "Volume": np.linspace(1000000, 5000000, 100),
                "Close": np.linspace(10, 100, 100),
                "Date": dates,
            }
        )
        df.set_index("Date", inplace=True)

        signal = ExecutionSignals.generate_liquidity_signal(df)

        # Verify output
        assert signal is not None
        assert len(signal) == len(df)
        assert set(signal.unique()).issubset({-1, 1})

    def test_liquidity_signal_high_volume(self):
        """Test liquidity signal with high volume stocks."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame(
            {
                "Volume": np.ones(50) * 10000000,  # Very high volume
                "Close": np.ones(50) * 50,  # Good price
            },
            index=dates,
        )

        signal = ExecutionSignals.generate_liquidity_signal(df)

        # Should indicate liquid (1)
        assert (signal == 1).sum() > (signal == -1).sum()

    def test_liquidity_signal_low_volume(self):
        """Test liquidity signal with low volume stocks."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame(
            {"Volume": np.ones(50) * 100000, "Close": np.ones(50) * 50},  # Low volume
            index=dates,
        )

        signal = ExecutionSignals.generate_liquidity_signal(df)

        # Should indicate illiquid (-1)
        assert (signal == -1).sum() > (signal == 1).sum()

    def test_liquidity_signal_low_price(self):
        """Test liquidity signal with penny stocks."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame(
            {
                "Volume": np.ones(50) * 5000000,  # High volume
                "Close": np.ones(50) * 1,  # Penny stock
            },
            index=dates,
        )

        signal = ExecutionSignals.generate_liquidity_signal(df)

        # Should indicate illiquid due to low price (-1)
        assert (signal == -1).sum() > (signal == 1).sum()

    def test_liquidity_signal_custom_thresholds(self):
        """Test liquidity signal with custom thresholds."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame(
            {"Volume": np.ones(50) * 500000, "Close": np.ones(50) * 50}, index=dates
        )

        # Test with lower thresholds
        signal1 = ExecutionSignals.generate_liquidity_signal(
            df, volume_threshold=100000, price_threshold=10
        )

        # Test with higher thresholds
        signal2 = ExecutionSignals.generate_liquidity_signal(
            df, volume_threshold=10000000, price_threshold=100
        )

        # Signal1 should have more liquid signals
        assert (signal1 == 1).sum() > (signal2 == 1).sum()


class TestSignalCombination:
    """Test signal combination logic."""

    def test_combine_signals_with_valid_inputs(self):
        """Test combining three signals into final signal."""
        from modules.signals.execution_signals import ExecutionSignals

        # Create sample signals
        index = pd.date_range("2025-01-01", periods=100, freq="D")
        macd_signal = pd.Series(np.random.choice([-1, 0, 1], 100), index=index)
        atr_signal = pd.Series(np.random.choice([-1, 1], 100), index=index)
        liquidity_signal = pd.Series(np.random.choice([-1, 1], 100), index=index)

        result = ExecutionSignals.combine_signals(
            macd_signal, atr_signal, liquidity_signal
        )

        # Verify output
        assert result is not None
        assert len(result) == 100
        assert set(result.unique()).issubset({-1, 0, 1})

    def test_combine_signals_returns_series(self):
        """Test that combine_signals returns pandas Series."""
        from modules.signals.execution_signals import ExecutionSignals

        index = pd.date_range("2025-01-01", periods=50, freq="D")
        macd = pd.Series(np.ones(50), index=index)
        atr = pd.Series(np.ones(50), index=index)
        liquidity = pd.Series(np.ones(50), index=index)

        result = ExecutionSignals.combine_signals(macd, atr, liquidity)

        assert isinstance(result, pd.Series)
        assert result.index.equals(index)

    def test_combine_signals_all_bullish(self):
        """Test combining all bullish signals."""
        from modules.signals.execution_signals import ExecutionSignals

        index = pd.date_range("2025-01-01", periods=100, freq="D")
        # All positive signals (bullish)
        macd_signal = pd.Series(np.ones(100), index=index)
        atr_signal = pd.Series(np.ones(100), index=index)
        liquidity_signal = pd.Series(np.ones(100), index=index)

        result = ExecutionSignals.combine_signals(
            macd_signal, atr_signal, liquidity_signal
        )

        # Should produce mostly BUY signals (1)
        assert (result == 1).sum() > (result == -1).sum()

    def test_combine_signals_all_bearish(self):
        """Test combining all bearish signals."""
        from modules.signals.execution_signals import ExecutionSignals

        index = pd.date_range("2025-01-01", periods=100, freq="D")
        # All negative signals (bearish)
        macd_signal = pd.Series(-np.ones(100), index=index)
        atr_signal = pd.Series(-np.ones(100), index=index)
        liquidity_signal = pd.Series(-np.ones(100), index=index)

        result = ExecutionSignals.combine_signals(
            macd_signal, atr_signal, liquidity_signal
        )

        # Should produce mostly SELL signals (-1)
        assert (result == -1).sum() > (result == 1).sum()

    def test_combine_signals_custom_weights(self):
        """Test combining signals with custom weights."""
        from modules.signals.execution_signals import ExecutionSignals

        index = pd.date_range("2025-01-01", periods=50, freq="D")
        macd = pd.Series(np.random.choice([-1, 1], 50), index=index)
        atr = pd.Series(np.random.choice([-1, 1], 50), index=index)
        liquidity = pd.Series(np.random.choice([-1, 1], 50), index=index)

        # Custom weights - favor MACD
        custom_weights = {"macd": 0.7, "atr": 0.2, "liquidity": 0.1}

        result = ExecutionSignals.combine_signals(
            macd, atr, liquidity, weights=custom_weights
        )

        assert len(result) == 50
        assert set(result.unique()).issubset({-1, 0, 1})

    def test_combine_signals_default_weights(self):
        """Test combining signals uses default weights when None."""
        from modules.signals.execution_signals import ExecutionSignals

        index = pd.date_range("2025-01-01", periods=50, freq="D")
        macd = pd.Series(np.ones(50), index=index)
        atr = pd.Series(np.ones(50), index=index)
        liquidity = pd.Series(np.ones(50), index=index)

        # Should use default weights {'macd': 0.4, 'atr': 0.3, 'liquidity': 0.3}
        result1 = ExecutionSignals.combine_signals(macd, atr, liquidity)
        result2 = ExecutionSignals.combine_signals(
            macd, atr, liquidity, weights={"macd": 0.4, "atr": 0.3, "liquidity": 0.3}
        )

        # Results should be identical
        assert result1.equals(result2)


class TestExecutionSignalsEndToEnd:
    """End-to-end tests for complete signal generation pipeline."""

    def test_full_signal_generation_pipeline(self):
        """Test complete signal generation from OHLCV data."""
        from modules.signals.execution_signals import ExecutionSignals

        # Generate realistic OHLCV data
        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "Open": np.linspace(100, 120, 100),
                "High": np.linspace(105, 125, 100),
                "Low": np.linspace(95, 115, 100),
                "Close": np.linspace(100, 120, 100) + np.random.normal(0, 1, 100),
                "Volume": np.random.uniform(1000000, 5000000, 100),
            },
            index=dates,
        )

        # Generate all signals
        macd_signal = ExecutionSignals.generate_macd_signal(df[["Close"]])
        atr_signal = ExecutionSignals.generate_atr_signal(df[["High", "Low", "Close"]])
        liquidity_signal = ExecutionSignals.generate_liquidity_signal(
            df[["Volume", "Close"]]
        )

        # Combine signals
        final_signal = ExecutionSignals.combine_signals(
            macd_signal, atr_signal, liquidity_signal
        )

        # Verify complete pipeline
        assert len(final_signal) == 100
        assert set(final_signal.unique()).issubset({-1, 0, 1})
        assert not final_signal.isna().all()

    def test_signal_generation_consistency(self):
        """Test that signal generation is deterministic."""
        from modules.signals.execution_signals import ExecutionSignals

        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame(
            {
                "Open": np.linspace(100, 110, 50),
                "High": np.linspace(105, 115, 50),
                "Low": np.linspace(95, 105, 50),
                "Close": np.linspace(100, 110, 50),
                "Volume": np.linspace(1000000, 3000000, 50),
            },
            index=dates,
        )

        # Generate signals twice
        signal1 = ExecutionSignals.generate_macd_signal(df[["Close"]])
        signal2 = ExecutionSignals.generate_macd_signal(df[["Close"]])

        # Should be identical
        assert signal1.equals(signal2)
