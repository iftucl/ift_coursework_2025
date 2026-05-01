"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : NewsAPI news article extraction via REST API
Project : CW1 - Value + News Sentiment Strategy

Fetches news articles from the NewsAPI.org ``/v2/everything`` endpoint.
NewsAPI indexes 150,000+ sources and provides structured article data
including title, description, source, and publication timestamp.

API details:
  - Endpoint: https://newsapi.org/v2/everything
  - Access: Free tier — 100 requests/day, 1-month historical lookback
  - Rate limit: Free tier is heavily restricted; use token bucket limiter
  - Parameters: q (company name/ticker), sortBy (publishedAt),
                language (en), pageSize (configurable)

Each article includes: title, description, URL, source name,
publication date, and author.

Reference: NewsAPI.org documentation (https://newsapi.org/docs/endpoints/everything)
"""

import os
import random
import time

import requests

from modules.utils.logger import pipeline_logger

NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"
USER_AGENT = "UCL-IFT-CW1/1.0 (Big Data Coursework)"


def fetch_news_newsapi(
    company_name: str,
    company_id: str,
    api_key: str = None,
    page_size: int = 10,
    max_retries: int = 3,
) -> list[dict]:
    """Fetch news articles for a company from NewsAPI.

    Uses the company's full name for search, falling back to ticker
    symbol if name is unavailable. Implements retry with exponential
    backoff for transient failures.

    :param company_name: Full company name (e.g. 'Apple Inc')
    :type company_name: str
    :param company_id: Ticker symbol for record linkage
    :type company_id: str
    :param api_key: NewsAPI API key (falls back to NEWSAPI_KEY env var)
    :type api_key: str or None
    :param page_size: Max articles to retrieve per request
    :type page_size: int
    :param max_retries: Retry attempts on failure
    :type max_retries: int
    :return: List of article dicts with headline, url, source, date
    :rtype: list[dict]

    Example::

        >>> articles = fetch_news_newsapi('Apple Inc', 'AAPL', api_key='...')
        >>> type(articles)
        <class 'list'>
    """
    key = api_key or os.environ.get("NEWSAPI_KEY", "")
    if not key:
        pipeline_logger.debug("NewsAPI: no API key configured, skipping %s", company_id)
        return []

    # Build search query — use cleaned company name + ticker
    clean_name = company_name.split(",")[0].split(" Inc")[0]
    clean_name = clean_name.split(" Corp")[0].split(" Ltd")[0].strip()
    query = f'"{clean_name}" OR {company_id.split(".")[0]}' if clean_name else company_id

    params = {
        "q": query,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": min(page_size, 100),
        "apiKey": key,
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(
                NEWSAPI_BASE_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=20,
            )
            if response.status_code == 200:
                data = response.json()
                raw_articles = data.get("articles", [])
                articles = []
                for art in raw_articles:
                    source = art.get("source", {})
                    articles.append(
                        {
                            "company_id": company_id,
                            "company_name": company_name,
                            "headline": art.get("title", "") or "",
                            "description": art.get("description", "") or "",
                            "url": art.get("url", ""),
                            "source_name": source.get("name", "") if isinstance(source, dict) else "",
                            "published_at": art.get("publishedAt", ""),
                            "author": art.get("author", ""),
                            "source": "newsapi",
                        }
                    )
                pipeline_logger.info("NewsAPI: %d articles for %s (%s)", len(articles), company_name, company_id)
                return articles
            elif response.status_code == 429:
                # Rate limited — backoff and retry
                delay = 10 * (attempt + 1) * random.uniform(0.5, 1.5)
                pipeline_logger.warning("NewsAPI rate limit for %s — waiting %.1fs", company_id, delay)
                if attempt < max_retries - 1:
                    time.sleep(delay)
            elif response.status_code == 401:
                pipeline_logger.warning("NewsAPI: invalid API key for %s", company_id)
                return []
            elif response.status_code >= 500:
                delay = (2**attempt) * random.uniform(0.5, 1.5)
                pipeline_logger.warning(
                    "NewsAPI HTTP %d for %s (attempt %d) — retrying in %.1fs",
                    response.status_code,
                    company_name,
                    attempt + 1,
                    delay,
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
            else:
                pipeline_logger.warning("NewsAPI returned HTTP %d for %s", response.status_code, company_name)
                return []
        except requests.exceptions.Timeout:
            delay = (2**attempt) * random.uniform(0.5, 1.5)
            pipeline_logger.warning(
                "NewsAPI timeout for %s (attempt %d) — retrying in %.1fs",
                company_name,
                attempt + 1,
                delay,
            )
            if attempt < max_retries - 1:
                time.sleep(delay)
        except requests.exceptions.RequestException as e:
            delay = (2**attempt) * random.uniform(0.5, 1.5)
            pipeline_logger.warning("NewsAPI request error for %s: %s", company_name, e)
            if attempt < max_retries - 1:
                time.sleep(delay)
        except (ValueError, KeyError) as e:
            pipeline_logger.warning("NewsAPI parse error for %s: %s", company_name, e)
            return []

    pipeline_logger.error("NewsAPI: failed after %d attempts for %s", max_retries, company_name)
    return []
