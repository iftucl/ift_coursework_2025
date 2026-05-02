"""
Market Data Loader

Loads and processes market data from yfinance and database sources.
Handles data validation, sector filtering, and universe preparation.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class MarketDataLoader:
    """Load and prepare market data for analysis."""

    @staticmethod
    def download_price_data(
        symbols: List[str], end_date: Optional[datetime] = None, periods: int = 400
    ) -> pd.DataFrame:
        """
        Download historical price data for symbols.

        Args:
            symbols: List of stock symbols
            end_date: End date for download (default: today)
            periods: Number of trading days to download

        Returns:
            DataFrame with OHLCV data
        """
        if end_date is None:
            end_date = datetime.now()

        start_date = end_date - timedelta(days=periods)

        logger.info(f"Downloading price data for {len(symbols)} symbols...")
        try:
            data = yf.download(
                " ".join(symbols), start=start_date, end=end_date, progress=False
            )
            logger.info(f"✓ Downloaded data for {len(symbols)} symbols")
            return data
        except Exception as e:
            logger.error(f"Error downloading data: {e}")
            raise

    @staticmethod
    def load_from_csv(filepath: str) -> pd.DataFrame:
        """Load market data from CSV file."""
        logger.info(f"Loading data from {filepath}...")
        df = pd.read_csv(filepath)
        logger.info(f"✓ Loaded {len(df)} rows from {filepath}")
        return df

    @staticmethod
    def validate_price_data(df: pd.DataFrame) -> bool:
        """Validate price data contains required columns."""
        required_cols = ["Close", "Volume"]
        missing = [col for col in required_cols if col not in df.columns]

        if missing:
            logger.warning(f"Missing columns: {missing}")
            return False

        logger.info("✓ Price data validation passed")
        return True
