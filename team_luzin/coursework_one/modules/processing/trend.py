"""
Trend Factor Calculator

Calculates trend and regime indicators from price data:
- 200-day Moving Average (MA200)
- Bullish/Bearish Regime Flag

Trend factors identify market regime and filter for stocks
in uptrends, reducing whipsaw risk.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class TrendCalculator:
    """Calculate trend and regime indicators from price data."""

    @staticmethod
    def calculate_ma200_ratio(df_ohlcv):
        """
        Calculate ratio of current price to 200-day Simple Moving Average.

        Formula: close / SMA(200)

        Args:
            df_ohlcv: DataFrame with 'close' column (sorted by date)

        Returns:
            ma200_ratio as float
            Returns None if insufficient data

        Example:
            current close = $150
            SMA(200) = $140
            ma200_ratio = 150/140 = 1.071

        Interpretation:
            > 1.0: Price ABOVE 200-day MA (uptrend/bullish)
            < 1.0: Price BELOW 200-day MA (downtrend/bearish)
            = 1.0: Price AT 200-day MA (transition point)

            1.10+: Strong uptrend (price well above MA)
            0.90-: Strong downtrend (price well below MA)

        Why it matters:
            - 200-day MA is professional "trend line"
            - Separates bullish from bearish regimes
            - Filters out downtrend stocks
            - Used by systematic traders globally
        """
        try:
            if len(df_ohlcv) < 200:
                logger.warning(f"Insufficient data for MA200: {len(df_ohlcv)} < 200")
                return None

            # Calculate 200-day SMA
            sma_200 = df_ohlcv["Close"].rolling(window=200).mean()

            # Current price to MA ratio
            current_price = df_ohlcv["Close"].iloc[-1]
            sma_200_value = sma_200.iloc[-1]

            if pd.isna(sma_200_value) or sma_200_value == 0:
                logger.warning("Invalid SMA(200) calculation")
                return None

            ma200_ratio = current_price / sma_200_value
            return float(ma200_ratio)

        except Exception as e:
            logger.error(f"Error calculating MA200 ratio: {e}")
            return None

    @staticmethod
    def calculate_regime_bull(ma200_ratio):
        """
        Determine bullish/bearish regime based on 200-day MA.

        Formula: regime_bull = 1 if ma200_ratio > 1.0, else 0

        Args:
            ma200_ratio: Output from calculate_ma200_ratio()

        Returns:
            regime_bull as int (1 for bullish, 0 for bearish)
            Returns None if input invalid

        Logic:
            regime_bull = 1 → Stock is in UPTREND (bullish)
                             Buy signals more reliable
                             Momentum factors work better
            regime_bull = 0 → Stock is in DOWNTREND (bearish)
                             Avoid or use shorting signals
                             Expect mean reversion

        Example:
            ma200_ratio = 1.071 → regime_bull = 1 (bullish)
            ma200_ratio = 0.950 → regime_bull = 0 (bearish)

        Why it matters:
            - Momentum works better in UPTRENDS
            - In downtrends, avoid going long
            - Simple but effective regime filter
            - Reduces losses in bear markets
        """
        try:
            if ma200_ratio is None:
                return None

            regime = 1 if ma200_ratio > 1.0 else 0
            return int(regime)

        except Exception as e:
            logger.error(f"Error calculating regime: {e}")
            return None

    @staticmethod
    def is_bullish(regime_bull):
        """
        Helper to check if regime is bullish.

        Args:
            regime_bull: From calculate_regime_bull()

        Returns:
            Boolean (True if bullish, False otherwise)
        """
        return regime_bull == 1 if regime_bull is not None else False

    @staticmethod
    def calculate_macd(df_ohlcv, fast=12, slow=26, signal=9):
        """
        Calculate MACD (Moving Average Convergence Divergence) and signal line.

        Formula:
            MACD = EMA(close, 12) - EMA(close, 26)
            Signal = EMA(MACD, 9)
            Histogram = MACD - Signal

        Args:
            df_ohlcv: DataFrame with 'close' column (sorted by date)
            fast: Fast EMA period (default: 12)
            slow: Slow EMA period (default: 26)
            signal: Signal line EMA period (default: 9)

        Returns:
            Tuple of (macd, macd_signal, macd_histogram)
            Returns (None, None, None) if insufficient data

        Example:
            MACD = 2.5 (12-EMA above 26-EMA, bullish)
            Signal = 2.0
            Histogram = 0.5 (positive, momentum increasing)

        Interpretation:
            MACD > 0 & rising: Strong bullish momentum
            MACD < 0 & falling: Strong bearish momentum
            MACD crosses Signal: Trend change signal
            Histogram > 0 & growing: Accelerating uptrend
            Histogram < 0 & shrinking: Momentum reversal warning

        Why it matters:
            - MACD confirms trend direction
            - Signal line crossovers are powerful entry/exit signals
            - Histogram divergences predict trend changes
            - Works well with momentum factors
            - Reduces false signals in choppy markets
        """
        try:
            if len(df_ohlcv) < slow + signal - 1:
                logger.warning(
                    f"Insufficient data for MACD: {len(df_ohlcv)} < {slow + signal - 1}"
                )
                return None, None, None

            close = df_ohlcv["Close"]

            # Calculate EMAs
            ema_fast = close.ewm(span=fast, adjust=False).mean()
            ema_slow = close.ewm(span=slow, adjust=False).mean()

            # Calculate MACD
            macd = ema_fast - ema_slow

            # Calculate Signal line (EMA of MACD)
            macd_signal = macd.ewm(span=signal, adjust=False).mean()

            # Calculate Histogram
            macd_histogram = macd - macd_signal

            # Get latest values
            macd_value = float(macd.iloc[-1])
            signal_value = float(macd_signal.iloc[-1])
            histogram_value = float(macd_histogram.iloc[-1])

            return macd_value, signal_value, histogram_value

        except Exception as e:
            logger.error(f"Error calculating MACD: {e}")
            return None, None, None

    @staticmethod
    def calculate_macd_signal(macd_value, macd_signal_value):
        """
        Generate MACD signal strength indicator.

        Combines MACD and signal line for trade signals:
            2: Strong buy (MACD > 0, above signal, histogram positive)
            1: Buy (MACD > signal OR positive histogram)
            0: Neutral (MACD near signal)
            -1: Sell (MACD < signal OR negative histogram)
            -2: Strong sell (MACD < 0, below signal, histogram negative)

        Args:
            macd_value: MACD value
            macd_signal_value: Signal line value

        Returns:
            Signal strength as int (-2 to 2)
        """
        try:
            if macd_value is None or macd_signal_value is None:
                return 0

            if macd_value > macd_signal_value:
                return 2 if macd_value > 0 else 1
            elif macd_value < macd_signal_value:
                return -2 if macd_value < 0 else -1
            else:
                return 0

        except Exception as e:
            logger.error(f"Error calculating MACD signal: {e}")
            return 0
