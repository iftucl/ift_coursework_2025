"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : CW1 schema contract — single source of truth for CW1↔CW2 integration
Project : CW2 - Value-Sentiment Investment Strategy

Centralises every column name, table name, MongoDB collection, MongoDB
field, and value convention that CW2 expects from CW1.  This module is
the single point at which CW2 asserts the shape of the CW1 data
contract; if CW1 ever changes a column or field name, *only this file*
needs to be updated.

Why a dedicated contract module?

    * **Ticker-vs-company_id naming asymmetry** — ``daily_prices`` and
      ``company_static`` use ``symbol``, but ``value_metrics``,
      ``sentiment_scores`` and ``composite_rankings`` use ``company_id``
      for the *same* underlying ticker. That's a foot-gun. Naming this
      explicitly here removes the magic.
    * **Date-column asymmetry** — ``daily_prices`` and ``fx_rates`` use
      ``cob_date`` (close-of-business); the scoring tables use ``date``.
    * **MongoDB field convention** — CW1 stores VADER compound as
      ``compound_score`` (not ``vader_compound``) and the article date
      as ``published_at`` (not ``date``/``seendate``). Hard-coding those
      strings in the loader caused silent data loss before this module
      existed.
    * **Identifier validation** — used by data_loader to whitelist any
      schema/table/column it interpolates into SQL (defence-in-depth on
      top of psycopg2 parameter binding).

