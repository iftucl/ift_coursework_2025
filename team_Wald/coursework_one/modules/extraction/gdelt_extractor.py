"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : GDELT news article extraction via REST API
Project : CW1 - Value + News Sentiment Strategy

Fetches news articles from the GDELT Project API v2 (Global Database
of Events, Language, and Tone).  GDELT provides free, unlimited access
to global news coverage with built-in tone analysis.

API details:
  - Endpoint: https://api.gdeltproject.org/api/v2/doc/doc
  - Access: Completely free, no API key, no rate limits
  - Parameters: query (company name), mode (artlist), format (json),
                timespan (configurable), maxrecords (50)

Each article includes: title, URL, source domain, publication date,
language, and GDELT tone scores.

Reference: Leetaru & Schrodt (2013), "GDELT: Global Data on Events,
Location and Tone, 1979-2012"
"""

import random
import time

import requests

from modules.utils.logger import pipeline_logger

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "UCL-IFT-CW1/1.0 (Big Data Coursework)"


def fetch_news_gdelt(
    company_name: str,
    company_id: str,
    timespan: str = "3months",
    max_records: int = 15,
    max_retries: int = 3,
) -> list[dict]:
    """Fetch news articles for a company from GDELT API.

    Uses the company's full name (not ticker) for better search
    results, as GDELT indexes article text rather than financial
    identifiers.

    Retry logic:
      - Exponential backoff with jitter on timeouts and connection errors
      - HTTP 5xx: retryable (server-side transient errors)
      - HTTP 4xx: not retryable (client errors)
      - Empty results on HTTP 200: retried (GDELT returns empty under load)

    :param company_name: Full company name (e.g. 'Apple Inc')
    :type company_name: str
    :param company_id: Ticker symbol for record linkage
    :type company_id: str
    :param timespan: GDELT timespan parameter (e.g. '3months')
    :type timespan: str
    :param max_records: Maximum articles to retrieve
    :type max_records: int
    :param max_retries: Retry attempts on failure
    :type max_retries: int
    :return: List of article dicts with headline, url, source, date, tone
    :rtype: list[dict]

    Example::

        >>> articles = fetch_news_gdelt('Apple Inc', 'AAPL')
        >>> type(articles)
        <class 'list'>
    """
    # Clean company name — use OR for broader matching
    clean_name = company_name.split(",")[0].split(" Inc")[0]
    clean_name = clean_name.split(" Corp")[0].split(" Ltd")[0]
    clean_name = clean_name.split(" PLC")[0].split(" plc")[0]
    clean_name = clean_name.split(" SE")[0].split(" SA")[0].strip()
    base_symbol = company_id.split(".")[0]
    if clean_name and len(clean_name) > 2:
        query = f'"{clean_name}" OR {base_symbol}'
    else:
        query = base_symbol

    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": max_records,
        "format": "json",
        "sourcelang": "english",
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(
                GDELT_BASE_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=25,
            )
            if response.status_code == 200:
                data = response.json()
                raw_articles = data.get("articles", [])
                articles = []
                for art in raw_articles:
                    articles.append(
                        {
                            "company_id": company_id,
                            "company_name": company_name,
                            "headline": art.get("title", ""),
                            "url": art.get("url", ""),
                            "source_name": art.get("domain", ""),
                            "published_at": art.get("seendate", ""),
                            "language": art.get("language", ""),
                            "gdelt_tone": art.get("tone", 0.0),
                            "source": "gdelt",
                        }
                    )
                # Empty result retry: GDELT sometimes returns 200 OK with 0 articles under load
                if len(articles) == 0 and attempt < max_retries - 1:
                    delay = 2.0 * random.uniform(0.5, 1.5)
                    pipeline_logger.info(
                        "GDELT: 0 articles for %s (attempt %d), retrying in %.1fs",
                        company_id,
                        attempt + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                pipeline_logger.info("GDELT: %d articles for %s (%s)", len(articles), company_name, company_id)
                return articles
            elif response.status_code == 429:
                delay = 5 * (attempt + 1) * random.uniform(0.5, 1.5)
                pipeline_logger.warning("GDELT rate limit — waiting %.1fs", delay)
                if attempt < max_retries - 1:
                    time.sleep(delay)
            elif response.status_code >= 500:
                # Server errors are transient — retry with backoff
                delay = (2**attempt) * random.uniform(0.5, 1.5)
                pipeline_logger.warning(
                    "GDELT HTTP %d for %s (attempt %d) — retrying in %.1fs",
                    response.status_code,
                    company_name,
                    attempt + 1,
                    delay,
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
            else:
                # 4xx client errors are not retryable
                pipeline_logger.warning("GDELT returned HTTP %d for %s", response.status_code, company_name)
                return []
        except requests.exceptions.Timeout:
            delay = (2**attempt) * random.uniform(0.5, 1.5)
            pipeline_logger.warning(
                "GDELT timeout for %s (attempt %d) — retrying in %.1fs",
                company_name,
                attempt + 1,
                delay,
            )
            if attempt < max_retries - 1:
                time.sleep(delay)
        except requests.exceptions.RequestException as e:
            delay = (2**attempt) * random.uniform(0.5, 1.5)
            pipeline_logger.warning("GDELT request error for %s: %s", company_name, e)
            if attempt < max_retries - 1:
                time.sleep(delay)
        except (ValueError, KeyError) as e:
            pipeline_logger.warning("GDELT parse error for %s: %s", company_name, e)
            return []

    pipeline_logger.error("GDELT: failed after %d attempts for %s", max_retries, company_name)
    return []


def fetch_all_companies_news(
    companies: list[dict],
    timespan: str = "3months",
    max_records: int = 50,
    delay_between: float = 0.5,
    max_retries: int = 3,
) -> dict:
    """Fetch GDELT news for all companies in the universe.

    :param companies: List of dicts with 'symbol' and 'security' keys
    :type companies: list[dict]
    :param timespan: GDELT timespan parameter
    :type timespan: str
    :param max_records: Max articles per company
    :type max_records: int
    :param delay_between: Seconds between API calls
    :type delay_between: float
    :param max_retries: Retry attempts per company
    :type max_retries: int
    :return: Dict mapping ticker to list of article dicts
    :rtype: dict

    Example::

        >>> companies = [{'symbol': 'AAPL', 'security': 'Apple Inc'}]
        >>> result = fetch_all_companies_news(companies)
        >>> 'AAPL' in result
        True
    """
    all_news = {}
    total = len(companies)

    for idx, company in enumerate(companies):
        ticker = company.get("symbol", "").strip()
        name = company.get("security", ticker)
        if not ticker:
            continue
        articles = fetch_news_gdelt(
            company_name=name,
            company_id=ticker,
            timespan=timespan,
            max_records=max_records,
            max_retries=max_retries,
        )
        all_news[ticker] = articles
        if idx < total - 1:
            time.sleep(delay_between)
        if (idx + 1) % 50 == 0:
            pipeline_logger.info("GDELT progress: %d/%d companies", idx + 1, total)

    pipeline_logger.info("GDELT extraction complete: %d companies processed", len(all_news))
    return all_news
