"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : FX rate extraction from Yahoo Finance
Project : CW1 - Value + News Sentiment Strategy

Fetches daily exchange rates for the currency pairs required to
normalise valuations across the multi-country universe to USD.

Required pairs (derived from company_static exchange suffixes):
  - GBPUSD=X  (London .L)
  - EURUSD=X  (Paris .PA, Amsterdam .AS, Frankfurt .DE, Madrid .MC, Milan .MI)
  - CADUSD=X  (Toronto .TO)
  - CHFUSD=X  (Zurich .SW)
"""

import time

import pandas as pd
import yfinance as yf

from modules.utils.logger import pipeline_logger

FX_PAIRS = ["GBPUSD=X", "EURUSD=X", "CADUSD=X", "CHFUSD=X"]


def fetch_fx_rates(
    start_date: str,
    end_date: str,
    pairs: list[str] = None,
    max_retries: int = 3,
) -> dict:
    """Fetch daily FX rates for all required currency pairs.

    :param start_date: Start date (YYYY-MM-DD)
    :type start_date: str
    :param end_date: End date (YYYY-MM-DD)
    :type end_date: str
    :param pairs: Override default FX pairs
    :type pairs: list[str] or None
    :param max_retries: Retry attempts per pair
    :type max_retries: int
    :return: Dict mapping pair identifier to OHLC DataFrame
    :rtype: dict

    Example::

        >>> rates = fetch_fx_rates('2024-01-01', '2024-12-31')
        >>> 'GBPUSD=X' in rates
        True
    """
    if pairs is None:
        pairs = FX_PAIRS

    results = {}
    for pair in pairs:
        for attempt in range(max_retries):
            try:
                df = yf.download(
                    pair, start=start_date, end=end_date, progress=False, auto_adjust=False, multi_level_index=False
                )
                if df is not None and not df.empty:
                    # Flatten MultiIndex columns if yfinance ignores multi_level_index=False
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    results[pair] = df
                    pipeline_logger.info("Fetched %d FX rows for %s", len(df), pair)
                    break
                pipeline_logger.warning("Empty FX data for %s (attempt %d)", pair, attempt + 1)
            except Exception as e:
                delay = 2**attempt
                pipeline_logger.warning("FX fetch error for %s: %s — retrying in %ds", pair, e, delay)
                time.sleep(delay)
        else:
            pipeline_logger.error("Failed to fetch FX for %s", pair)
            results[pair] = pd.DataFrame()
        time.sleep(0.5)

    pipeline_logger.info("FX extraction complete: %d/%d pairs", len(results), len(pairs))
    return results
