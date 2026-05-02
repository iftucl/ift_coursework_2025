"""
Momentum Factor Calculator

Calculates momentum metrics from price data:
- 6-month momentum
- 12-month momentum  
- Risk-adjusted momentum (RAM)

Momentum measures the rate of change in price over a period,
indicating trend strength and potential mean reversion.
"""

import logging

logger = logging.getLogger(__name__)


class MomentumCalculator:
    """Calculate momentum factors from price series."""

    @staticmethod
    def calculate_momentum(df_ohlcv, window=252):
        """
        Calculate price momentum over specified period.

        Formula: (Price_today / Price_window_ago) - 1

        Args:
            df_ohlcv: DataFrame with 'close' column (sorted by date)
            window: Number of trading days (126 for 6m, 252 for 12m)

        Returns:
            Momentum as decimal (e.g., 0.50 for +50%)
            Returns None if insufficient data

        Example:
            close_today = $150
            close_252_days_ago = $100
            momentum_12m = (150/100) - 1 = 0.50 (50% gain)

        Interpretation:
            > 0: Price has increased (bullish)
            < 0: Price has decreased (bearish)
            High absolute value: Strong trend
        """
        try:
            if len(df_ohlcv) < window + 1:
                logger.warning(f"Insufficient data: {len(df_ohlcv)} < {window + 1}")
                return None

            current_price = df_ohlcv["Close"].iloc[-1]
            past_price = df_ohlcv["Close"].iloc[-(window + 1)]

            if past_price == 0:
                return None

            momentum = (current_price / past_price) - 1
            return momentum

        except Exception as e:
            logger.error(f"Error calculating momentum: {e}")
            return None

    @staticmethod
    def calculate_momentum_6m(df_ohlcv):
        """Calculate 6-month momentum (126 trading days)."""
        return MomentumCalculator.calculate_momentum(df_ohlcv, window=126)

    @staticmethod
    def calculate_momentum_12m(df_ohlcv):
        """Calculate 12-month momentum (252 trading days)."""
        return MomentumCalculator.calculate_momentum(df_ohlcv, window=252)

    @staticmethod
    def calculate_risk_adjusted_momentum(momentum, volatility):
        """
        Calculate risk-adjusted momentum (RAM).

        Formula: Momentum / Volatility

        Args:
            momentum: Price momentum (decimal)
            volatility: Annualized volatility (from RiskCalculator)

        Returns:
            RAM score as float
            Returns None if calculation not possible

        Interpretation:
            Positive RAM: Upward momentum with controllable risk
            Negative RAM: Downward momentum (declining price)
            Higher |RAM|: Stronger risk-adjusted signal

        Example:
            momentum = 0.50 (50% return)
            volatility = 0.25 (25% annualized volatility)
            RAM = 0.50 / 0.25 = 2.0

            Means: 50% return per 25% risk = good risk-reward
        """
        try:
            if momentum is None or volatility is None:
                return None

            if volatility == 0:
                logger.warning("Zero volatility in RAM calculation")
                return None

            ram = momentum / volatility
            return ram

        except Exception as e:
            logger.error(f"Error calculating RAM: {e}")
            return None
