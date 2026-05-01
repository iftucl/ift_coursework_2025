"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Load investable universe from company_static table
Project : CW1 - Value + News Sentiment Strategy

Reads the 678-company universe from the PostgreSQL table
``systematic_equity.company_static``.  Always reads fresh from
the database to handle additions/removals (Assignment Spec §3).

Addresses Spec §7.2 Issue 1: ticker symbols in company_static
contain trailing whitespace which must be stripped.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from modules.db.postgres_connection import get_db_client
from modules.utils.logger import pipeline_logger


def load_companies(db_config: dict = None, **kwargs) -> pd.DataFrame:
    """Load the full investable universe from company_static.

    Returns a cleaned DataFrame with trimmed ticker symbols.
    The company_static table is seeded by Docker postgres_seed
    from the provided CSV file.

    :param db_config: PostgreSQL config dict from conf.yaml
    :type db_config: dict or None
    :return: DataFrame with columns [symbol, security, gics_sector,
             gics_industry, country, region]
    :rtype: pd.DataFrame

    Example::

        >>> df = load_companies(conf['config']['Database']['Postgres'])
        >>> len(df)
        678
    """
    client = get_db_client(db_config, **kwargs)
    try:
        query = """
            SELECT TRIM(symbol) AS symbol,
                   security,
                   gics_sector,
                   gics_industry,
                   TRIM(country) AS country,
                   region
            FROM systematic_equity.company_static
        """
        df = client.execute_query_df(query)
        df["symbol"] = df["symbol"].str.strip()
        pipeline_logger.info("Loaded %d companies from company_static", len(df))
        return df
    finally:
        client.close()


def detect_inactive_tickers(
    tickers: list[str],
    max_workers: int = 12,
    timeout_per_ticker: float = 20.0,
) -> set[str]:
    """Dynamically detect delisted/inactive tickers via live yfinance verification.

    Uses a multi-signal approach inspired by production pipelines:
      1. Parallel fast_info checks for all tickers (regularMarketPrice)
      2. Tickers with no valid market price are confirmed inactive

    Rate-limit awareness: HTTP 401/403 errors and timeouts are NOT
    counted as delisted — only tickers that return no price data after
    successful API responses are considered inactive.

    This is non-hardcoded, non-cached, and runs every pipeline invocation
    to adapt to actual market state.

    :param tickers: Full ticker list from company_static
    :type tickers: list[str]
    :param max_workers: Number of parallel verification workers
    :type max_workers: int
    :param timeout_per_ticker: Timeout per live check in seconds
    :type timeout_per_ticker: float
    :return: Set of confirmed inactive ticker symbols
    :rtype: set[str]
    """
    import time

    import yfinance as yf

    inactive = set()
    rate_limited = set()

    def _check_live(raw_ticker: str) -> tuple[str, str]:
        """Return (ticker, status) where status is 'active', 'inactive', or 'error'."""
        yf_ticker = prepare_ticker(raw_ticker)
        try:
            t = yf.Ticker(yf_ticker)
            fi = t.fast_info
            price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_previous_close", None)
            if price is None or float(price) <= 0:
                return (raw_ticker, "inactive")
            return (raw_ticker, "active")
        except Exception as e:
            err_str = str(e).lower()
            # Rate-limiting or auth errors — ticker may be active
            if any(kw in err_str for kw in ("401", "403", "unauthorized", "crumb", "rate", "too many")):
                return (raw_ticker, "error")
            # Connection/timeout errors — don't assume delisted
            if any(kw in err_str for kw in ("timeout", "connection", "reset", "broken pipe")):
                return (raw_ticker, "error")
            # Other errors (e.g. "no data found", genuine delisting)
            return (raw_ticker, "inactive")

    pipeline_logger.info(
        "Dynamic delisted detection: checking %d tickers via live verification (%d workers)...",
        len(tickers),
        max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check_live, t): t for t in tickers}
        for fut in as_completed(futures):
            try:
                ticker, status = fut.result(timeout=timeout_per_ticker)
                if status == "inactive":
                    inactive.add(ticker)
                elif status == "error":
                    rate_limited.add(ticker)
            except Exception:
                # Timeout / cancellation — assume still active (don't penalise)
                rate_limited.add(futures[fut])

    # Retry rate-limited tickers with smaller batch and delay
    if rate_limited:
        pipeline_logger.info(
            "Retrying %d rate-limited tickers sequentially...",
            len(rate_limited),
        )
        for ticker in sorted(rate_limited):
            time.sleep(0.5)  # Gentle rate limiting
            _, status = _check_live(ticker)
            if status == "inactive":
                inactive.add(ticker)
            elif status == "error":
                # Still erroring — assume active (safe default)
                pipeline_logger.debug("Ticker %s still rate-limited — assuming active", ticker)

    if inactive:
        pipeline_logger.info(
            "Delisted detection complete: %d/%d confirmed inactive",
            len(inactive),
            len(tickers),
        )
        examples = sorted(inactive)[:15]
        pipeline_logger.info("  Examples: %s%s", ", ".join(examples), "..." if len(inactive) > 15 else "")
    else:
        pipeline_logger.info("Delisted detection: 0/%d inactive — all tickers active", len(tickers))

    return inactive


