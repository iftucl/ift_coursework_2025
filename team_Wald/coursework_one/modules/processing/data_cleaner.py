"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Data cleaning and validation utilities
Project : CW1 - Value + News Sentiment Strategy

Provides validation and cleaning functions for raw data before
loading into PostgreSQL.  Handles common data quality issues:
  - NaN/Inf values in numeric columns
  - Duplicate date entries per ticker
  - Negative prices or volumes
  - Missing required fields
"""

import numpy as np
import pandas as pd

from modules.utils.logger import pipeline_logger


def clean_price_dataframe(df: pd.DataFrame, ticker: str, currency: str = "USD") -> list[dict]:
    """Clean and validate a raw yfinance price DataFrame.

    Converts the DataFrame into a list of dicts suitable for
    ``upsert_daily_prices``, removing invalid rows.

    :param df: Raw OHLCV DataFrame from yfinance
    :type df: pd.DataFrame
    :param ticker: Ticker symbol for the records
    :type ticker: str
    :param currency: Currency code for the price data
    :type currency: str
    :return: List of clean price record dicts
    :rtype: list[dict]

    Example::

        >>> import pandas as pd
        >>> df = pd.DataFrame({'Open': [150.0], 'High': [152.0],
        ...     'Low': [149.0], 'Close': [151.0], 'Adj Close': [150.5],
        ...     'Volume': [1000000]}, index=pd.to_datetime(['2024-01-02']))
        >>> records = clean_price_dataframe(df, 'AAPL')
        >>> len(records)
        1
    """
    if df is None or df.empty:
        return []

    records = []
    for idx, row in df.iterrows():
        try:
            dt = pd.Timestamp(idx)
            cob_date = dt.strftime("%Y-%m-%d")
        except Exception:
            continue

        open_p = _validate_price(row.get("Open"))
        high_p = _validate_price(row.get("High"))
        low_p = _validate_price(row.get("Low"))
        close_p = _validate_price(row.get("Close"))
        adj_close = _validate_price(row.get("Adj Close"))
        volume = _validate_volume(row.get("Volume"))

        if close_p is None:
            continue

        records.append(
            {
                "symbol": ticker,
                "cob_date": cob_date,
                "open_price": open_p,
                "high_price": high_p,
                "low_price": low_p,
                "close_price": close_p,
                "adj_close_price": adj_close,
                "volume": volume,
                "currency": currency,
            }
        )

    original = len(df)
    cleaned = len(records)
    if original > cleaned:
        pipeline_logger.warning(
            "Cleaned %s prices: %d → %d rows (dropped %d invalid)",
            ticker,
            original,
            cleaned,
            original - cleaned,
        )
    return records


def clean_fx_dataframe(df: pd.DataFrame, currency_pair: str) -> list[dict]:
    """Clean a raw yfinance FX rate DataFrame.

    :param df: Raw OHLC DataFrame for FX pair
    :type df: pd.DataFrame
    :param currency_pair: FX pair identifier (e.g. 'GBPUSD=X')
    :type currency_pair: str
    :return: List of clean FX rate record dicts
    :rtype: list[dict]
    """
    if df is None or df.empty:
        return []

    # Flatten MultiIndex columns (yfinance 1.x may return them even for single tickers)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    records = []
    for idx, row in df.iterrows():
        try:
            cob_date = pd.Timestamp(idx).strftime("%Y-%m-%d")
        except Exception:
            continue

        close_r = _validate_price(row.get("Close"))
        if close_r is None:
            continue

        records.append(
            {
                "currency_pair": currency_pair,
                "cob_date": cob_date,
                "open_rate": _validate_price(row.get("Open")),
                "high_rate": _validate_price(row.get("High")),
                "low_rate": _validate_price(row.get("Low")),
                "close_rate": close_r,
            }
        )
    return records


def validate_company_info(info: dict) -> bool:
    """Check if a company info dict has minimum required fields.

    :param info: Dict from fetch_company_info
    :type info: dict
    :return: True if valid for scoring
    :rtype: bool
    """
    if not info or not info.get("symbol"):
        return False
    ratio_fields = ["pe_ratio", "pb_ratio", "ev_ebitda", "dividend_yield", "debt_equity"]
    has_any = any(info.get(f) is not None for f in ratio_fields)
    return has_any


def _validate_price(val) -> float:
    """Validate a price value — must be non-negative and finite.

    :param val: Raw price value
    :return: Valid float or None
    :rtype: float or None
    """
    if val is None:
        return None
    try:
        f = float(val)
        if np.isfinite(f) and f >= 0:
            return round(f, 6)
        return None
    except (TypeError, ValueError):
        return None


def _validate_volume(val) -> int:
    """Validate a volume value — must be non-negative integer.

    :param val: Raw volume value
    :return: Valid integer or None
    :rtype: int or None
    """
    if val is None:
        return None
    try:
        v = int(float(val))
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None
