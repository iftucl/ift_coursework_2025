"""Finnhub news extractor for company-level news articles.

Fetches news articles from the Finnhub REST API (free tier: 60 req/min).
Covers approximately 1-2 years of historical news per company.
Articles are returned as raw dicts for downstream sentiment scoring.

Noise-reduction measures applied:

1. Language filter: English only (via ``langid``).
2. Relevance: Finnhub's ``/company-news`` endpoint is ticker-scoped, so
   all returned articles are already company-specific.
3. Deduplication: URL-based dedup via Redis SET (survives pipeline restarts).
4. Minimum headline length: headlines < 10 chars discarded.

Rate limiting: 60 req/min, enforced via :class:`~modules.utils.resilience.TokenBucket`.
Circuit breaker: opens after 5 consecutive failures, recovers after 120 s.

Example usage::

    from modules.extract.finnhub_news import run_finnhub_extraction

    articles = run_finnhub_extraction(["AAPL", "MSFT"], backfill_years=2)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from modules.utils.resilience import get_circuit_breaker, get_token_bucket, retry_with_backoff

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
_MAX_HISTORY_YEARS = 2  # Finnhub free tier covers ~1-2 years
_MIN_HEADLINE_LEN = 10
_CHUNK_DAYS = 30  # Query in monthly chunks to stay within Finnhub pagination

_cb = get_circuit_breaker("finnhub", failure_threshold=5, recovery_timeout=120)
_tb = get_token_bucket("finnhub", rate=55, period=60)  # 55/60 — safety margin


# ---------------------------------------------------------------------------
# Deduplication via Redis
# ---------------------------------------------------------------------------


def _is_duplicate(url: str, *, symbol: str = "") -> bool:
    """Check and register URL in Redis deduplication SET.

    :param url: Article URL to check.
    :param symbol: Optional ticker symbol namespace for per-symbol deduplication.
    :type url: str
    :returns: ``True`` if already seen.
    :rtype: bool
    """
    from modules.utils.resilience import _get_redis

    r = _get_redis()
    if r is None:
        return False  # No Redis → no dedup (acceptable in test mode)
    symbol_ns = str(symbol or "").strip().upper()
    key = "cw1:news:seen_urls"
    if symbol_ns:
        key = f"{key}:{symbol_ns}"
    added = r.sadd(key, url)
    r.expire(key, 60 * 60 * 24 * 30)  # 30-day TTL
    return added == 0  # 0 means already existed


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def _is_english(text: str) -> bool:
    """Return ``True`` if *text* is detected as English.

    Falls back to ``True`` when ``langid`` is unavailable.

    :param text: Text to classify.
    :type text: str
    :returns: Whether the text is English.
    :rtype: bool
    """
    if not text or len(text) < 10:
        return True
    try:
        import langid  # type: ignore

        lang, _ = langid.classify(text)
        return lang == "en"
    except Exception:
        return True


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------


def _get_api_key() -> Optional[str]:
    """Return Finnhub API key from environment.

    :returns: API key string or ``None``.
    :rtype: str | None
    """
    key = os.getenv("FINNHUB_API_KEY", "").strip()
    return key if key else None


@retry_with_backoff(max_retries=3, base_delay=2.0, max_delay=30.0, service="finnhub")
def _fetch_company_news_raw(
    symbol: str,
    from_date: date,
    to_date: date,
    api_key: str,
) -> List[Dict[str, Any]]:
    """Fetch raw news articles from Finnhub for one symbol and date range.

    :param symbol: Ticker symbol.
    :param from_date: Start date (inclusive).
    :param to_date: End date (inclusive).
    :param api_key: Finnhub API key.
    :returns: List of raw article dicts from Finnhub.
    :rtype: list[dict]
    :raises requests.HTTPError: On non-200 response.
    """
    _tb.acquire()
    url = f"{FINNHUB_BASE_URL}/company-news"
    params = {
        "symbol": symbol,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "token": api_key,
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


@_cb.protect
def fetch_news_for_symbol(
    symbol: str,
    *,
    from_date: date,
    to_date: date,
    api_key: str,
) -> List[Dict[str, Any]]:
    """Fetch and filter news articles for one symbol over the given date range.

    Applies language filter, minimum headline length, and URL deduplication.

    :param symbol: Ticker symbol.
    :param from_date: Start date (inclusive).
    :param to_date: End date (inclusive).
    :param api_key: Finnhub API key.
    :returns: Filtered list of article dicts with normalized fields.
    :rtype: list[dict]
    """
    articles: List[Dict[str, Any]] = []

    # Query in monthly chunks.
    chunk_start = from_date
    while chunk_start <= to_date:
        chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS - 1), to_date)
        try:
            raw = _fetch_company_news_raw(symbol, chunk_start, chunk_end, api_key)
        except Exception as exc:
            logger.warning(
                "finnhub: fetch failed symbol=%s %s..%s error=%s",
                symbol,
                chunk_start,
                chunk_end,
                exc,
            )
            chunk_start = chunk_end + timedelta(days=1)
            continue

        for item in raw:
            article = _normalize_article(symbol, item)
            if article is None:
                continue
            articles.append(article)

        logger.debug(
            "finnhub: symbol=%s %s..%s raw=%s kept=%s",
            symbol,
            chunk_start,
            chunk_end,
            len(raw),
            len(articles),
        )
        chunk_start = chunk_end + timedelta(days=1)

    return articles


# ---------------------------------------------------------------------------
# Normalization & filtering
# ---------------------------------------------------------------------------


def _normalize_article(symbol: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one raw Finnhub article dict; return ``None`` to discard.

    :param symbol: Ticker symbol the article relates to.
    :param item: Raw article dict from Finnhub API.
    :returns: Normalized article dict or ``None`` if filtered out.
    :rtype: dict | None
    """
    headline = str(item.get("headline") or "").strip()
    if len(headline) < _MIN_HEADLINE_LEN:
        return None

    summary = str(item.get("summary") or "").strip()
    url = str(item.get("url") or "").strip()

    # Language filter on headline + summary
    combined_text = f"{headline} {summary}"
    if not _is_english(combined_text):
        return None

    # URL deduplication
    if url and _is_duplicate(url, symbol=symbol):
        return None

    # Published timestamp → date
    ts = item.get("datetime")
    pub_date: Optional[date] = None
    if ts:
        try:
            pub_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        except (ValueError, TypeError, OSError):
            pass

    return {
        "symbol": symbol,
        "publish_date": pub_date,
        "headline": headline,
        "summary": summary,
        "url": url,
        "source": str(item.get("source") or "finnhub"),
        "data_source": "finnhub",
        "category": str(item.get("category") or ""),
    }