def partition_tickers(tickers: list[str]) -> tuple[list[str], list[str]]:
    """Split tickers into active and delisted groups using live detection.

    Dynamically checks each ticker via yfinance fast_info to determine
    if it is still actively trading. No hardcoded lists or caching.

    :param tickers: Full ticker list from company_static
    :type tickers: list[str]
    :return: (active_tickers, delisted_tickers)
    :rtype: tuple[list[str], list[str]]
    """
    inactive = detect_inactive_tickers(tickers)
    active = [t for t in tickers if t not in inactive]
    delisted = [t for t in tickers if t in inactive]
    return active, delisted


def get_ticker_list(db_config: dict = None, **kwargs) -> list[str]:
    """Get a clean list of ticker symbols from company_static.

    Strips trailing whitespace per Spec §7.2 Issue 1 and applies
    Swiss ticker remapping (.S → .SW) for Yahoo Finance compatibility.

    :param db_config: PostgreSQL config dict
    :type db_config: dict or None
    :return: List of cleaned ticker symbols
    :rtype: list[str]

    Example::

        >>> tickers = get_ticker_list(conf['config']['Database']['Postgres'])
        >>> 'AAPL' in tickers
        True
    """
    df = load_companies(db_config, **kwargs)
    tickers = df["symbol"].tolist()
    pipeline_logger.info("Retrieved %d ticker symbols", len(tickers))
    return tickers


def prepare_ticker(raw_ticker: str, swiss_remap: bool = True) -> str:
    """Clean and prepare a single ticker for Yahoo Finance API calls.

    Handles:
      - Trailing whitespace stripping (Spec §7.2 Issue 1)
      - Swiss exchange remapping .S → .SW (Spec §7.2 Issue 3)

    :param raw_ticker: Raw ticker symbol from company_static
    :type raw_ticker: str
    :param swiss_remap: Whether to remap Swiss tickers
    :type swiss_remap: bool
    :return: Cleaned ticker string
    :rtype: str
    """
    ticker = raw_ticker.strip()
    if swiss_remap and ticker.endswith(".S"):
        ticker = ticker[:-2] + ".SW"
    # Yahoo Finance uses hyphen for share class (e.g. BRK-B not BRK.B)
    if ticker.endswith(".B"):
        ticker = ticker[:-2] + "-B"
    return ticker


def infer_currency(ticker: str, currency_map: dict = None) -> str:
    """Infer the local currency from the ticker exchange suffix.

    Solves Spec §7.2 Issue 2: company_static has no currency column.

    :param ticker: Cleaned ticker symbol
    :type ticker: str
    :param currency_map: Suffix-to-currency mapping from conf.yaml
    :type currency_map: dict or None
    :return: ISO 4217 currency code (e.g. USD, GBP, EUR)
    :rtype: str

    Example::

        >>> infer_currency('VOD.L', {'.L': 'GBP'})
        'GBP'
        >>> infer_currency('AAPL')
        'USD'
    """
    if currency_map is None:
        currency_map = {
            ".L": "GBP",
            ".PA": "EUR",
            ".AS": "EUR",
            ".DE": "EUR",
            ".MC": "EUR",
            ".MI": "EUR",
            ".TO": "CAD",
            ".SW": "CHF",
            ".S": "CHF",
        }
    for suffix, currency in currency_map.items():
        if ticker.endswith(suffix):
            return currency
    return "USD"
