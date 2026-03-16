"""
Liquidity Factor Calculator

Calculates liquidity metrics from volume and price data:
- 60-day average dollar volume

Liquidity measures trading capacity and ensures positions can be
executed in live portfolio management without market impact.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class LiquidityCalculator:
    """Calculate liquidity factors from OHLCV data."""

    @staticmethod
    def calculate_avg_dollar_volume_60d(df_ohlcv, window=60):
        """
        Calculate 60-day average dollar volume.

        Formula: avg(close × volume) over last 60 trading days

        Args:
            df_ohlcv: DataFrame with 'close' and 'volume' columns
            window: Number of trading days (default 60)

        Returns:
            Average daily dollar volume as float
            Returns None if insufficient data

        Example:
            Day 1: close=$150, volume=2M → dollar_volume=$300M
            Day 2: close=$152, volume=1.8M → dollar_volume=$273.6M
            ...
            avg_60d = mean of last 60 days' dollar volumes

        Interpretation:
            > $10M: Highly liquid (easy to buy/sell large positions)
            $1M-$10M: Moderate liquidity
            < $1M: Illiquid (avoid for portfolio)

        Why it matters:
            - Prevents slippage (price movement from order impact)
            - Ensures exits in market stress
            - Reduces bid-ask spread impact
        """
        try:
            if len(df_ohlcv) < window:
                logger.warning(
                    f"Insufficient data for liquidity calc: {len(df_ohlcv)} < {window}"
                )
                return None

            # Calculate daily dollar volume
            df_ohlcv = df_ohlcv.copy()
            df_ohlcv["dollar_volume"] = df_ohlcv["Close"] * df_ohlcv["Volume"]

            # Average last 60 days
            avg_dv = df_ohlcv["dollar_volume"].tail(window).mean()

            if pd.isna(avg_dv):
                return None

            return float(avg_dv)

        except Exception as e:
            logger.error(f"Error calculating dollar volume: {e}")
            return None

    @staticmethod
    def is_liquid(avg_dollar_volume, min_threshold=1_000_000):
        """
        Check if stock meets liquidity threshold.

        Args:
            avg_dollar_volume: From calculate_avg_dollar_volume_60d()
            min_threshold: Minimum required (default $1M/day)

        Returns:
            Boolean (True if liquid, False otherwise)

        Example:
            avg_dv = 15_000_000  → is_liquid() → True
            avg_dv = 500_000     → is_liquid() → False
        """
        if avg_dollar_volume is None:
            return False

        return avg_dollar_volume >= min_threshold