# ---------------------------------------------------------------------------
# Bulk runner
# ---------------------------------------------------------------------------


def run_finnhub_extraction(
    symbols: List[str],
    *,
    backfill_years: int = 2,
    as_of: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Fetch Finnhub news for all symbols.

    :param symbols: List of ticker symbols.
    :type symbols: list[str]
    :param backfill_years: Years of history to fetch (capped at ``_MAX_HISTORY_YEARS``).
    :type backfill_years: int
    :param as_of: Reference end date. Defaults to today.
    :type as_of: date | None
    :returns: All filtered article dicts across all symbols.
    :rtype: list[dict]
    """
    api_key = _get_api_key()
    if not api_key:
        logger.error(
            "finnhub: FINNHUB_API_KEY not set. "
            "Set it in .env or environment. Skipping Finnhub extraction."
        )
        return []

    to_date = as_of or date.today()
    years = min(backfill_years, _MAX_HISTORY_YEARS)
    from_date = to_date - timedelta(days=years * 365)

    all_articles: List[Dict[str, Any]] = []
    total = len(symbols)

    for idx, symbol in enumerate(symbols, 1):
        logger.info("finnhub: processing %s/%s symbol=%s", idx, total, symbol)
        articles = fetch_news_for_symbol(
            symbol, from_date=from_date, to_date=to_date, api_key=api_key
        )
        all_articles.extend(articles)
        logger.info("finnhub: symbol=%s articles=%s", symbol, len(articles))

    logger.info(
        "finnhub: extraction complete total_articles=%s symbols=%s",
        len(all_articles),
        total,
    )
    return all_articles
