"""
Risk Factor Calculator

Calculates risk metrics from OHLCV data:
- 6-month and 12-month volatility
- Average True Range (ATR) as % of price

Risk factors measure price variability and inform position sizing,
stop-loss levels, and portfolio diversification.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RiskCalculator:
    """Calculate risk and volatility metrics from OHLCV data."""

    @staticmethod
    def calculate_volatility(df_ohlcv, window):
        """
        Calculate annualized volatility from daily returns.

        Formula: sqrt(252) × std(daily_log_returns)

        Args:
            df_ohlcv: DataFrame with 'close' column (sorted by date)
            window: Number of trading days (126 for 6m, 252 for 12m)

        Returns:
            Annualized volatility as float (e.g., 0.25 for 25%)
            Returns None if insufficient data

        Example:
            Daily log returns: [-0.01, +0.02, -0.015, ...]
            std = 0.0158
            vol_12m = 0.0158 × sqrt(252) = 0.251 (25.1% annualized)

        Interpretation:
            0.10-0.15: Low volatility (stable stocks)
            0.15-0.25: Moderate volatility (typical)
            0.25-0.40: High volatility (risky)
            > 0.40: Very high volatility (avoid)

        Why it matters:
            - Higher vol = larger potential losses
            - Used for position sizing (risk parity)
            - Component of Risk-Adjusted Momentum (RAM)
        """
        try:
            if len(df_ohlcv) < window + 1:
                logger.warning(
                    f"Insufficient data for vol calc: {len(df_ohlcv)} < {window + 1}"
                )
                return None

            # Calculate daily log returns
            prices = df_ohlcv["Close"].iloc[-(window + 1) :]
            log_returns = np.log(prices / prices.shift(1)).dropna()

            if len(log_returns) == 0:
                return None

            # Annualized volatility
            volatility = log_returns.std() * np.sqrt(252)

            if pd.isna(volatility):
                return None

            return float(volatility)

        except Exception as e:
            logger.error(f"Error calculating volatility: {e}")
            return None

    @staticmethod
    def calculate_volatility_6m(df_ohlcv):
        """Calculate 6-month volatility (126 trading days)."""
        return RiskCalculator.calculate_volatility(df_ohlcv, window=126)

    @staticmethod
    def calculate_volatility_12m(df_ohlcv):
        """Calculate 12-month volatility (252 trading days)."""
        return RiskCalculator.calculate_volatility(df_ohlcv, window=252)

    @staticmethod
    def calculate_atr_pct(df_ohlcv, period=14):
        """
        Calculate Average True Range as % of closing price.

        Formula: ATR / close × 100

        Where ATR is computed as:
        - True Range (TR) = max(H-L, |H-PC|, |L-PC|)
        - ATR = EMA(TR, period)

        Args:
            df_ohlcv: DataFrame with OHLC columns (handles both yfinance formats)
            period: ATR period (default 14)

        Returns:
            ATR % as float (e.g., 2.5 for 2.5% of price)
            Returns None if insufficient data

        Example:
            Today's range: H=$155, L=$145 → H-L = $10
            Previous close: $148
            TR = max(10, |155-148|, |145-148|) = 10
            ATR = EMA(TR) ≈ $2.50
            close = $150
            ATR% = 2.50/150 × 100 = 1.67%

        Interpretation:
            0.5-1.0%: Low volatility (stable)
            1.0-2.5%: Moderate volatility
            > 2.5%: High volatility (risky)

        Why it matters:
            - Practical measure of "typical daily move"
            - Used to set stop-losses (e.g., 2× ATR)
            - More robust than simple H-L range
        """
        try:
            if len(df_ohlcv) < period:
                logger.warning(
                    f"Insufficient data for ATR calc: {len(df_ohlcv)} < {period}"
                )
                return None

            # Handle yfinance MultiIndex columns (e.g., ('Close', 'AAPL'))
            if isinstance(df_ohlcv.columns, pd.MultiIndex):
                # Get first symbol from MultiIndex
                symbol = df_ohlcv.columns.get_level_values(1)[0]
                high = df_ohlcv["High", symbol].values
                low = df_ohlcv["Low", symbol].values
                close = df_ohlcv["Close", symbol].values
            else:
                # Standard column names
                high_col = "High" if "High" in df_ohlcv.columns else "high"
                low_col = "Low" if "Low" in df_ohlcv.columns else "low"
                close_col = "Close" if "Close" in df_ohlcv.columns else "close"
                high = df_ohlcv[high_col].values
                low = df_ohlcv[low_col].values
                close = df_ohlcv[close_col].values

            # Calculate True Range
            high_low = high - low
            high_close = np.abs(high - np.roll(close, 1))
            low_close = np.abs(low - np.roll(close, 1))

            # True Range is max of three
            tr = np.maximum(np.maximum(high_low, high_close), low_close)

            # Average True Range (14-period EMA using pandas)
            atr_series = pd.Series(tr).ewm(span=period, adjust=False).mean()
            atr = atr_series.iloc[-1]

            # ATR as percentage of current close
            atr_pct = (atr / close[-1]) * 100

            if pd.isna(atr_pct):
                return None

            return float(atr_pct)

        except Exception as e:
            logger.error(f"Error calculating ATR: {e}")
            return None

    @staticmethod
    def calculate_var_95(df_ohlcv, window=252):
        """
        Calculate Value-at-Risk (VaR) at 95% confidence level using historical method.

        Formula: VaR_95% = 5th percentile of daily log returns

        Args:
            df_ohlcv: DataFrame with 'close' column (sorted by date)
            window: Number of trading days (default 252 for 1 year)

        Returns:
            VaR as negative float (e.g., -0.035 means max loss is 3.5% with 95% confidence)
            Returns None if insufficient data

        Example:
            Daily returns: [-0.02, +0.015, -0.01, +0.025, ..., -0.035]
            Sorted: [-0.035, -0.025, -0.015, ..., +0.035]
            5th percentile (252 × 0.05 = ~13th value): -0.035
            → 95% of days lose ≤ 3.5%, 5% lose > 3.5%

        Interpretation:
            -0.02: On bad days, expect to lose up to 2% (lower risk)
            -0.05: On bad days, expect to lose up to 5% (moderate risk)
            -0.10: On bad days, expect to lose up to 10% (high risk)

        Why it matters:
            - Captures tail risk (worst-case scenarios)
            - Helps size positions (e.g., don't allocate 5% to -10% VaR stock)
            - Used in portfolio scoring: score = 0.6*Z(momentum) + 0.2*Z(liquidity) - 0.2*Z(risk)
              (higher VaR = worse, so we subtract it)

        Advantages over volatility:
            - Volatility (std dev) treats upside and downside equally
            - VaR focuses on downside risk only (what investors care about)
            - Captures fat tails better for skewed return distributions

        Historical method advantages:
            - No parametric assumptions (vs Gaussian)
            - Uses actual observed returns
            - Good for up to 252 observations (1 year)

        Limitations:
            - May miss unprecedented risk if market regime changes
            - Doesn't account for liquidity in crises
            - 95% confidence leaves 5% of days with worse outcomes
        """
        try:
            if len(df_ohlcv) < window:
                logger.warning(
                    f"Insufficient data for VaR calc: {len(df_ohlcv)} < {window}"
                )
                return None

            # Calculate daily log returns over the window
            prices = df_ohlcv["Close"].iloc[-window:]
            log_returns = np.log(prices / prices.shift(1)).dropna()

            if len(log_returns) < window - 1:
                logger.warning(f"Not enough valid returns for VaR: {len(log_returns)}")
                return None

            # Historical VaR: 5th percentile (95% confidence level)
            # At 95% confidence, 5% of returns are worse than this
            var_95 = np.percentile(log_returns, 5)

            if pd.isna(var_95):
                return None

            # Return as negative number (convention: VaR expressed as magnitude of loss)
            # E.g., -0.035 means max expected loss is 3.5%
            return float(var_95)

        except Exception as e:
            logger.error(f"Error calculating VaR: {e}")
            return None
