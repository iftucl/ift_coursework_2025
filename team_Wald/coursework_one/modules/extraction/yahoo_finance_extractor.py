"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Yahoo Finance data extraction (financials, prices, ratios, news)
Project : CW1 - Value + News Sentiment Strategy

Extracts financial data for the 678-company investable universe using
the yfinance Python library.  Fetches:

  1. Daily price history (OHLCV) — 5-year lookback
  2. Company info with pre-computed ratios (P/E, P/B, EV/EBITDA, etc.)
  3. Quarterly financial statements (income, balance sheet, cash flow)
  4. Recent news headlines (supplementary to GDELT)

Smart design: retrieves ratios directly from ``yfinance.Ticker.info``
rather than recalculating from raw financials.  Raw financials are still
downloaded and stored in MinIO for full data lineage.

Handles:
  - Batch processing with configurable batch_size and delay
  - Retry with exponential backoff on transient failures
  - Graceful per-ticker error handling (one failure does not block others)
  - Rate limiting to avoid Yahoo Finance throttling (Spec §7.2 Issue 5)
"""

import random
import time

import pandas as pd
import yfinance as yf

from modules.utils.logger import pipeline_logger


def fetch_price_history(ticker: str, start_date: str, end_date: str, max_retries: int = 3) -> pd.DataFrame:
    """Fetch daily OHLCV price history for a single ticker.

    :param ticker: Yahoo Finance ticker symbol (e.g. 'AAPL', 'VOD.L')
    :type ticker: str
    :param start_date: Start date in YYYY-MM-DD format
    :type start_date: str
    :param end_date: End date in YYYY-MM-DD format
    :type end_date: str
    :param max_retries: Number of retry attempts on failure
    :type max_retries: int
    :return: DataFrame with OHLCV data indexed by date, or empty DataFrame
    :rtype: pd.DataFrame

    Example::

        >>> df = fetch_price_history('AAPL', '2020-01-01', '2025-01-01')
        >>> 'Close' in df.columns
        True
    """
    for attempt in range(max_retries):
        try:
            df = yf.download(
                ticker, start=start_date, end=end_date, progress=False, auto_adjust=False, multi_level_index=False
            )
            if df is not None and not df.empty:
                # Flatten MultiIndex columns if yfinance ignores multi_level_index=False
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                # Verify Close column has valid data (not all NaN from 401 errors)
                if "Close" in df.columns and df["Close"].notna().any():
                    return df
                pipeline_logger.warning("Price data for %s is all NaN (attempt %d) — retrying", ticker, attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep((2**attempt) * random.uniform(0.5, 1.5))
                continue
            else:
                pipeline_logger.warning("Empty price data for %s (attempt %d)", ticker, attempt + 1)
        except Exception as e:
            delay = (2**attempt) * random.uniform(0.5, 1.5)
            pipeline_logger.warning(
                "Price fetch error for %s (attempt %d): %s — retrying in %.1fs", ticker, attempt + 1, e, delay
            )
            if attempt < max_retries - 1:
                time.sleep(delay)
    pipeline_logger.error("Failed to fetch prices for %s after %d attempts", ticker, max_retries)
    return pd.DataFrame()


def fetch_company_info(ticker: str, max_retries: int = 3) -> dict:
    """Fetch company info including pre-computed financial ratios.

    Retrieves P/E, P/B, EV/EBITDA, dividend yield, debt-to-equity
    directly from Yahoo Finance's ``Ticker.info`` endpoint rather
    than recalculating — this is both faster and more reliable.

    :param ticker: Yahoo Finance ticker symbol
    :type ticker: str
    :param max_retries: Retry attempts
    :type max_retries: int
    :return: Dict with ratio fields, or empty dict on failure
    :rtype: dict

    Example::

        >>> info = fetch_company_info('AAPL')
        >>> 'trailingPE' in info
        True
    """
    best_result = None
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            if not info or not info.get("marketCap"):
                # Partial/empty response — likely rate-limited
                if attempt < max_retries - 1:
                    delay = (2 ** (attempt + 1)) * random.uniform(1.0, 2.0)
                    pipeline_logger.debug(
                        "Partial info for %s (attempt %d, no marketCap) — retrying in %.1fs",
                        ticker,
                        attempt + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
            result = {
                "symbol": ticker,
                # Pre-computed ratios
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "dividend_yield": info.get("dividendYield"),
                "debt_equity": info.get("debtToEquity"),
                # Market data
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "trailing_eps": info.get("trailingEps"),
                "book_value": info.get("bookValue"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "beta": info.get("beta"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                # Raw financial components for ratio fallback calculation
                "enterprise_value": info.get("enterpriseValue"),
                "ebitda_raw": info.get("ebitda"),
                "total_debt_raw": info.get("totalDebt"),
                "total_cash": info.get("totalCash"),
                "stockholders_equity": (
                    info.get("totalStockholderEquity")
                    or info.get("totalStockholdersEquity")
                    or info.get("stockholdersEquity")
                ),
                "operating_cashflow": info.get("operatingCashflow"),
                "free_cashflow": info.get("freeCashflow"),
                "total_revenue": info.get("totalRevenue"),
                "net_income_raw": info.get("netIncomeToCommon") or info.get("netIncome"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "total_assets": info.get("totalAssets"),
                "total_liabilities": info.get("totalLiabilities") or info.get("totalLiab"),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "operating_income": info.get("operatingIncome"),
            }
            # Keep the best result (most fields populated)
            if best_result is None:
                best_result = result
            else:
                # Merge: fill gaps in best_result from new result
                for k, v in result.items():
                    if best_result.get(k) is None and v is not None:
                        best_result[k] = v

            # Check if we got the critical ratio fields
            has_ev = result.get("ev_ebitda") is not None
            has_de = result.get("debt_equity") is not None
            if has_ev and has_de:
                return best_result  # Complete data — no need to retry

            # If missing critical fields, retry with backoff (rate limiting probable)
            if attempt < max_retries - 1:
                delay = (2 ** (attempt + 1)) * random.uniform(0.8, 1.5)
                time.sleep(delay)
        except Exception as e:
            delay = (2 ** (attempt + 1)) * random.uniform(1.0, 2.0)
            pipeline_logger.warning("Info fetch error for %s (attempt %d): %s", ticker, attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(delay)

    # Return best result we got (may have partial data)
    if best_result:
        return best_result
    pipeline_logger.error("Failed to fetch info for %s", ticker)
    return {}


def fetch_financial_data(ticker: str, max_retries: int = 3) -> dict:
    """Fetch quarterly financial statements for raw storage in MinIO.

    Downloads income statement, balance sheet, and cash flow data
    for the most recent quarters available.

    :param ticker: Yahoo Finance ticker symbol
    :type ticker: str
    :param max_retries: Retry attempts
    :type max_retries: int
    :return: Dict with keys 'income_statement', 'balance_sheet', 'cash_flow'
    :rtype: dict

    Example::

        >>> data = fetch_financial_data('AAPL')
        >>> 'income_statement' in data
        True
    """
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(ticker)
            result = {
                "income_statement": _df_to_serialisable(t.quarterly_financials),
                "balance_sheet": _df_to_serialisable(t.quarterly_balance_sheet),
                "cash_flow": _df_to_serialisable(t.quarterly_cashflow),
                # Annual data as fallback — more fields than quarterly
                "annual_income_statement": _df_to_serialisable(t.financials),
                "annual_balance_sheet": _df_to_serialisable(t.balance_sheet),
                "annual_cash_flow": _df_to_serialisable(t.cashflow),
            }
            has_data = any(v for v in result.values())
            if has_data:
                return result
        except Exception as e:
            delay = (2**attempt) * random.uniform(0.5, 1.5)
            pipeline_logger.warning("Financials error for %s (attempt %d): %s", ticker, attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(delay)
    pipeline_logger.error("Failed to fetch financials for %s", ticker)
    return {}


def fetch_news(ticker: str, max_retries: int = 3) -> list[dict]:
    """Fetch recent news articles from Yahoo Finance for a ticker.

    Used as supplementary source alongside GDELT.  Each article
    contains title, publisher, link, and publication timestamp.

    :param ticker: Yahoo Finance ticker symbol
    :type ticker: str
    :param max_retries: Retry attempts
    :type max_retries: int
    :return: List of article dicts with headline and metadata
    :rtype: list[dict]
    """
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(ticker)
            news = t.news or []
            articles = []
            for item in news:
                # yfinance >= 0.2.40 nests article data under "content"
                content = item.get("content", {}) if isinstance(item, dict) else {}
                provider = content.get("provider") or {}
                click_url = content.get("clickThroughUrl") or {}
                articles.append(
                    {
                        "headline": content.get("title", "") or item.get("title", ""),
                        "publisher": provider.get("displayName", "") if isinstance(provider, dict) else "",
                        "url": (click_url.get("url", "") if isinstance(click_url, dict) else item.get("link", "")),
                        "published_at": content.get("pubDate", "") or item.get("providerPublishTime", ""),
                        "source": "yahoo_finance",
                        "company_id": ticker,
                    }
                )
            return articles
        except Exception as e:
            delay = (2**attempt) * random.uniform(0.5, 1.5)
            pipeline_logger.warning("News fetch error for %s: %s", ticker, e)
            if attempt < max_retries - 1:
                time.sleep(delay)
    return []


def fetch_all_companies(
    tickers: list[str],
    start_date: str,
    end_date: str,
    batch_size: int = 50,
    delay: float = 2.0,
    max_retries: int = 3,
    sources: list[str] = None,
) -> dict:
    """Fetch data for all companies in batches with rate limiting.

    Processes tickers in configurable batches with delays between
    batches to avoid Yahoo Finance throttling.

    :param tickers: List of ticker symbols
    :type tickers: list[str]
    :param start_date: Price history start date
    :type start_date: str
    :param end_date: Price history end date
    :type end_date: str
    :param batch_size: Tickers per batch
    :type batch_size: int
    :param delay: Seconds between batches
    :type delay: float
    :param max_retries: Retry attempts per ticker
    :type max_retries: int
    :param sources: Which data types to fetch
    :type sources: list[str] or None
    :return: Nested dict: {ticker: {prices, info, financials, news}}
    :rtype: dict
    """
    if sources is None:
        sources = ["prices", "financials", "news"]
    results = {}
    total = len(tickers)
    for batch_start in range(0, total, batch_size):
        batch = tickers[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        pipeline_logger.info(
            "Processing batch %d (%d-%d of %d)",
            batch_num,
            batch_start + 1,
            min(batch_start + batch_size, total),
            total,
        )
        for ticker in batch:
            ticker_data = {}
            try:
                if "prices" in sources:
                    ticker_data["prices"] = fetch_price_history(ticker, start_date, end_date, max_retries)
                if "financials" in sources:
                    ticker_data["info"] = fetch_company_info(ticker, max_retries)
                    ticker_data["financials"] = fetch_financial_data(ticker, max_retries)
                if "news" in sources:
                    ticker_data["news"] = fetch_news(ticker)
                results[ticker] = ticker_data
            except Exception as e:
                pipeline_logger.error("Unhandled error for %s: %s — skipping", ticker, e)
                results[ticker] = {"error": str(e)}
            time.sleep(0.3)
        if batch_start + batch_size < total:
            pipeline_logger.info("Batch %d complete — waiting %.1fs", batch_num, delay)
            time.sleep(delay)
    pipeline_logger.info("Extraction complete: %d/%d tickers processed", len(results), total)
    return results


def _df_to_serialisable(df) -> dict:
    """Convert a yfinance financial statement DataFrame to a JSON-serialisable dict.

    yfinance financial DataFrames have field names as rows (index) and dates
    as columns.  We need the output format::

        { "Field Name": { "2024-09-30": 12345, ... }, ... }

    so that ``_extract_field()`` in value_calculator.py can look up fields by
    name and iterate dates to find the most recent non-null value.

    Uses ``orient='index'`` which maps each row label (field name) to a dict
    of {column_label (date): value}.  All keys are stringified for MongoDB
    compatibility.

    :param df: DataFrame from yfinance (may be None)
    :return: Dict with field names as outer keys, dates as inner keys
    :rtype: dict
    """
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return {}
    try:
        # orient='index' gives {row_label: {col_label: value}}
        # For financial statements: {field_name: {date: value}} — correct format
        raw = df.to_dict(orient="index")
        return {
            str(k): {str(kk): vv for kk, vv in v.items()} if isinstance(v, dict) else v
            for k, v in raw.items()
        }
    except Exception:
        return {}
