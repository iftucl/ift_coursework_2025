"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Benchmark data retrieval and processing
Project : CW2 - Value-Sentiment Investment Strategy

Downloads benchmark price series from Yahoo Finance for performance
comparison.  Supports S&P 500 (primary) and MSCI World Value ETF
(secondary).

On-disk cache: the first successful Yahoo Finance fetch for a given
(ticker, start, end) is saved under ``output/benchmark_cache/`` as a
CSV. Subsequent runs read from the cache, so a temporary network
outage or Yahoo Finance throttling never blocks the back-test.

Ref: Part A §A7.3 — Benchmark Selection
"""

import logging
import os
import time
from typing import Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_BENCHMARK_CACHE_DIR = os.path.join('.cache', 'benchmarks')
_YAHOO_CHART_V8 = 'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


def _fetch_yahoo_chart_api(ticker: str, start_date: str, end_date: str) -> Optional[pd.Series]:
    """Fetch benchmark prices via Yahoo's public chart-v8 JSON API.

    Uses the ``requests`` library (not urllib / yfinance) because
    yfinance's download path has been unreliable (curl timeouts) in
    several environments and urllib's default TLS stack also stalls.
    The chart-v8 endpoint is the same one the Yahoo Finance website
    uses.

    :param ticker: Yahoo ticker (e.g. ``^GSPC``)
    :type ticker: str
    :param start_date: ISO start date
    :type start_date: str
    :param end_date: ISO end date (exclusive upper bound)
    :type end_date: str
    :returns: Series of adjusted close prices or None on failure
    :rtype: pd.Series or None
    """
    try:
        p1 = int(pd.Timestamp(start_date).timestamp())
        p2 = int(pd.Timestamp(end_date).timestamp())
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Invalid date range for %s: %s", ticker, exc)
        return None

    url = _YAHOO_CHART_V8.format(ticker=ticker)
    params = {
        'period1': p1,
        'period2': p2,
        'interval': '1d',
        'events': 'history',
    }
    try:
        resp = requests.get(
            url, params=params, headers={'User-Agent': _UA}, timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Yahoo chart API failed for %s: %s", ticker, exc)
        return None

    try:
        result = body['chart']['result'][0]
        timestamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        # Prefer adjclose if present
        adj = result.get('indicators', {}).get('adjclose', [{}])[0].get('adjclose')
        closes = adj if adj else quote['close']
        idx = pd.to_datetime(timestamps, unit='s').normalize()
        series = pd.Series(closes, index=idx, name=ticker).dropna()
        series.index.name = 'date'
        return series
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Yahoo chart API response malformed for %s: %s", ticker, exc)
        return None


class BenchmarkLoader:
    """Download and process benchmark return series.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, config: dict):
        self._config = config
        self._primary_ticker = config['benchmark']['primary']
        self._secondary_ticker = config['benchmark']['secondary']
        os.makedirs(_BENCHMARK_CACHE_DIR, exist_ok=True)

    def _cache_path(self, ticker: str, start_date: str, end_date: str) -> str:
        safe_ticker = ticker.replace('^', '').replace('.', '_').replace('/', '_')
        return os.path.join(
            _BENCHMARK_CACHE_DIR, f'{safe_ticker}_{start_date}_{end_date}.csv'
        )

    def _read_cache(self, path: str) -> Optional[pd.Series]:
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_csv(path, parse_dates=['date'], index_col='date')
            if len(df) == 0:
                return None
            prices = df.iloc[:, 0]
            prices.index.name = 'date'
            logger.info("Loaded %d benchmark prices from cache: %s", len(prices), path)
            return prices
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Benchmark cache read failed (%s) — refetching: %s", path, exc)
            return None

    def _write_cache(self, prices: pd.Series, path: str):
        try:
            df = prices.to_frame()
            df.index.name = 'date'
            df.to_csv(path)
            logger.info("Benchmark cached to %s (%d rows)", path, len(prices))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Benchmark cache write failed (%s): %s", path, exc)

    def load_benchmark_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        max_retries: int = 3,
    ) -> pd.Series:
        """Download adjusted close prices for a benchmark index.

        Reads from disk cache first, then falls back to Yahoo Finance
        with exponential-backoff retries. Writes successful fetches to
        the cache so later runs are instant and resilient to network
        hiccups.

        :param ticker: Yahoo Finance ticker (e.g. '^GSPC')
        :type ticker: str
        :param start_date: Start date (YYYY-MM-DD)
        :type start_date: str
        :param end_date: End date (YYYY-MM-DD)
        :type end_date: str
        :param max_retries: Yahoo Finance retry count
        :type max_retries: int
        :returns: Series of adjusted close prices indexed by date
        :rtype: pd.Series
        """
        cache = self._cache_path(ticker, start_date, end_date)
        cached = self._read_cache(cache)
        if cached is not None:
            return cached

        # Primary path — Yahoo chart-v8 JSON endpoint. We call this
        # before yfinance because yfinance's download() has been
        # intermittently timing out with curl errors in some Windows
        # environments, while the chart endpoint (which the Yahoo
        # Finance website itself uses) is reliable.
        prices = _fetch_yahoo_chart_api(ticker, start_date, end_date)
        if prices is not None and len(prices) > 0:
            logger.info("Loaded %d benchmark prices for %s via chart-v8 API", len(prices), ticker)
            self._write_cache(prices, cache)
            return prices

        # Fallback — yfinance.download with retries
        delay = 2.0
        data = pd.DataFrame()
        for attempt in range(1, max_retries + 1):
            logger.info(
                "yfinance fallback for %s (%s to %s), attempt %d/%d",
                ticker, start_date, end_date, attempt, max_retries,
            )
            try:
                data = yf.download(
                    ticker, start=start_date, end=end_date,
                    progress=False, auto_adjust=True, threads=False,
                )
                if not data.empty:
                    break
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("yfinance attempt %d failed: %s", attempt, exc)
            time.sleep(delay)
            delay *= 2

        if data.empty:
            logger.warning(
                "No benchmark data returned for %s — returning empty Series "
                "(pipeline will fall back to EW universe benchmark)", ticker,
            )
            return pd.Series(dtype=float)

        # Handle multi-level columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            prices = data['Close'].iloc[:, 0]
        else:
            prices = data['Close']

        prices.index = pd.to_datetime(prices.index)
        prices.index.name = 'date'
        prices.name = ticker
        logger.info("Loaded %d benchmark prices for %s", len(prices), ticker)
        self._write_cache(prices, cache)
        return prices

    def load_primary(self, start_date: str, end_date: str) -> pd.Series:
        """Load S&P 500 benchmark prices.

        :param start_date: Start date (YYYY-MM-DD)
        :type start_date: str
        :param end_date: End date (YYYY-MM-DD)
        :type end_date: str
        :returns: S&P 500 adjusted close prices
        :rtype: pd.Series
        """
        return self.load_benchmark_prices(self._primary_ticker, start_date, end_date)

    def load_secondary(self, start_date: str, end_date: str) -> pd.Series:
        """Load MSCI World Value ETF benchmark prices.

        :param start_date: Start date (YYYY-MM-DD)
        :type start_date: str
        :param end_date: End date (YYYY-MM-DD)
        :type end_date: str
        :returns: MSCI World Value ETF adjusted close prices
        :rtype: pd.Series
        """
        return self.load_benchmark_prices(self._secondary_ticker, start_date, end_date)

    def compute_benchmark_returns(self, prices: pd.Series) -> pd.Series:
        """Convert benchmark prices to daily simple returns.

        :param prices: Adjusted close price series
        :type prices: pd.Series
        :returns: Daily simple return series
        :rtype: pd.Series
        """
        returns = prices.pct_change().dropna()
        logger.info("Computed %d daily benchmark returns", len(returns))
        return returns

    def compute_equal_weight_universe_returns(
        self,
        prices_df: pd.DataFrame,
        universe_tickers: list,
    ) -> pd.Series:
        """Compute equal-weight returns across the full universe.

        Used as a third benchmark to isolate the value of stock
        selection vs holding the entire universe.

        :param prices_df: Full price matrix (dates × tickers)
        :type prices_df: pd.DataFrame
        :param universe_tickers: List of tickers in the universe
        :type universe_tickers: list
        :returns: Equal-weight daily returns series
        :rtype: pd.Series
        """
        available = [t for t in universe_tickers if t in prices_df.columns]
        subset = prices_df[available]
        daily_returns = subset.pct_change().dropna(how='all')

        # Equal-weight: average return across all available stocks each day
        ew_returns = daily_returns.mean(axis=1)
        ew_returns.name = 'EW_Universe'
        logger.info(
            "Computed equal-weight universe returns: %d days, %d avg stocks",
            len(ew_returns), int(daily_returns.notna().sum(axis=1).mean()),
        )
        return ew_returns
