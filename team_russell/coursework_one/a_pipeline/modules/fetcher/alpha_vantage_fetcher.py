"""Fetch quarterly financial statements from Alpha Vantage API.

Free tier limit: 25 requests per day.
Each company requires 2 calls (balance sheet + income statement).
A rate-limit delay is applied between every request.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"
_RATE_LIMIT_DELAY_SECONDS = 12  # 5 requests/minute on free tier


def _get(function: str, symbol: str, api_key: str) -> Optional[dict]:
    """Generic Alpha Vantage GET with rate-limit delay and error handling."""
    params = {"function": function, "symbol": symbol.strip(), "apikey": api_key}
    try:
        response = requests.get(_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Alpha Vantage returns error messages inside the JSON body
        if "Note" in data or "Information" in data:
            msg = data.get("Note") or data.get("Information")
            logger.warning(f"Alpha Vantage rate limit hit for {symbol}: {msg}")
            return None

        return data

    except requests.RequestException as exc:
        logger.error(f"HTTP error fetching {function} for {symbol}: {exc}")
        return None
    finally:
        time.sleep(_RATE_LIMIT_DELAY_SECONDS)


def fetch_balance_sheet(symbol: str, api_key: str) -> Optional[dict]:
    """Fetch quarterly balance sheet data for a symbol.

    Args:
        symbol: Ticker symbol.
        api_key: Alpha Vantage API key.

    Returns:
        Dict with symbol, data (raw API response), fetched_at. None on failure.
    """
    data = _get("BALANCE_SHEET", symbol, api_key)
    if data is None or "quarterlyReports" not in data:
        logger.warning(f"No balance sheet data for {symbol}")
        return None

    return {
        "symbol": symbol.strip(),
        "type": "balance_sheet",
        "data": data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_income_statement(symbol: str, api_key: str) -> Optional[dict]:
    """Fetch quarterly income statement data for a symbol.

    Args:
        symbol: Ticker symbol.
        api_key: Alpha Vantage API key.

    Returns:
        Dict with symbol, data (raw API response), fetched_at. None on failure.
    """
    data = _get("INCOME_STATEMENT", symbol, api_key)
    if data is None or "quarterlyReports" not in data:
        logger.warning(f"No income statement for {symbol}")
        return None

    return {
        "symbol": symbol.strip(),
        "type": "income_statement",
        "data": data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
