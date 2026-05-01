"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : MongoDB loader for news articles and sentiment documents
Project : CW1 - Value + News Sentiment Strategy

Stores raw news articles in the ``raw_news_articles`` collection and
updates them with VADER sentiment scores after analysis.  Supports
querying by company_id and date range for downstream processing.

Each document schema::

    {
        "company_id":   "AAPL",
        "company_name": "Apple Inc",
        "headline":     "Apple Reports Record Revenue...",
        "description":  "Apple Inc reported...",
        "source_name":  "reuters.com",
        "published_at": "2025-10-28T14:30:00Z",
        "url":          "https://...",
        "source":       "gdelt",
        "fetched_at":   ISODate("2026-02-25T10:00:00Z"),
        "compound_score": 0.7003,
        "positive_score": 0.594,
        "negative_score": 0.0,
        "neutral_score":  0.406
    }
"""

from modules.db.mongo_connection import MongoDBClient

RAW_NEWS_COLLECTION = "raw_news_articles"


def store_news_articles(mongo: MongoDBClient, articles: list[dict]) -> int:
    """Store raw news articles in MongoDB raw_news_articles collection.

    Each article dict should contain at minimum: company_id, headline,
    source_name, published_at.  A ``fetched_at`` timestamp is added
    automatically by the MongoDB client.

    :param mongo: Active MongoDB client
    :type mongo: MongoDBClient
    :param articles: List of article dicts from GDELT or Yahoo Finance
    :type articles: list[dict]
    :return: Number of documents inserted
    :rtype: int

    Example::

        >>> count = store_news_articles(mongo, [{'company_id': 'AAPL', 'headline': 'Test'}])
        >>> count
        1
    """
    if not articles:
        return 0
    return mongo.insert_documents(RAW_NEWS_COLLECTION, articles)


def store_articles_for_company(
    mongo: MongoDBClient,
    company_id: str,
    company_name: str,
    articles: list[dict],
) -> int:
    """Store articles for a specific company, enriching each with identifiers.

    :param mongo: Active MongoDB client
    :type mongo: MongoDBClient
    :param company_id: Ticker symbol
    :type company_id: str
    :param company_name: Full company name
    :type company_name: str
    :param articles: List of raw article dicts
    :type articles: list[dict]
    :return: Number of documents inserted
    :rtype: int
    """
    enriched = []
    for art in articles:
        doc = dict(art)
        doc["company_id"] = company_id
        doc["company_name"] = company_name
        enriched.append(doc)
    return store_news_articles(mongo, enriched)


def update_article_sentiment(
    mongo: MongoDBClient,
    article_query: dict,
    sentiment_scores: dict,
) -> int:
    """Update an article document with VADER sentiment scores.

    Called after sentiment analysis to enrich the raw article with
    compound, positive, negative, and neutral scores.

    :param mongo: Active MongoDB client
    :type mongo: MongoDBClient
    :param article_query: MongoDB query to identify the article
    :type article_query: dict
    :param sentiment_scores: Dict with compound_score, positive_score,
                             negative_score, neutral_score
    :type sentiment_scores: dict
    :return: Number of documents modified
    :rtype: int
    """
    return mongo.update_document(
        RAW_NEWS_COLLECTION,
        article_query,
        {"$set": sentiment_scores},
    )


def get_company_articles(
    mongo: MongoDBClient,
    company_id: str,
    limit: int = 0,
) -> list[dict]:
    """Retrieve all articles for a company from MongoDB.

    :param mongo: Active MongoDB client
    :type mongo: MongoDBClient
    :param company_id: Ticker symbol
    :type company_id: str
    :param limit: Max articles to return (0 = unlimited)
    :type limit: int
    :return: List of article documents
    :rtype: list[dict]
    """
    return mongo.query_documents(
        RAW_NEWS_COLLECTION,
        {"company_id": company_id},
        limit=limit,
    )


def get_articles_by_date_range(
    mongo: MongoDBClient,
    company_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Retrieve articles for a company within a date range.

    :param mongo: Active MongoDB client
    :type mongo: MongoDBClient
    :param company_id: Ticker symbol
    :type company_id: str
    :param start_date: Start date ISO string
    :type start_date: str
    :param end_date: End date ISO string
    :type end_date: str
    :return: List of article documents
    :rtype: list[dict]
    """
    query = {
        "company_id": company_id,
        "published_at": {"$gte": start_date, "$lte": end_date},
    }
    return mongo.query_documents(RAW_NEWS_COLLECTION, query)
