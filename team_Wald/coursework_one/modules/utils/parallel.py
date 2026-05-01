"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Parallel extraction engine for the pipeline
Project : CW1 - Value + News Sentiment Strategy

Wraps the extraction modules in ThreadPoolExecutor-based concurrency to
achieve ~4-5x speedup.  Each function replaces a sequential loop in
Main.py with thread-pool parallelism.  Rate limiting uses per-worker
sleeps and inter-batch delays to avoid Yahoo Finance throttling.

Parallelisation layers
----------------------
1. **Intra-stage** — each extraction function runs its items in a thread
   pool (e.g. 6 workers fetching tickers concurrently).
2. **Inter-stage** — FX runs concurrently with the news cascade.
3. **News cascade** — three-tier gap-fill pattern (like reference project):
     Tier 1: YF News (primary) for all tickers in parallel
     Tier 2: GDELT (gap-fill) only for tickers with 0 articles
     Tier 3: NewsAPI (gap-fill) only for tickers still with 0 articles
   Each tier has its own circuit breaker + rate limiter.
4. **Post-batch uploads** — MinIO / MongoDB / PostgreSQL writes after
   each price batch are parallelised across tickers.
5. **Sentiment scoring** — each company scored in its own thread.

Thread safety notes
-------------------
- ``yfinance.download`` and ``yfinance.Ticker`` create per-call HTTP
  sessions — safe to use from multiple threads.
- PostgreSQL ``scoped_session`` is thread-local; however, DB writes are
  serialised after each batch (not inside workers).