Ref: CW1 ``static/schema/create_tables.sql`` and ``conf.yaml``.
"""

from __future__ import annotations

import re
from typing import FrozenSet


# ---------------------------------------------------------------------------
# Schema and table names (psql-side identifiers that may be interpolated
# directly into SQL strings — so they must pass strict validation).
# ---------------------------------------------------------------------------

DEFAULT_SCHEMA: str = 'systematic_equity'

TABLE_COMPANY_STATIC: str = 'company_static'
TABLE_DAILY_PRICES: str = 'daily_prices'
TABLE_VALUE_METRICS: str = 'value_metrics'
TABLE_SENTIMENT_SCORES: str = 'sentiment_scores'
TABLE_COMPOSITE_RANKINGS: str = 'composite_rankings'
TABLE_FX_RATES: str = 'fx_rates'
TABLE_INGESTION_LOG: str = 'ingestion_log'
TABLE_PIPELINE_METADATA: str = 'pipeline_metadata'

KNOWN_TABLES: FrozenSet[str] = frozenset({
    TABLE_COMPANY_STATIC,
    TABLE_DAILY_PRICES,
    TABLE_VALUE_METRICS,
    TABLE_SENTIMENT_SCORES,
    TABLE_COMPOSITE_RANKINGS,
    TABLE_FX_RATES,
    TABLE_INGESTION_LOG,
    TABLE_PIPELINE_METADATA,
})


# ---------------------------------------------------------------------------
# Column-name conventions
# ---------------------------------------------------------------------------

# `daily_prices` / `company_static` use `symbol`
SYMBOL_COL: str = 'symbol'

# `value_metrics` / `sentiment_scores` / `composite_rankings` use `company_id`
COMPANY_ID_COL: str = 'company_id'

# Date column conventions
PRICE_DATE_COL: str = 'cob_date'  # daily_prices, fx_rates
SCORE_DATE_COL: str = 'date'  # value_metrics, sentiment_scores, composite_rankings


# ---------------------------------------------------------------------------
# MongoDB collection + document field convention
# ---------------------------------------------------------------------------

MONGO_DB_NAME: str = 'ift_cw1_sentiment'
MONGO_COLLECTION_NEWS: str = 'raw_news_articles'
MONGO_COLLECTION_FINANCIALS: str = 'raw_financial_data'
MONGO_COLLECTION_PRICES: str = 'raw_price_history'

# News-article fields as written by CW1 ``mongo_loader.store_news_articles``
MONGO_FIELD_COMPANY_ID: str = 'company_id'
MONGO_FIELD_COMPANY_NAME: str = 'company_name'  # used for relevance matching in CW2 sentiment signal
MONGO_FIELD_HEADLINE: str = 'headline'
MONGO_FIELD_DESCRIPTION: str = 'description'
MONGO_FIELD_SOURCE_NAME: str = 'source_name'
MONGO_FIELD_PUBLISHED_AT: str = 'published_at'
MONGO_FIELD_FETCHED_AT: str = 'fetched_at'
MONGO_FIELD_URL: str = 'url'
MONGO_FIELD_SOURCE: str = 'source'  # 'gdelt', 'yf_news', 'newsapi'

# VADER scores stored per-article by CW1
MONGO_FIELD_COMPOUND_SCORE: str = 'compound_score'
MONGO_FIELD_POSITIVE_SCORE: str = 'positive_score'
MONGO_FIELD_NEGATIVE_SCORE: str = 'negative_score'
MONGO_FIELD_NEUTRAL_SCORE: str = 'neutral_score'

# Default Mongo projection for CW2 quality-weighted sentiment
MONGO_NEWS_PROJECTION: dict = {
    '_id': 0,
    MONGO_FIELD_COMPANY_ID: 1,
    MONGO_FIELD_COMPANY_NAME: 1,
    MONGO_FIELD_HEADLINE: 1,
    MONGO_FIELD_DESCRIPTION: 1,
    MONGO_FIELD_SOURCE_NAME: 1,
    MONGO_FIELD_PUBLISHED_AT: 1,
    MONGO_FIELD_FETCHED_AT: 1,
    MONGO_FIELD_URL: 1,
    MONGO_FIELD_SOURCE: 1,
    MONGO_FIELD_COMPOUND_SCORE: 1,
    MONGO_FIELD_POSITIVE_SCORE: 1,
    MONGO_FIELD_NEGATIVE_SCORE: 1,
    MONGO_FIELD_NEUTRAL_SCORE: 1,
}


# ---------------------------------------------------------------------------
# Identifier-safety regex (defence-in-depth alongside parameter binding)
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def is_safe_identifier(name: str) -> bool:
    """Return True iff ``name`` is a syntactically valid SQL identifier.

    Used by :class:`modules.data.data_loader.DataLoader` to whitelist any
    schema or table name *before* it is interpolated into a SQL string.
    Combined with parameter binding for all *value* placeholders, this
    eliminates SQL injection.

    :param name: Candidate identifier
    :type name: str
    :returns: True if valid (alpha + alnum + underscore, not starting with digit)
    :rtype: bool
    """
    if not isinstance(name, str) or not name:
        return False
    return bool(_IDENT_RE.match(name))


def assert_safe_identifier(name: str, kind: str = 'identifier') -> str:
    """Raise ``ValueError`` if ``name`` is not a safe SQL identifier.

    :param name: Candidate identifier (schema, table, or column)
    :type name: str
    :param kind: Human label used in the error message (e.g. ``'schema'``)
    :type kind: str
    :returns: ``name`` unchanged on success
    :rtype: str
    :raises ValueError: If ``name`` contains characters outside ``[A-Za-z0-9_]``
                        or starts with a digit.
    """
    if not is_safe_identifier(name):
        raise ValueError(
            f"Unsafe {kind}: {name!r} — must match [A-Za-z_][A-Za-z0-9_]*"
        )
    return name


def normalise_ticker(symbol: str) -> str:
    """Apply CW1's ticker normalisation conventions.

    CW1 trims whitespace and uppercases tickers throughout. This helper
    enforces the same convention so that joins between CW2 in-memory
    structures and CW1 database rows always agree.

    :param symbol: Raw ticker as provided by upstream caller
    :type symbol: str
    :returns: Trimmed, uppercased ticker
    :rtype: str
    :raises ValueError: If ``symbol`` is empty after stripping
    """
    if symbol is None:
        raise ValueError("Ticker cannot be None")
    cleaned = str(symbol).strip().upper()
    if not cleaned:
        raise ValueError("Ticker cannot be empty after stripping")
    return cleaned
