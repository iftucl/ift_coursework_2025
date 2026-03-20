"""Fetch daily closing prices and shares outstanding from Yahoo Finance."""

import logging
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_prices(symbol: str, start_date: str, end_date: str) -> Optional[dict]:
    """Fetch daily OHLCV history and shares outstanding for a ticker.

    Args:
        symbol: Ticker symbol (e.g. 'AAPL').
        start_date: Start date string 'YYYY-MM-DD'.
        end_date: End date string 'YYYY-MM-DD'.

    Returns:
        Dict with keys symbol, prices (date→price), shares_outstanding, fetched_at.
        Returns None if fetch fails.
    """
    try:
        ticker = yf.Ticker(symbol.strip())
        hist = ticker.history(start=start_date, end=end_date, auto_adjust=True)

        if hist.empty:
            logger.warning(f"No price history returned for {symbol}")
            return None

        prices = {str(ts.date()): round(float(close), 4) for ts, close in hist["Close"].items()}

        info = ticker.info
        shares_outstanding = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")

        return {
            "symbol": symbol.strip(),
            "prices": prices,
            "shares_outstanding": shares_outstanding,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.error(f"Failed to fetch prices for {symbol}: {exc}")
        return None
