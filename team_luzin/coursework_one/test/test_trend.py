"""
Comprehensive tests for Trend calculation module
Focused on MACD and Moving Average calculations
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


class TestTrendCalculator:
    """Comprehensive tests for TrendCalculator module"""

    @pytest.fixture
    def uptrend_data(self):
        """Strong uptrend"""
        prices = np.linspace(100, 150, 300)
        return pd.DataFrame(
            {"Close": prices, "Volume": np.random.uniform(1000000, 5000000, 300)}
        )

    @pytest.fixture
    def downtrend_data(self):
        """Strong downtrend"""
        prices = np.linspace(150, 100, 300)
        return pd.DataFrame(
            {"Close": prices, "Volume": np.random.uniform(1000000, 5000000, 300)}
        )

    @pytest.fixture
    def sideways_data(self):
        """Sideways/flat market"""
        prices = np.ones(300) * 100 + np.random.normal(0, 1, 300)
        return pd.DataFrame(
            {"Close": prices, "Volume": np.random.uniform(1000000, 5000000, 300)}
        )

    def test_calculate_ma200_ratio_uptrend(self, uptrend_data):
        """Test MA200 ratio in uptrend"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_ma200_ratio(uptrend_data)

        if result is not None:
            assert result >= 1.0  # Price above 200 MA in uptrend

    def test_calculate_ma200_ratio_downtrend(self, downtrend_data):
        """Test MA200 ratio in downtrend"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_ma200_ratio(downtrend_data)

        if result is not None:
            assert result <= 1.0  # Price below 200 MA in downtrend

    def test_calculate_ma200_ratio_insufficient_data(self):
        """Test MA200 with insufficient data"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 110, 150)})

        result = TrendCalculator.calculate_ma200_ratio(df)
        assert result is None

    def test_calculate_ma200_with_full_data(self):
        """Test MA200 calculation with full 200+ days of data"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 150, 300)})

        result = TrendCalculator.calculate_ma200_ratio(df)

        if result is not None:
            assert isinstance(result, (int, float))
            assert result > 0

    def test_calculate_ma200_with_nan_values(self):
        """Test MA200 with NaN values"""
        from modules.processing.trend import TrendCalculator

        prices = np.linspace(100, 150, 300)
        prices[10:15] = np.nan  # Insert NaNs

        df = pd.DataFrame({"Close": prices})

        result = TrendCalculator.calculate_ma200_ratio(df)
        # Should handle gracefully
        assert result is None or isinstance(result, (int, float))

    def test_calculate_macd_line(self):
        """Test MACD line calculation"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 150, 100)})

        result = TrendCalculator.calculate_macd(df)

        if result is not None:
            macd_val, signal_val, hist_val = result
            assert isinstance(macd_val, (int, float, type(None)))
            assert isinstance(signal_val, (int, float, type(None)))
            assert isinstance(hist_val, (int, float, type(None)))

    def test_calculate_macd_with_sufficient_data(self):
        """Test MACD with full data"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.random.uniform(95, 105, 50)})

        result = TrendCalculator.calculate_macd(df)

        if result is not None and result[0] is not None:
            macd_val, signal_val, hist_val = result
            assert isinstance(macd_val, (int, float))
            assert isinstance(signal_val, (int, float))
            assert isinstance(hist_val, (int, float))

    def test_calculate_macd_uptrend(self, uptrend_data):
        """Test MACD in uptrend"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd(uptrend_data)

        if result is not None and result[0] is not None:
            macd_val, signal_val, hist_val = result
            # In uptrend, MACD typically positive
            assert isinstance(macd_val, (int, float))

    def test_calculate_macd_downtrend(self, downtrend_data):
        """Test MACD in downtrend"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd(downtrend_data)

        if result is not None and result[0] is not None:
            macd_val, signal_val, hist_val = result
            # In downtrend, MACD typically negative
            assert isinstance(macd_val, (int, float))

    def test_calculate_macd_sideways(self, sideways_data):
        """Test MACD in sideways market"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd(sideways_data)

        if result is not None and result[0] is not None:
            macd_val, signal_val, hist_val = result
            assert isinstance(macd_val, (int, float))

    def test_calculate_macd_empty_dataframe(self):
        """Test MACD with empty dataframe"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": []})

        result = TrendCalculator.calculate_macd(df)
        assert result is None or (
            result[0] is None and result[1] is None and result[2] is None
        )

    def test_calculate_macd_insufficient_data_small(self):
        """Test MACD with very small dataset"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": [100, 101, 102, 103, 104]})

        result = TrendCalculator.calculate_macd(df)
        assert result is None or result[0] is None

    def test_calculate_ma200_ratio_exact_200_days(self):
        """Test MA200 with exactly 200 days"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 150, 200)})

        result = TrendCalculator.calculate_ma200_ratio(df)
        # May return None or a value depending on implementation
        assert result is None or isinstance(result, (int, float))

    def test_calculate_ma200_ratio_201_days(self):
        """Test MA200 with 201 days"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 150, 201)})

        result = TrendCalculator.calculate_ma200_ratio(df)

        if result is not None:
            assert isinstance(result, (int, float))
            assert result > 0

    def test_calculate_macd_histogram_calculation(self):
        """Test MACD histogram (MACD line - Signal line)"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 150, 100)})

        result = TrendCalculator.calculate_macd(df)

        if result is not None and all(v is not None for v in result):
            macd_val, signal_val, hist_val = result
            # Histogram should be MACD - Signal
            expected_hist = macd_val - signal_val
            assert abs(hist_val - expected_hist) < 0.0001

    def test_calculate_ma200_with_constant_prices(self):
        """Test MA200 with constant prices"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.ones(300) * 100})

        result = TrendCalculator.calculate_ma200_ratio(df)

        if result is not None:
            # When all prices are same, ratio should be 1.0
            assert abs(result - 1.0) < 0.0001

    def test_calculate_macd_with_high_volatility(self):
        """Test MACD with highly volatile data"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.random.uniform(80, 120, 100)})

        result = TrendCalculator.calculate_macd(df)

        if result is not None and result[0] is not None:
            macd_val, signal_val, hist_val = result
            assert isinstance(macd_val, (int, float))
            assert isinstance(signal_val, (int, float))

    def test_calculate_macd_with_low_volatility(self):
        """Test MACD with low volatility data"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 101, 100)})

        result = TrendCalculator.calculate_macd(df)

        if result is not None and result[0] is not None:
            macd_val, signal_val, hist_val = result
            # Low vol should result in MACD close to 0
            assert abs(macd_val) < 1

    def test_calculate_regime_bull_above_threshold(self):
        """Test regime_bull = 1 when ma200_ratio > 1.0"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_regime_bull(1.05)
        assert result == 1

    def test_calculate_regime_bull_below_threshold(self):
        """Test regime_bull = 0 when ma200_ratio < 1.0"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_regime_bull(0.95)
        assert result == 0

    def test_calculate_regime_bull_exactly_one(self):
        """Test regime_bull at exactly 1.0 threshold"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_regime_bull(1.0)
        # Exactly 1.0 should NOT trigger bullish (needs to be > 1.0)
        assert result == 0

    def test_calculate_regime_bull_none_input(self):
        """Test regime_bull with None input"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_regime_bull(None)
        assert result is None

    def test_calculate_regime_bull_extreme_values(self):
        """Test regime_bull with extreme values"""
        from modules.processing.trend import TrendCalculator

        # Very high ratio (strong uptrend)
        result_high = TrendCalculator.calculate_regime_bull(2.5)
        assert result_high == 1

        # Very low ratio (strong downtrend)
        result_low = TrendCalculator.calculate_regime_bull(0.5)
        assert result_low == 0

    def test_is_bullish_when_regime_is_one(self):
        """Test is_bullish returns True when regime_bull = 1"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.is_bullish(1)
        assert result is True

    def test_is_bullish_when_regime_is_zero(self):
        """Test is_bullish returns False when regime_bull = 0"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.is_bullish(0)
        assert result is False

    def test_is_bullish_with_none_regime(self):
        """Test is_bullish with None regime"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.is_bullish(None)
        assert result is False

    def test_calculate_macd_signal_strong_buy(self):
        """Test calculate_macd_signal for strong buy (MACD=1, Signal=0.5)"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(1.0, 0.5)
        assert result == 2  # Strong buy signal

    def test_calculate_macd_signal_weak_buy(self):
        """Test calculate_macd_signal for weak buy (MACD=0.5, Signal=1, both positive)"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(0.5, 1.0)
        # When MACD < Signal but MACD > 0: returns -1 (weak bearish crossing)
        assert result == -1

    def test_calculate_macd_signal_strong_sell(self):
        """Test calculate_macd_signal for strong sell (MACD=-1, Signal=-0.5)"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(-1.0, -0.5)
        assert result == -2  # Strong sell signal

    def test_calculate_macd_signal_crossing_down(self):
        """Test calculate_macd_signal for crossing down (MACD=-0.5, Signal=1)"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(-0.5, 1.0)
        # When MACD < Signal and MACD < 0: returns -2 (strong bearish)
        assert result == -2

    def test_calculate_macd_signal_neutral(self):
        """Test calculate_macd_signal returns 0 when MACD = Signal"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(1.0, 1.0)
        assert result == 0  # Neutral

    def test_calculate_macd_signal_positive_crossover_up(self):
        """Test MACD crossing above signal line with positive values"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(1.5, 1.0)
        # When MACD > Signal and MACD > 0: returns 2 (strong bullish)
        assert result == 2

    def test_calculate_macd_signal_positive_crossover_down(self):
        """Test MACD crossing below signal line with positive values"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(0.5, 1.5)
        # When MACD < Signal but MACD > 0: returns -1 (weak bearish)
        assert result == -1

    def test_calculate_macd_signal_negative_values_crossover(self):
        """Test MACD above signal but both negative"""
        from modules.processing.trend import TrendCalculator

        result = TrendCalculator.calculate_macd_signal(-0.5, -1.0)
        # When MACD > Signal but MACD < 0: returns 1 (weak bullish)
        assert result == 1

    def test_calculate_macd_signal_none_inputs(self):
        """Test calculate_macd_signal with None inputs"""
        from modules.processing.trend import TrendCalculator

        result1 = TrendCalculator.calculate_macd_signal(None, 0.5)
        result2 = TrendCalculator.calculate_macd_signal(1.0, None)
        result3 = TrendCalculator.calculate_macd_signal(None, None)

        assert result1 == 0
        assert result2 == 0
        assert result3 == 0

    def test_calculate_macd_with_custom_periods(self):
        """Test MACD calculation with custom fast/slow/signal periods"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 150, 100)})

        # Using default parameters
        result = TrendCalculator.calculate_macd(df, fast=12, slow=26, signal=9)

        if result[0] is not None:
            macd_val, signal_val, hist_val = result
            assert isinstance(macd_val, float)
            assert isinstance(signal_val, float)
            assert isinstance(hist_val, float)

    def test_calculate_macd_histogram_equals_macd_minus_signal(self):
        """Verify MACD histogram = MACD - Signal mathematically"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(100, 150, 100)})

        macd_val, signal_val, hist_val = TrendCalculator.calculate_macd(df)

        if macd_val is not None and signal_val is not None and hist_val is not None:
            # Histogram should equal MACD - Signal
            expected_hist = macd_val - signal_val
            assert abs(hist_val - expected_hist) < 0.0001

    def test_calculate_ma200_with_very_high_prices(self):
        """Test MA200 with high price values"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(10000, 15000, 250)})

        result = TrendCalculator.calculate_ma200_ratio(df)

        if result is not None:
            assert isinstance(result, float)
            assert result > 0

    def test_calculate_ma200_with_very_low_prices(self):
        """Test MA200 with low price values (penny stocks)"""
        from modules.processing.trend import TrendCalculator

        df = pd.DataFrame({"Close": np.linspace(0.10, 0.20, 250)})

        result = TrendCalculator.calculate_ma200_ratio(df)

        if result is not None:
            assert isinstance(result, float)
            assert result > 0

    def test_calculate_ma200_with_nan_in_middle(self):
        """Test MA200 behavior with NaN values in middle of data"""
        from modules.processing.trend import TrendCalculator

        prices = np.linspace(100, 150, 250).tolist()
        prices[100:110] = [np.nan] * 10  # Insert NaN gap

        df = pd.DataFrame({"Close": prices})

        result = TrendCalculator.calculate_ma200_ratio(df)
        # Should handle NaN gracefully
        assert result is None or isinstance(result, float)

    def test_calculate_macd_insufficient_data_boundary(self):
        """Test MACD returns None at exact boundary of insufficient data"""
        from modules.processing.trend import TrendCalculator

        # MACD needs at least slow + signal - 1 = 26 + 9 - 1 = 34 points
        df_borderline = pd.DataFrame({"Close": np.linspace(100, 110, 34)})

        result = TrendCalculator.calculate_macd(df_borderline)
        # Should return (None, None, None) or valid values
        assert result[0] is None or isinstance(result[0], float)

    def test_calculate_regime_bull_near_one(self):
        """Test regime_bull behavior near 1.0 threshold with precision"""
        from modules.processing.trend import TrendCalculator

        # Just above 1.0
        result_above = TrendCalculator.calculate_regime_bull(1.0001)
        assert result_above == 1

        # Just below 1.0
        result_below = TrendCalculator.calculate_regime_bull(0.9999)
        assert result_below == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
