"""
Price data extraction module using Yahoo Finance
Fetches historical stock price data for momentum calculations
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class PriceDataExtractor:
    """Extract historical price data from Yahoo Finance."""

    def __init__(self, years: int = 5):
        """
        Initialize price data extractor.

        Args:
            years: Number of years of historical data to fetch (default: 5)
        """
        self.years = years
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=365 * years)
        logger.info(f"Price extractor initialized for {years} years of data")
        logger.info(f"Date range: {self.start_date.date()} to {self.end_date.date()}")

    def fetch_price_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch historical price data for a single stock.

        Args:
            symbol (str): Stock ticker symbol (e.g., 'AAPL')

        Returns:
            DataFrame with OHLCV data or None if fetch fails
        """
        try:
            logger.debug(f"Fetching price data for {symbol}...")
            ticker = yf.Ticker(symbol)

            # Fetch historical data
            hist = ticker.history(start=self.start_date, end=self.end_date)

            if hist.empty:
                logger.warning(f"No price data found for {symbol}")
                return None

            logger.info(f"✓ Fetched {len(hist)} days of data for {symbol}")
            return hist

        except Exception as e:
            logger.error(f"Error fetching price data for {symbol}: {e}")
            return None

    def fetch_multiple_prices(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Fetch price data for multiple stocks.

        Args:
            symbols (List[str]): List of stock ticker symbols

        Returns:
            Dictionary with symbol as key and price data as value
        """
        results = {}
        successful = 0
        failed = 0

        logger.info(f"Fetching price data for {len(symbols)} stocks...")

        for i, symbol in enumerate(symbols, 1):
            logger.info(f"  [{i}/{len(symbols)}] {symbol.strip()}")
            data = self.fetch_price_data(symbol.strip())

            if data is not None:
                results[symbol.strip()] = data
                successful += 1
            else:
                failed += 1

        logger.info(f"Fetch complete: {successful} successful, {failed} failed")
        return results

    def calculate_returns(
        self, price_data: pd.DataFrame, periods: List[int] = None
    ) -> Dict[str, float]:
        """
        Calculate returns for specified periods.

        Args:
            price_data (pd.DataFrame): Historical price data (must have 'Close' column)
            periods (List[int]): Number of trading days (e.g., [126, 252] for 6m, 12m)

        Returns:
            Dictionary with period labels and returns
        """
        if periods is None:
            periods = [
                126,
                252,
            ]  # 6-month (126 trading days) and 12-month (252 trading days)

        returns = {}

        if price_data.empty or len(price_data) < max(periods):
            logger.warning("Insufficient price data for return calculation")
            return returns

        current_price = price_data["Close"].iloc[-1]

        for period in periods:
            if len(price_data) >= period:
                past_price = price_data["Close"].iloc[-period]
                period_return = (current_price - past_price) / past_price
                period_label = f"{period // 21}m_return"  # Convert trading days to months (approx 21 trading days/month)
                returns[period_label] = period_return
                logger.debug(f"  {period_label}: {period_return:.2%}")

        return returns

    def calculate_momentum_score(self, price_data: pd.DataFrame) -> float:
        """
        Calculate a simple momentum score (0-100).

        Momentum = (Current Price - SMA50) / SMA50 * 100
        Where SMA50 = 50-day simple moving average

        Args:
            price_data (pd.DataFrame): Historical price data

        Returns:
            Momentum score (float)
        """
        try:
            if len(price_data) < 50:
                logger.warning("Insufficient data for 50-day SMA calculation")
                return 0.0

            sma_50 = price_data["Close"].tail(50).mean()
            current_price = price_data["Close"].iloc[-1]
            momentum = ((current_price - sma_50) / sma_50) * 100

            return momentum
        except Exception as e:
            logger.error(f"Error calculating momentum: {e}")
            return 0.0

    def extract_company_metrics(self, symbol: str, price_data: pd.DataFrame) -> Dict:
        """
        Extract key metrics for a company.

        Args:
            symbol (str): Stock ticker symbol
            price_data (pd.DataFrame): Historical price data

        Returns:
            Dictionary with extracted metrics
        """
        if price_data is None or price_data.empty:
            return {}

        try:
            current_price = price_data["Close"].iloc[-1]
            returns = self.calculate_returns(price_data)
            momentum = self.calculate_momentum_score(price_data)

            # Calculate volatility (annualized)
            daily_returns = price_data["Close"].pct_change()
            volatility = daily_returns.std() * (252**0.5)  # Annualized

            metrics = {
                "symbol": symbol,
                "current_price": current_price,
                "momentum_score": momentum,
                "volatility": volatility,
                "data_points": len(price_data),
                **returns,
            }

            logger.debug(
                f"Extracted metrics for {symbol}: price=${current_price:.2f}, momentum={momentum:.1f}"
            )
            return metrics

        except Exception as e:
            logger.error(f"Error extracting metrics for {symbol}: {e}")
            return {}

    def extract_all_metrics(
        self, symbols_to_data: Dict[str, pd.DataFrame]
    ) -> List[Dict]:
        """
        Extract metrics for all companies.

        Args:
            symbols_to_data (Dict): Dictionary mapping symbols to price data

        Returns:
            List of dictionaries with company metrics
        """
        all_metrics = []

        logger.info(f"Extracting metrics for {len(symbols_to_data)} companies...")

        for symbol, price_data in symbols_to_data.items():
            metrics = self.extract_company_metrics(symbol, price_data)
            if metrics:
                all_metrics.append(metrics)

        logger.info(f"✓ Extracted metrics for {len(all_metrics)} companies")
        return all_metrics

    def organize_prices_by_ticker_year(
        self, symbols_to_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, Dict[int, pd.DataFrame]]:
        """
        Organize price data by ticker and year for data lake partitioning.

        Args:
            symbols_to_data (Dict): Dictionary mapping symbols to price data

        Returns:
            Dict mapping ticker -> {year -> DataFrame}
        """
        organized = {}

        for symbol, df in symbols_to_data.items():
            organized[symbol] = {}

            # Ensure Date is in datetime format
            if "Date" not in df.columns:
                df_copy = df.reset_index()
                df_copy.rename(columns={"Date": "Date"}, inplace=True)
            else:
                df_copy = df.copy()

            df_copy["Date"] = pd.to_datetime(df_copy["Date"])

            # Group by year
            for year, year_group in df_copy.groupby(df_copy["Date"].dt.year):
                organized[symbol][year] = year_group.reset_index(drop=True)

        logger.info("Organized price data by ticker and year")
        return organized
