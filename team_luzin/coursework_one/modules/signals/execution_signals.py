"""
Execution Signals Module

Generates trading signals based on technical indicators:
- MACD for trend identification
- ATR for volatility/risk assessment  
- Liquidity filters for tradability
- Combined signal generation (BUY/SELL/HOLD)
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ExecutionSignals:
    """Generate trading execution signals from technical indicators."""

    @staticmethod
    def extract_close_prices(df: pd.DataFrame) -> Optional[pd.Series]:
        """
        Extract Close prices from OHLCV DataFrame.

        Args:
            df: DataFrame with price data (Close column required)

        Returns:
            Series of Close prices, or None if extraction fails
        """
        try:
            if df is None or df.empty:
                return None

            if "Close" not in df.columns:
                logger.warning("Close column not found in DataFrame")
                return None

            close_series = df["Close"]
            if close_series.isna().all():
                logger.warning("All Close prices are NaN")
                return None

            return close_series
        except Exception as e:
            logger.error(f"Error extracting close prices: {e}")
            return None

    @staticmethod
    def generate_macd_signal(close_prices) -> pd.Series:
        """
        Generate MACD-based trend signal.

        Args:
            close_prices: Series or DataFrame with Close prices

        Returns:
            Series with trend signals (1=bullish, -1=bearish, 0=neutral)
        """
        try:
            # Handle both Series and DataFrame inputs
            if isinstance(close_prices, pd.DataFrame):
                close = close_prices["Close"]
            else:
                close = close_prices

            if close is None or len(close) == 0:
                raise ValueError("No close prices available")

            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd = ema12 - ema26
            signal_line = macd.ewm(span=9).mean()

            trend = np.where(macd > signal_line, 1, np.where(macd < signal_line, -1, 0))
            logger.debug(
                f"✓ MACD signal generated: {np.sum(trend == 1)} bullish, {np.sum(trend == -1)} bearish"
            )

            return pd.Series(trend, index=close.index)
        except Exception as e:
            logger.error(f"Error generating MACD signal: {e}")
            raise

    @staticmethod
    def generate_atr_signal(
        df: pd.DataFrame, period: int = 14, threshold: float = 2.0
    ) -> pd.Series:
        """
        Generate ATR-based risk signal.

        Args:
            df: DataFrame with OHLC prices
            period: ATR calculation period
            threshold: Risk threshold as multiple of ATR

        Returns:
            Series with risk signals (1=low risk, -1=high risk)
        """
        try:
            high = df["High"]
            low = df["Low"]
            close = df["Close"]

            tr = np.maximum(
                high - low,
                np.maximum(abs(high - close.shift()), abs(low - close.shift())),
            )
            atr = pd.Series(tr).rolling(window=period).mean()

            current_price_range = high - low
            risk_signal = np.where(current_price_range <= threshold * atr, 1, -1)

            logger.debug(
                f"✓ ATR signal generated: {np.sum(risk_signal == 1)} low risk, {np.sum(risk_signal == -1)} high risk"
            )

            return pd.Series(risk_signal, index=df.index)
        except Exception as e:
            logger.error(f"Error generating ATR signal: {e}")
            raise

    @staticmethod
    def generate_liquidity_signal(
        df: pd.DataFrame,
        volume_threshold: float = 1000000.0,
        price_threshold: float = 5.0,
    ) -> pd.Series:
        """
        Generate liquidity signal for tradability.

        Args:
            df: DataFrame with Volume and Close prices
            volume_threshold: Minimum daily volume
            price_threshold: Minimum stock price

        Returns:
            Series with liquidity signals (1=liquid, -1=illiquid)
        """
        try:
            volume = df["Volume"]
            close = df["Close"]

            is_liquid = (volume >= volume_threshold) & (close >= price_threshold)
            liquidity_signal = np.where(is_liquid, 1, -1)

            logger.debug(
                f"✓ Liquidity signal generated: {np.sum(liquidity_signal == 1)} liquid stocks"
            )

            return pd.Series(liquidity_signal, index=df.index)
        except Exception as e:
            logger.error(f"Error generating liquidity signal: {e}")
            raise

    @staticmethod
    def combine_signals(
        macd_signal: pd.Series,
        atr_signal: pd.Series,
        liquidity_signal: pd.Series,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.Series:
        """
        Combine individual signals into final execution signal.

        Args:
            macd_signal: Trend signal
            atr_signal: Risk signal
            liquidity_signal: Liquidity signal
            weights: Weight for each signal (default: equal)

        Returns:
            Final signal: 1=BUY, 0=HOLD, -1=SELL
        """
        if weights is None:
            weights = {"macd": 0.4, "atr": 0.3, "liquidity": 0.3}

        try:
            # Normalize signals to [0, 1]
            macd_normalized = (macd_signal + 1) / 2
            atr_normalized = (atr_signal + 1) / 2
            liquidity_normalized = (liquidity_signal + 1) / 2

            # Weighted combination
            combined = (
                weights["macd"] * macd_normalized
                + weights["atr"] * atr_normalized
                + weights["liquidity"] * liquidity_normalized
            )

            # Generate final signal
            final_signal = np.where(
                combined >= 0.6,
                1,  # BUY
                np.where(combined <= 0.4, -1, 0),  # SELL vs HOLD
            )

            logger.info(
                f"✓ Combined signal: {np.sum(final_signal == 1)} BUY, {np.sum(final_signal == -1)} SELL, {np.sum(final_signal == 0)} HOLD"
            )

            return pd.Series(final_signal, index=macd_signal.index)
        except Exception as e:
            logger.error(f"Error combining signals: {e}")
            raise
