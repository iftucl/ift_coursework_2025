"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Unit tests for CW1 schema contract module
Project : CW2 - Value-Sentiment Investment Strategy

Locks down the integration contract between CW1 and CW2 so any drift in
column or field names is caught at unit-test time rather than via a
silent-data-loss bug at run time.
"""

import pytest

from modules.data import cw1_schema
from modules.data.cw1_schema import (
    COMPANY_ID_COL,
    DEFAULT_SCHEMA,
    KNOWN_TABLES,
    MONGO_COLLECTION_NEWS,
    MONGO_DB_NAME,
    MONGO_FIELD_COMPOUND_SCORE,
    MONGO_FIELD_PUBLISHED_AT,
    MONGO_NEWS_PROJECTION,
    PRICE_DATE_COL,
    SCORE_DATE_COL,
    SYMBOL_COL,
    TABLE_COMPANY_STATIC,
    TABLE_COMPOSITE_RANKINGS,
    TABLE_DAILY_PRICES,
    TABLE_SENTIMENT_SCORES,
    TABLE_VALUE_METRICS,
    assert_safe_identifier,
    is_safe_identifier,
    normalise_ticker,
)


class TestSchemaConstants:
    """Ensure the contract values match the CW1 DDL exactly."""

    def test_default_schema(self):
        assert DEFAULT_SCHEMA == 'systematic_equity'

    def test_table_names(self):
        assert TABLE_COMPANY_STATIC == 'company_static'
        assert TABLE_DAILY_PRICES == 'daily_prices'
        assert TABLE_VALUE_METRICS == 'value_metrics'
        assert TABLE_SENTIMENT_SCORES == 'sentiment_scores'
        assert TABLE_COMPOSITE_RANKINGS == 'composite_rankings'

    def test_known_tables_complete(self):
        assert TABLE_COMPANY_STATIC in KNOWN_TABLES
        assert TABLE_DAILY_PRICES in KNOWN_TABLES
        assert TABLE_VALUE_METRICS in KNOWN_TABLES
        assert TABLE_SENTIMENT_SCORES in KNOWN_TABLES
        assert TABLE_COMPOSITE_RANKINGS in KNOWN_TABLES

    def test_column_naming_asymmetry(self):
        """daily_prices uses `symbol`; scoring tables use `company_id`."""
        assert SYMBOL_COL == 'symbol'
        assert COMPANY_ID_COL == 'company_id'

    def test_date_column_naming_asymmetry(self):
        """Prices use `cob_date`; scoring tables use `date`."""
        assert PRICE_DATE_COL == 'cob_date'
        assert SCORE_DATE_COL == 'date'


class TestMongoFieldContract:
    """CW1 stores VADER as `compound_score` and date as `published_at`."""

    def test_vader_field_name(self):
        assert MONGO_FIELD_COMPOUND_SCORE == 'compound_score'

    def test_published_at_field_name(self):
        assert MONGO_FIELD_PUBLISHED_AT == 'published_at'

    def test_collection_and_db(self):
        assert MONGO_DB_NAME == 'ift_cw1_sentiment'
        assert MONGO_COLLECTION_NEWS == 'raw_news_articles'

    def test_projection_includes_required_fields(self):
        for required in (
            'company_id', 'headline', 'description', 'source_name',
            'published_at', 'compound_score',
        ):
            assert required in MONGO_NEWS_PROJECTION
            assert MONGO_NEWS_PROJECTION[required] == 1
        assert MONGO_NEWS_PROJECTION['_id'] == 0


class TestIdentifierSafety:
    """Defence-in-depth identifier whitelist."""

    @pytest.mark.parametrize('name', [
        'systematic_equity',
        'company_static',
        'daily_prices',
        'value_metrics',
        '_underscore_start',
        'Mixed_Case_123',
    ])
    def test_valid_identifiers(self, name):
        assert is_safe_identifier(name)

    @pytest.mark.parametrize('name', [
        '',
        '1starts_with_digit',
        'has space',
        'has;semicolon',
        "drop'table",
        'select * from x',
        'has-hyphen',
        'unicode-é',
        None,
        123,
    ])
    def test_invalid_identifiers(self, name):
        assert not is_safe_identifier(name)

    def test_assert_safe_raises_on_injection_attempt(self):
        with pytest.raises(ValueError):
            assert_safe_identifier("public'; DROP TABLE x; --")

    def test_assert_safe_returns_input_on_success(self):
        assert assert_safe_identifier('systematic_equity') == 'systematic_equity'

    def test_assert_safe_kind_label_in_message(self):
        with pytest.raises(ValueError, match='schema'):
            assert_safe_identifier('bad; sql', kind='schema')


class TestTickerNormalisation:
    """CW1 trims and uppercases tickers; CW2 must do the same."""

    @pytest.mark.parametrize('input_ticker,expected', [
        ('AAPL', 'AAPL'),
        ('aapl', 'AAPL'),
        ('  aapl  ', 'AAPL'),
        ('VOD.L', 'VOD.L'),
        ('brk-b', 'BRK-B'),
    ])
    def test_normalise_known_tickers(self, input_ticker, expected):
        assert normalise_ticker(input_ticker) == expected

    def test_normalise_none_raises(self):
        with pytest.raises(ValueError):
            normalise_ticker(None)

    def test_normalise_empty_raises(self):
        with pytest.raises(ValueError):
            normalise_ticker('   ')