- PyMongo ``MongoClient`` is thread-safe by design.
- MinIO client methods are stateless HTTP calls — safe.
- VADER ``SentimentIntensityAnalyzer`` is stateless (read-only lexicon).
"""

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from modules.extraction.company_loader import infer_currency, prepare_ticker
from modules.extraction.fx_extractor import FX_PAIRS, fetch_fx_rates
from modules.extraction.gdelt_extractor import fetch_news_gdelt
from modules.extraction.newsapi_extractor import fetch_news_newsapi
from modules.extraction.yahoo_finance_extractor import (
    fetch_company_info,
    fetch_financial_data,
    fetch_news,
    fetch_price_history,
)
from modules.processing.data_cleaner import clean_price_dataframe, validate_company_info
from modules.processing.sentiment_scorer import aggregate_sentiment, deduplicate_articles, get_analyser, score_articles
from modules.processing.value_calculator import calculate_ratios_from_financials, enhance_company_info
from modules.utils.circuit_breaker import CircuitBreaker
from modules.utils.logger import pipeline_logger
from modules.utils.rate_limiter import TokenBucketRateLimiter

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TickerResult:
    """Result of extracting data for a single ticker."""

    ticker: str
    yf_ticker: str
    currency: str
    price_records: list = field(default_factory=list)
    company_info: dict = field(default_factory=dict)
    financials: dict = field(default_factory=dict)
    price_df: pd.DataFrame | None = None
    status: str = "success"  # success | empty | error
    error: str = ""


@dataclass
class BatchResult:
    """Aggregated result of a parallel batch extraction."""

    price_records: list = field(default_factory=list)
    company_infos: list = field(default_factory=list)
    ticker_results: list = field(default_factory=list)
    price_success: int = 0
    price_empty: int = 0
    price_fail: int = 0
    info_success: int = 0
    info_fail: int = 0


# ---------------------------------------------------------------------------
# Yahoo Finance: parallel price / financial extraction
# ---------------------------------------------------------------------------


def _extract_single_ticker(
    raw_ticker: str,
    sources: list[str],
    start_date: str,
    end_date: str,
    currency_map: dict,
    max_retries: int,
    rate_limiter,
    delay: float = 0.3,
    circuit_breaker: CircuitBreaker | None = None,
) -> TickerResult:
    """Extract all requested data for one ticker (runs inside a thread).

    Integrates token bucket rate limiting and circuit breaker protection.
    If the circuit is OPEN, skips API calls entirely to prevent cascading
    failures from Yahoo Finance throttling.
    """
    # Rate limiting — acquire token before making any API calls
    if isinstance(rate_limiter, TokenBucketRateLimiter):
        rate_limiter.acquire()
    elif isinstance(rate_limiter, threading.Semaphore):
        with rate_limiter:
            time.sleep(delay)
    else:
        time.sleep(delay)

    yf_ticker = prepare_ticker(raw_ticker)
    currency = infer_currency(yf_ticker, currency_map)
    result = TickerResult(ticker=raw_ticker, yf_ticker=yf_ticker, currency=currency)

    # Circuit breaker check — if OPEN, skip this ticker entirely
    if circuit_breaker and not circuit_breaker.allow_request():
        result.status = "error"
        result.error = "circuit_breaker_open"
        return result

    try:
        # Prices
        if "prices" in sources:
            price_df = fetch_price_history(yf_ticker, start_date, end_date, max_retries)
            if not price_df.empty:
                records = clean_price_dataframe(price_df, raw_ticker, currency)
                result.price_records = records
                result.price_df = price_df
                result.status = "success" if records else "empty"
                if circuit_breaker:
                    circuit_breaker.record_success()
            else:
                result.status = "empty"
                if circuit_breaker:
                    circuit_breaker.record_failure()

        # Company info / ratios — inter-request delay to reduce 401 errors
        if "financials" in sources:
            time.sleep(random.uniform(0.3, 0.8))

            # Re-check circuit breaker before info fetch
            if circuit_breaker and not circuit_breaker.allow_request():
                pipeline_logger.debug("Circuit open — skipping info fetch for %s", raw_ticker)
            else:
                info = fetch_company_info(yf_ticker, max_retries)
                if info:
                    # Accept even partial info (don't gate on validate_company_info
                    # here — the enhance step will fill gaps from statements)
                    info["symbol"] = raw_ticker
                    result.company_info = info
                    if circuit_breaker:
                        circuit_breaker.record_success()
                elif circuit_breaker:
                    circuit_breaker.record_failure()

            # Raw financial statements
            time.sleep(random.uniform(0.3, 0.8))
            if circuit_breaker and not circuit_breaker.allow_request():
                pipeline_logger.debug("Circuit open — skipping financials for %s", raw_ticker)
            else:
                result.financials = fetch_financial_data(yf_ticker, max_retries)
                if result.financials and circuit_breaker:
                    circuit_breaker.record_success()

            # --- Ratio calculator fallback (Task 5.1) ---
            if result.financials:
                if result.company_info:
                    result.company_info = enhance_company_info(result.company_info, result.financials)
                else:
                    market_cap = None
                    try:
                        import yfinance as yf_lib

                        fi = yf_lib.Ticker(yf_ticker).fast_info
                        market_cap = getattr(fi, "market_cap", None)
                    except Exception:
                        pass
                    calculated = calculate_ratios_from_financials(raw_ticker, result.financials, market_cap)
                    if calculated:
                        result.company_info = calculated

    except Exception as e:
        result.status = "error"
        result.error = str(e)
        if circuit_breaker:
            circuit_breaker.record_failure()
        pipeline_logger.error("Parallel extract error for %s: %s", raw_ticker, e)

    return result


def parallel_extract_prices(
    batch: list[str],
    sources: list[str],
    start_date: str,
    end_date: str,
    currency_map: dict,
    max_retries: int = 3,
    max_workers: int = 6,
    delay_per_ticker: float = 0.3,
    progress_callback=None,
) -> BatchResult:
    """Extract Yahoo Finance data for a batch of tickers in parallel.

    :param batch: List of raw ticker symbols to process
    :param sources: Data sources to fetch ('prices', 'financials')
    :param start_date: Start date YYYY-MM-DD
    :param end_date: End date YYYY-MM-DD
    :param currency_map: Ticker-to-currency mapping dict
    :param max_retries: Retries per ticker per data type
    :param max_workers: Thread pool size
    :param delay_per_ticker: Rate-limiting delay between requests
    :param progress_callback: Optional callable(ticker, status, description) called per ticker
    :return: Aggregated BatchResult with all records and counters
    """
    result = BatchResult()
    rate_limiter = TokenBucketRateLimiter(
        rate=1.0 / max(delay_per_ticker, 0.1),
        capacity=max_workers,
        name="yf_prices",
    )
    # Circuit breaker: trips after 15 consecutive failures, recovers after 60s
    yf_circuit = CircuitBreaker(
        name="yf_extraction",
        failure_threshold=15,
        recovery_timeout=60.0,
        success_threshold=2,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _extract_single_ticker,
                raw_ticker,
                sources,
                start_date,
                end_date,
                currency_map,
                max_retries,
                rate_limiter,
                delay_per_ticker,
                yf_circuit,
            ): raw_ticker
            for raw_ticker in batch
        }

        for future in as_completed(futures):
            raw_ticker = futures[future]
            try:
                tr = future.result()
                result.ticker_results.append(tr)

                # Aggregate price records
                if tr.price_records:
                    result.price_records.extend(tr.price_records)
                    result.price_success += 1
                elif tr.status == "empty":
                    result.price_empty += 1
                elif tr.status == "error":
                    result.price_fail += 1

                # Aggregate company infos
                if tr.company_info:
                    result.company_infos.append(tr.company_info)
                    result.info_success += 1
                elif "financials" in sources and not tr.company_info:
                    result.info_fail += 1

                # Progress callback
                if progress_callback:
                    desc = f"{raw_ticker}: {len(tr.price_records)} rows" if tr.price_records else raw_ticker
                    progress_callback(raw_ticker, tr.status, desc)

            except Exception as e:
                pipeline_logger.error("Future error for %s: %s", raw_ticker, e)
                result.price_fail += 1
                if progress_callback:
                    progress_callback(raw_ticker, "error", f"{raw_ticker}: {e}")

    return result


def refetch_missing_ratios(
    company_infos: list[dict],
    all_financials: dict | None = None,
    max_retries: int = 3,
    delay: float = 1.0,
) -> list[dict]:
    """Re-fetch company info for tickers missing any financial ratio.

    Two-pass strategy:
      1. **Statement recalculation** — for tickers that already have financial
         statement data (from the initial extraction), re-run the ratio
         calculators.  This is fast (no API calls) and now works correctly
         after the ``_df_to_serialisable()`` fix.
      2. **API re-fetch** — for tickers still missing ratios after
         recalculation, sequentially re-fetch ``company_info`` and
         ``financial_data`` from Yahoo Finance with proper delays.

    :param company_infos: List of company info dicts (mutated in place)
    :param all_financials: Optional dict mapping ticker → financial statements
    :param max_retries: Per-ticker retry count
    :param delay: Seconds between requests
    :return: Same list with missing fields filled in
    """
    from modules.extraction.yahoo_finance_extractor import fetch_financial_data

    ratio_keys = ("pe_ratio", "pb_ratio", "ev_ebitda", "dividend_yield", "debt_equity")
    missing_tickers = []
    info_by_ticker = {}
    for info in company_infos:
        ticker = info.get("symbol") or info.get("company_id", "")
        info_by_ticker[ticker] = info
        if any(info.get(k) is None for k in ratio_keys):
            missing_tickers.append(ticker)

    if not missing_tickers:
        return company_infos

    pipeline_logger.info(
        "Refetch pass: %d tickers missing one or more ratios",
        len(missing_tickers),
    )

    # --- Pass 1: Recalculate from existing financial statements ---
    # This is free (no API calls) and leverages the _df_to_serialisable fix
    if all_financials:
        recalc_counts = {k: 0 for k in ratio_keys}
        for ticker in list(missing_tickers):
            fins = all_financials.get(ticker, {})
            if not fins:
                continue
            existing = info_by_ticker.get(ticker, {})
            enhanced = enhance_company_info(existing, fins)
            for k in ratio_keys:
                if existing.get(k) is None and enhanced.get(k) is not None:
                    existing[k] = enhanced[k]
                    recalc_counts[k] += 1

        pipeline_logger.info(
            "Pass 1 (statement recalculation): filled %s",
            ", ".join(f"{v} {k}" for k, v in recalc_counts.items() if v > 0) or "0 ratios",
        )

    # Recompute missing list after pass 1
    still_missing = []
    for ticker in missing_tickers:
        existing = info_by_ticker.get(ticker, {})
        if any(existing.get(k) is None for k in ratio_keys):
            still_missing.append(ticker)

    if not still_missing:
        pipeline_logger.info("All gaps filled by statement recalculation — no API re-fetch needed")
        return company_infos

    pipeline_logger.info(
        "Pass 2 (API re-fetch): %d tickers still missing ratios",
        len(still_missing),
    )

    # --- Pass 2: Sequential API re-fetch with delays ---
    filled_counts = {k: 0 for k in ratio_keys}
    for ticker in still_missing:
        yf_ticker = prepare_ticker(ticker)
        time.sleep(delay)
        try:
            # Re-fetch company info
            new_info = fetch_company_info(yf_ticker, max_retries)
            existing = info_by_ticker.get(ticker, {})

            if new_info:
                # Fill any missing ratios from refreshed info
                for k in ratio_keys:
                    if existing.get(k) is None and new_info.get(k) is not None:
                        existing[k] = new_info[k]
                        filled_counts[k] += 1

                # Fill raw component fields for calculator fallback
                for key in (
                    "enterprise_value",
                    "ebitda_raw",
                    "total_debt_raw",
                    "total_cash",
                    "stockholders_equity",
                    "total_assets",
                    "total_liabilities",
                    "operating_income",
                    "net_income_raw",
                    "market_cap",
                ):
                    if existing.get(key) is None and new_info.get(key) is not None:
                        existing[key] = new_info[key]

            # If still missing any ratio, try financial statements and computing
            if any(existing.get(k) is None for k in ratio_keys):
                time.sleep(delay * 0.5)
                fins = fetch_financial_data(yf_ticker, max_retries)
                if fins:
                    enhanced = enhance_company_info(existing, fins)
                    for k in ratio_keys:
                        if existing.get(k) is None and enhanced.get(k) is not None:
                            existing[k] = enhanced[k]
                            filled_counts[k] += 1

        except Exception as e:
            pipeline_logger.debug("Re-fetch failed for %s: %s", ticker, e)

    pipeline_logger.info(
        "Pass 2 (API re-fetch): filled %s",
        ", ".join(f"{v} {k}" for k, v in filled_counts.items() if v > 0) or "0 ratios",
    )
    return company_infos


# ---------------------------------------------------------------------------
# FX: parallel pair extraction
# ---------------------------------------------------------------------------


def parallel_extract_fx(
    start_date: str,
    end_date: str,
    pairs: list[str] | None = None,
    max_workers: int = 4,
    progress_callback=None,
) -> dict[str, pd.DataFrame]:
    """Fetch FX rates for all currency pairs in parallel.

    :param start_date: Start date YYYY-MM-DD
    :param end_date: End date YYYY-MM-DD
    :param pairs: Override default FX pairs
    :param max_workers: Thread pool size (one per pair)
    :param progress_callback: Optional callable(pair, status, description)
    :return: Dict mapping pair identifier to OHLC DataFrame
    """
    if pairs is None:
        pairs = list(FX_PAIRS)

    results = {}

    def _fetch_single_pair(pair: str) -> tuple[str, pd.DataFrame]:
        fx_data = fetch_fx_rates(start_date, end_date, pairs=[pair])
        return pair, fx_data.get(pair, pd.DataFrame())

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_single_pair, pair): pair for pair in pairs}

        for future in as_completed(futures):
            pair = futures[future]
            try:
                _, df = future.result()
                results[pair] = df
                status = "success" if not df.empty else "empty"
                if progress_callback:
                    rows = len(df) if not df.empty else 0
                    progress_callback(pair, status, f"{pair}: {rows} rates")
            except Exception as e:
                pipeline_logger.error("FX parallel error for %s: %s", pair, e)
                results[pair] = pd.DataFrame()
                if progress_callback:
                    progress_callback(pair, "error", f"{pair}: {e}")

    return results


# ---------------------------------------------------------------------------
# Yahoo Finance news: parallel extraction
# ---------------------------------------------------------------------------


def parallel_extract_news(
    tickers: list[str],
    max_workers: int = 4,
    delay_per_ticker: float = 0.3,
    circuit_breaker: CircuitBreaker = None,
    progress_callback=None,
) -> dict[str, list[dict]]:
    """Fetch Yahoo Finance news for all tickers in parallel.

    Uses batched concurrency to stay under Yahoo Finance rate limits.
    Processes tickers in mini-batches of ``max_workers`` with a delay
    between each batch, giving ~10 req/s sustained throughput.

    Includes circuit breaker protection and 2 retry passes for empty
    results with increasing cooldown (5s, 10s).

    :param tickers: List of raw ticker symbols
    :param max_workers: Thread pool size
    :param delay_per_ticker: Per-worker delay before each request
    :param circuit_breaker: Optional CircuitBreaker for YF News API
    :param progress_callback: Optional callable(ticker, status, description)
    :return: Dict mapping ticker to list of article dicts
    """
    results = {}
    empty_tickers = []

    def _fetch_single_news(raw_ticker: str) -> tuple[str, list[dict]]:
        # Jitter on per-ticker delay to decorrelate concurrent workers
        time.sleep(delay_per_ticker * random.uniform(0.5, 1.5))
        if circuit_breaker and not circuit_breaker.allow_request():
            return raw_ticker, []
        yf_ticker = prepare_ticker(raw_ticker)
        try:
            articles = fetch_news(yf_ticker)
            for article in articles:
                article["company_id"] = raw_ticker
            if circuit_breaker:
                if articles:
                    circuit_breaker.record_success()
                else:
                    circuit_breaker.record_failure()
            return raw_ticker, articles
        except Exception as e:
            if circuit_breaker:
                circuit_breaker.record_failure()
            raise e

    # Process in mini-batches to control request rate
    batch_sz = max_workers * 3
    for i in range(0, len(tickers), batch_sz):
        mini_batch = tickers[i : i + batch_sz]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_single_news, t): t for t in mini_batch}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    _, articles = future.result()
                    results[ticker] = articles
                    if articles:
                        if progress_callback:
                            progress_callback(ticker, "success", f"{ticker}: {len(articles)} articles")
                    else:
                        empty_tickers.append(ticker)
                        if progress_callback:
                            progress_callback(ticker, "empty", f"{ticker}: 0 articles")
                except Exception as e:
                    pipeline_logger.error("News parallel error for %s: %s", ticker, e)
                    results[ticker] = []
                    if progress_callback:
                        progress_callback(ticker, "error", f"{ticker}: {e}")
        # Brief pause between mini-batches to avoid rate limiting
        time.sleep(1.0)

    # 2 retry passes for empty tickers with increasing cooldown
    retry_cooldowns = [5, 10]
    for pass_num, cooldown in enumerate(retry_cooldowns, 1):
        if not empty_tickers:
            break
        pipeline_logger.info(
            "YF News retry pass %d: %d empty tickers, cooldown %ds",
            pass_num,
            len(empty_tickers),
            cooldown,
        )
        time.sleep(cooldown)
        still_empty = []
        for i in range(0, len(empty_tickers), batch_sz):
            mini_batch = empty_tickers[i : i + batch_sz]
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_fetch_single_news, t): t for t in mini_batch}
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        _, articles = future.result()
                        if articles:
                            results[ticker] = articles
                            pipeline_logger.info(
                                "YF News retry pass %d: %s got %d articles", pass_num, ticker, len(articles)
                            )
                        else:
                            still_empty.append(ticker)
                    except Exception:
                        still_empty.append(ticker)
            time.sleep(1.0)
        empty_tickers = still_empty

    return results


# ---------------------------------------------------------------------------
# GDELT news: parallel extraction (replaces sequential fetch_all_companies_news)
# ---------------------------------------------------------------------------


def parallel_extract_gdelt(
    companies: list[dict],
    timespan: str = "3months",
    max_records: int = 15,
    max_retries: int = 3,
    max_workers: int = 12,
    delay_per_company: float = 0.0,
    circuit_breaker: CircuitBreaker = None,
    rate_limiter: TokenBucketRateLimiter = None,
    progress_callback=None,
) -> dict[str, list[dict]]:
    """Fetch GDELT news for all companies in parallel.

    Uses 12 workers (reduced from 24 to avoid connection flooding),
    circuit breaker protection, and token bucket rate limiting.
    Includes 2 retry passes for companies that returned 0 articles.

    :param companies: List of dicts with 'symbol' and 'security' keys
    :param timespan: GDELT timespan parameter
    :param max_records: Max articles per company
    :param max_retries: Retry attempts per company
    :param max_workers: Thread pool size
    :param delay_per_company: Small delay to avoid connection flooding
    :param circuit_breaker: Optional CircuitBreaker for GDELT API
    :param rate_limiter: Optional TokenBucketRateLimiter for GDELT API
    :param progress_callback: Optional callable(ticker, status, description)
    :return: Dict mapping ticker to list of article dicts
    """
    results = {}
    empty_companies = []

    def _fetch_single_gdelt(company: dict) -> tuple[str, list[dict]]:
        ticker = company.get("symbol", "").strip()
        name = company.get("security", ticker)
        if not ticker:
            return "", []
        # Circuit breaker check
        if circuit_breaker and not circuit_breaker.allow_request():
            return ticker, []
        # Rate limiter
        if rate_limiter:
            rate_limiter.acquire()
        elif delay_per_company > 0:
            time.sleep(delay_per_company)
        try:
            articles = fetch_news_gdelt(
                company_name=name,
                company_id=ticker,
                timespan=timespan,
                max_records=max_records,
                max_retries=max_retries,
            )
            if circuit_breaker:
                if articles:
                    circuit_breaker.record_success()
                else:
                    circuit_breaker.record_failure()
            return ticker, articles
        except Exception as e:
            if circuit_breaker:
                circuit_breaker.record_failure()
            raise e

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_single_gdelt, c): c for c in companies}

        for future in as_completed(futures):
            company = futures[future]
            ticker = company.get("symbol", "")
            try:
                t, articles = future.result()
                if t:
                    results[t] = articles
                    if articles:
                        if progress_callback:
                            progress_callback(t, "success", f"{t}: {len(articles)} articles")
                    else:
                        empty_companies.append(company)
                        if progress_callback:
                            progress_callback(t, "empty", f"{t}: 0 articles")
            except Exception as e:
                pipeline_logger.error("GDELT parallel error for %s: %s", ticker, e)
                if ticker:
                    results[ticker] = []
                    empty_companies.append(company)
                if progress_callback:
                    progress_callback(ticker, "error", f"{ticker}: {e}")

    # 2 retry passes for empty results with cooldown and fewer workers
    retry_cooldowns = [3, 6]
    for pass_num, cooldown in enumerate(retry_cooldowns, 1):
        if not empty_companies:
            break
        pipeline_logger.info(
            "GDELT retry pass %d: %d empty companies, cooldown %ds",
            pass_num,
            len(empty_companies),
            cooldown,
        )
        time.sleep(cooldown)
        retry_workers = max(max_workers // 2, 4)
        still_empty = []
        with ThreadPoolExecutor(max_workers=retry_workers) as executor:
            futures = {executor.submit(_fetch_single_gdelt, c): c for c in empty_companies}
            for future in as_completed(futures):
                company = futures[future]
                ticker = company.get("symbol", "")
                try:
                    t, articles = future.result()
                    if t and articles:
                        results[t] = articles
                        pipeline_logger.info("GDELT retry pass %d: %s got %d articles", pass_num, t, len(articles))
                        if progress_callback:
                            progress_callback(t, "success", f"{t}: {len(articles)} articles")
                    elif t:
                        still_empty.append(company)
                except Exception:
                    still_empty.append(company)
        empty_companies = still_empty

    return results


# ---------------------------------------------------------------------------
# NewsAPI: parallel extraction (supplementary news source)
# ---------------------------------------------------------------------------


def parallel_extract_newsapi(
    companies: list[dict],
    api_key: str = None,
    page_size: int = 10,
    max_workers: int = 4,
    max_retries: int = 3,
    circuit_breaker: CircuitBreaker = None,
    rate_limiter: TokenBucketRateLimiter = None,
    progress_callback=None,
) -> dict[str, list[dict]]:
    """Fetch NewsAPI articles for a list of companies in parallel.

    NewsAPI free tier allows only 100 requests/day, so this function
    uses aggressive rate limiting (0.5 req/s, burst 2) and a circuit
    breaker to avoid burning the daily quota on transient errors.

    Per task instructions, NewsAPI is supplementary and should be used
    for the top 50-100 companies after initial screening.

    :param companies: List of dicts with 'symbol' and 'security' keys
    :param api_key: NewsAPI API key (falls back to NEWSAPI_KEY env var)
    :param page_size: Max articles per company request
    :param max_workers: Thread pool size (kept low for rate limits)
    :param max_retries: Retry attempts per company
    :param circuit_breaker: Optional CircuitBreaker for NewsAPI
    :param rate_limiter: Optional TokenBucketRateLimiter for NewsAPI
    :param progress_callback: Optional callable(ticker, status, description)
    :return: Dict mapping ticker to list of article dicts
    """
    results = {}
    empty_companies = []

    def _fetch_single_newsapi(company: dict) -> tuple[str, list[dict]]:
        ticker = company.get("symbol", "").strip()
        name = company.get("security", ticker)
        if not ticker:
            return "", []
        # Circuit breaker check
        if circuit_breaker and not circuit_breaker.allow_request():
            return ticker, []
        # Rate limiter — critical for 100 req/day budget
        if rate_limiter:
            rate_limiter.acquire()
        try:
            articles = fetch_news_newsapi(
                company_name=name,
                company_id=ticker,
                api_key=api_key,
                page_size=page_size,
                max_retries=max_retries,
            )
            if circuit_breaker:
                if articles:
                    circuit_breaker.record_success()
                else:
                    circuit_breaker.record_failure()
            return ticker, articles
        except Exception as e:
            if circuit_breaker:
                circuit_breaker.record_failure()
            raise e

    # Process in mini-batches to control request rate
    batch_sz = max_workers * 2
    for i in range(0, len(companies), batch_sz):
        mini_batch = companies[i : i + batch_sz]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_single_newsapi, c): c for c in mini_batch}
            for future in as_completed(futures):
                company = futures[future]
                ticker = company.get("symbol", "")
                try:
                    t, articles = future.result()
                    if t:
                        results[t] = articles
                        if articles:
                            if progress_callback:
                                progress_callback(t, "success", f"{t}: {len(articles)} articles")
                        else:
                            empty_companies.append(company)
                            if progress_callback:
                                progress_callback(t, "empty", f"{t}: 0 articles")
                except Exception as e:
                    pipeline_logger.error("NewsAPI parallel error for %s: %s", ticker, e)
                    if ticker:
                        results[ticker] = []
                        empty_companies.append(company)
                    if progress_callback:
                        progress_callback(ticker, "error", f"{ticker}: {e}")
        # Pause between mini-batches to stay within rate limits
        time.sleep(2.0)

    # Single retry pass for empty results (conservative — preserve daily quota)
    if empty_companies:
        pipeline_logger.info(
            "NewsAPI retry pass: %d empty companies, cooldown 5s",
            len(empty_companies),
        )
        time.sleep(5)
        retry_workers = max(max_workers // 2, 2)
        with ThreadPoolExecutor(max_workers=retry_workers) as executor:
            futures = {executor.submit(_fetch_single_newsapi, c): c for c in empty_companies}
            for future in as_completed(futures):
                company = futures[future]
                ticker = company.get("symbol", "")
                try:
                    t, articles = future.result()
                    if t and articles:
                        results[t] = articles
                        pipeline_logger.info("NewsAPI retry: %s got %d articles", t, len(articles))
                        if progress_callback:
                            progress_callback(t, "success", f"{t}: {len(articles)} articles")
                except Exception:
                    pass

    return results


# ---------------------------------------------------------------------------
# Post-batch uploads: parallel MinIO / MongoDB / PostgreSQL writes
# ---------------------------------------------------------------------------


def parallel_upload_batch_results(
    ticker_results: list,
    minio,
    mongo,
    db,
    run_id: str,
    end_date: str,
    frequency: str,
    start_date: str,
    max_workers: int = 6,
) -> None:
    """Upload extraction results to MinIO/MongoDB and write ingestion logs in parallel.

    Each ticker's uploads (CSV, JSON, ingestion log) run in their own thread.
    All three storage backends (MinIO, MongoDB, PostgreSQL) are thread-safe.

    :param ticker_results: List of TickerResult objects from a batch
    :param minio: MinIO client
    :param mongo: MongoDB client
    :param db: PostgreSQL DatabaseClient
    :param run_id: Pipeline run ID for ingestion log
    :param end_date: End date string for file naming
    :param frequency: Pipeline frequency for ingestion log
    :param start_date: Start date string for ingestion log
    :param max_workers: Thread pool size
    """
    from modules.loading.postgres_loader import insert_ingestion_log

    def _upload_single_ticker(tr):
        try:
            if tr.price_df is not None and not tr.price_df.empty:
                minio.upload_csv(tr.price_df, "prices", tr.ticker, f"{end_date}.csv")
                insert_ingestion_log(
                    db,
                    run_id,
                    "yfinance_prices",
                    tr.ticker,
                    "SUCCESS",
                    len(tr.price_records),
                    run_frequency=frequency,
                    date_range_start=start_date,
                    date_range_end=end_date,
                )
            elif tr.status == "empty":
                insert_ingestion_log(db, run_id, "yfinance_prices", tr.ticker, "EMPTY", 0, run_frequency=frequency)
            elif tr.status == "error":
                insert_ingestion_log(db, run_id, "yfinance", tr.ticker, "FAILED", 0, tr.error, frequency)

            if tr.company_info:
                minio.upload_json(tr.company_info, "company_info", tr.ticker, "info.json")
                mongo.insert_one("raw_financial_data", {"company_id": tr.ticker, "data": tr.company_info})
                insert_ingestion_log(db, run_id, "yfinance_info", tr.ticker, "SUCCESS", 1, run_frequency=frequency)

            if tr.financials:
                minio.upload_json(tr.financials, f"financial/{end_date[:4]}", tr.ticker, "statements.json")
                mongo.insert_one(
                    "raw_financial_data",
                    {"company_id": tr.ticker, "type": "statements", "data": tr.financials},
                )
        except Exception as e:
            pipeline_logger.error("Parallel upload error for %s: %s", tr.ticker, e)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_upload_single_ticker, tr) for tr in ticker_results]
        for future in as_completed(futures):
            future.result()  # Propagate any unhandled exceptions


# ---------------------------------------------------------------------------
# Sentiment scoring: parallel per-company VADER analysis
# ---------------------------------------------------------------------------


def parallel_compute_sentiment(
    all_articles: dict,
    score_date: date = None,
    max_workers: int = 8,
    progress_callback=None,
) -> list[dict]:
    """Compute VADER sentiment scores for all companies in parallel.

    Each company's articles are independently deduplicated, scored, and
    aggregated in its own thread.  VADER's ``SentimentIntensityAnalyzer``
    is stateless (read-only lexicon lookup), so thread-safe.

    :param all_articles: Dict mapping ticker to list of article dicts
    :param score_date: Date for all scores
    :param max_workers: Thread pool size
    :param progress_callback: Optional callable(ticker, status, description)
    :return: List of aggregated sentiment records
    """
    if score_date is None:
        score_date = date.today()

    analyser = get_analyser()
    results = []

    def _score_company(ticker: str, articles: list[dict]) -> dict:
        unique_articles = deduplicate_articles(articles)
        scored = score_articles(analyser, unique_articles)
        return aggregate_sentiment(ticker, scored, score_date)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_score_company, ticker, articles): ticker for ticker, articles in all_articles.items()
        }

        for future in as_completed(futures):
            ticker = futures[future]
            try:
                agg = future.result()
                results.append(agg)
                if progress_callback:
                    status = "success" if agg.get("sentiment_score") is not None else "empty"
                    progress_callback(ticker, status, f"{ticker}: {agg.get('sentiment_score', 'N/A')}")
            except Exception as e:
                pipeline_logger.error("Sentiment parallel error for %s: %s", ticker, e)
                if progress_callback:
                    progress_callback(ticker, "error", f"{ticker}: {e}")

    scored_count = sum(1 for r in results if r.get("sentiment_score") is not None)
    pipeline_logger.info("Computed sentiment for %d companies (%d with scores)", len(results), scored_count)
    return results


# ---------------------------------------------------------------------------
# Stage-level concurrency: run independent extraction stages simultaneously
# ---------------------------------------------------------------------------


def run_extraction_stages(
    tickers: list[str],
    company_records: list[dict],
    sources: list[str],
    start_date: str,
    end_date: str,
    ds_config: dict,
    progress_callback=None,
    fx_progress_callback=None,
    news_progress_callback=None,
) -> dict:
    """Run FX extraction and cascading news extraction concurrently.

    Architecture (follows reference project gap-fill pattern):
      - FX runs independently in its own thread.
      - News uses a 3-tier cascade, each tier parallel across tickers:
          1. YF News (primary) — all tickers in parallel
          2. GDELT (gap-fill) — only tickers with 0 articles from tier 1
          3. NewsAPI (gap-fill) — only tickers still with 0 after tier 2
                                  (limited to top N per config, requires API key)
      - FX and the entire news cascade run concurrently.

    Each tier has its own circuit breaker and rate limiter for resilience.
    This avoids wasting API calls on sources that aren't needed.

    :param tickers: List of ticker symbols
    :param company_records: List of company dicts for GDELT/NewsAPI
    :param sources: Active data sources
    :param start_date: Start date YYYY-MM-DD
    :param end_date: End date YYYY-MM-DD
    :param ds_config: DataSources configuration dict
    :param progress_callback: Shared fallback callable(item, status, description)
    :param fx_progress_callback: FX-specific progress callback
    :param news_progress_callback: News cascade progress callback
    :return: Dict with keys 'fx_data', 'all_news', 'news_stats'
    """
    results = {"fx_data": {}, "all_news": {}, "news_stats": {}}
    _fx_cb = fx_progress_callback or progress_callback
    _news_cb = news_progress_callback or progress_callback

    def _run_fx():
        if "fx" not in sources:
            return {}
        return parallel_extract_fx(
            start_date=start_date,
            end_date=end_date,
            max_workers=4,
            progress_callback=_fx_cb,
        )

    def _run_news_cascade():
        """Three-tier cascading news extraction with gap-fill."""
        if "news" not in sources:
            return {}, {}

        all_news = {}  # ticker -> [articles]
        stats = {"yf_news": 0, "gdelt": 0, "newsapi": 0}

        # Build ticker->company lookup for GDELT/NewsAPI (need name for query)
        ticker_to_company = {c.get("symbol", "").strip(): c for c in company_records}

        # -- Tier 1: YF News (primary source) — all tickers in parallel --
        yf_news_cb = CircuitBreaker("yf_news", failure_threshold=8, recovery_timeout=45)
        pipeline_logger.info("News cascade tier 1: YF News for %d tickers", len(tickers))

        yf_results = parallel_extract_news(
            tickers=tickers,
            max_workers=4,
            delay_per_ticker=0.3,
            circuit_breaker=yf_news_cb,
            progress_callback=_news_cb,
        )

        # Merge YF results and identify gap tickers
        gap_tickers = []
        for ticker in tickers:
            articles = yf_results.get(ticker, [])
            if articles:
                all_news[ticker] = articles
                stats["yf_news"] += len(articles)
            else:
                gap_tickers.append(ticker)

        pipeline_logger.info(
            "News cascade tier 1 complete: %d tickers with articles, %d gaps (CB: %s, trips=%d)",
            len(tickers) - len(gap_tickers),
            len(gap_tickers),
            yf_news_cb.state.value,
            yf_news_cb._total_trips,
        )

        if not gap_tickers:
            return all_news, stats

        # -- Tier 2: GDELT (gap-fill) — only 0-article tickers --
        gdelt_config = ds_config.get("gdelt", {})
        if gdelt_config.get("enabled", True):
            gdelt_cb = CircuitBreaker("gdelt", failure_threshold=10, recovery_timeout=30)
            gdelt_rl = TokenBucketRateLimiter(rate=5.0, capacity=12, name="gdelt")

            gap_companies = [ticker_to_company[t] for t in gap_tickers if t in ticker_to_company]
            pipeline_logger.info("News cascade tier 2: GDELT for %d gap tickers", len(gap_companies))

            gdelt_results = parallel_extract_gdelt(
                companies=gap_companies,
                timespan=gdelt_config.get("timespan", "3months"),
                max_records=gdelt_config.get("max_records", 15),
                max_workers=12,
                delay_per_company=0.0,
                circuit_breaker=gdelt_cb,
                rate_limiter=gdelt_rl,
                progress_callback=_news_cb,
            )

            # Merge GDELT results and update gaps
            still_gap = []
            for ticker in gap_tickers:
                articles = gdelt_results.get(ticker, [])
                if articles:
                    all_news[ticker] = articles
                    stats["gdelt"] += len(articles)
                else:
                    still_gap.append(ticker)

            pipeline_logger.info(
                "News cascade tier 2 complete: %d filled by GDELT, %d still empty (CB: %s, trips=%d)",
                len(gap_tickers) - len(still_gap),
                len(still_gap),
                gdelt_cb.state.value,
                gdelt_cb._total_trips,
            )
            gap_tickers = still_gap

        if not gap_tickers:
            return all_news, stats

        # -- Tier 3: NewsAPI (gap-fill) — only remaining 0-article tickers --
        newsapi_config = ds_config.get("newsapi", {})
        if newsapi_config.get("enabled", False):
            newsapi_cb = CircuitBreaker("newsapi", failure_threshold=5, recovery_timeout=60)
            # Very conservative: 100 req/day limit → 0.5 req/s burst 2
            newsapi_rl = TokenBucketRateLimiter(rate=0.5, capacity=2, name="newsapi")
            api_key = newsapi_config.get("api_key", "")
            # Resolve ${ENV_VAR} references from config
            if api_key and api_key.startswith("${") and api_key.endswith("}"):
                import os

                api_key = os.environ.get(api_key[2:-1], "")
            only_top_n = newsapi_config.get("only_top_n", 50)

            # Per instructions: limit to top N companies from the gap list
            gap_companies = [ticker_to_company[t] for t in gap_tickers if t in ticker_to_company]
            target_companies = gap_companies[:only_top_n]

            pipeline_logger.info(
                "News cascade tier 3: NewsAPI for %d/%d gap tickers (only_top_n=%d)",
                len(target_companies),
                len(gap_companies),
                only_top_n,
            )

            newsapi_results = parallel_extract_newsapi(
                companies=target_companies,
                api_key=api_key,
                page_size=10,
                max_workers=2,
                max_retries=3,
                circuit_breaker=newsapi_cb,
                rate_limiter=newsapi_rl,
                progress_callback=_news_cb,
            )

            for ticker, articles in newsapi_results.items():
                if articles:
                    all_news[ticker] = articles
                    stats["newsapi"] += len(articles)

            pipeline_logger.info(
                "News cascade tier 3 complete: %d filled by NewsAPI (CB: %s, trips=%d)",
                sum(1 for a in newsapi_results.values() if a),
                newsapi_cb.state.value,
                newsapi_cb._total_trips,
            )
        else:
            pipeline_logger.info("NewsAPI: disabled in config, skipping tier 3")

        return all_news, stats

    # Run FX and the entire news cascade concurrently
    with ThreadPoolExecutor(max_workers=2) as executor:
        fx_future = executor.submit(_run_fx)
        news_future = executor.submit(_run_news_cascade)

        try:
            results["fx_data"] = fx_future.result()
        except Exception as e:
            pipeline_logger.error("FX stage error: %s", e)

        try:
            all_news, news_stats = news_future.result()
            results["all_news"] = all_news
            results["news_stats"] = news_stats
        except Exception as e:
            pipeline_logger.error("News cascade error: %s", e)

    total_articles = sum(len(a) for a in results["all_news"].values())
    stats = results.get("news_stats", {})
    pipeline_logger.info(
        "News cascade summary: %d total articles (YF: %d, GDELT: %d, NewsAPI: %d) across %d tickers",
        total_articles,
        stats.get("yf_news", 0),
        stats.get("gdelt", 0),
        stats.get("newsapi", 0),
        len(results["all_news"]),
    )

    return results
