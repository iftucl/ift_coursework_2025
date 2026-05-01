"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for DataLoader (security, env-vars, normalisation)
Project : CW2 - Value-Sentiment Investment Strategy

These tests focus on the parts of :class:`modules.data.data_loader.DataLoader`
that don't require a live PostgreSQL or MongoDB instance:

    * Identifier whitelist enforcement (rejects schema-name injection)
    * Env-var credential resolution chain (YAML → env → fail-loud)
    * Mongo article normalisation (the contract that maps CW1's
      ``compound_score``/``published_at`` field names onto the in-memory
      schema CW2's sentiment signal expects)

The full end-to-end query path is covered separately by the integration
test ``tests/test_integration.py``.
"""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from modules.data.data_loader import DataLoader, _resolve_secret


# ----------------------------------------------------------------------
# Credential resolution chain
# ----------------------------------------------------------------------

class TestResolveSecret:

    def test_yaml_value_wins(self, monkeypatch):
        monkeypatch.setenv('TEST_PG', 'env-value')
        assert _resolve_secret('yaml-value', 'TEST_PG') == 'yaml-value'

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv('TEST_PG', 'env-value')
        assert _resolve_secret(None, 'TEST_PG') == 'env-value'
        assert _resolve_secret('', 'TEST_PG') == 'env-value'
        assert _resolve_secret('null', 'TEST_PG') == 'env-value'

    def test_neither_returns_none(self, monkeypatch):
        monkeypatch.delenv('TEST_PG', raising=False)
        assert _resolve_secret(None, 'TEST_PG') is None


# ----------------------------------------------------------------------
# Schema injection guard at construction time
# ----------------------------------------------------------------------

class TestSchemaInjectionGuard:

    def test_rejects_unsafe_schema(self, tmp_path):
        cw1_yaml = tmp_path / 'conf.yaml'
        cw1_yaml.write_text(
            "dev:\n  config:\n    Database:\n      Postgres:\n"
            "        Host: localhost\n        Port: 5439\n"
            "        Database: fift\n        Username: postgres\n"
            "        Password: postgres\n"
        )
        config = {
            'data': {'postgres_schema': 'public; DROP TABLE x; --'},
            'cw1': {'config_path': str(cw1_yaml), 'env_type': 'dev'},
        }
        with pytest.raises(ValueError, match='schema'):
            DataLoader(config)


# ----------------------------------------------------------------------
# Article normalisation contract (no Mongo required)
# ----------------------------------------------------------------------

class TestNormaliseArticles:

    def test_translates_compound_score_to_vader_compound(self):
        articles = [
            {
                'company_id': 'aapl',
                'headline': 'Apple beats earnings',
                'description': 'Quarterly results crushed analyst expectations.',
                'source_name': 'reuters.com',
                'published_at': datetime(2024, 1, 15),
                'compound_score': 0.85,
                'positive_score': 0.6,
                'negative_score': 0.1,
                'neutral_score': 0.3,
            },
        ]
        df = DataLoader._normalise_articles(articles)
        assert 'vader_compound' in df.columns
        assert df['vader_compound'].iloc[0] == pytest.approx(0.85)

    def test_published_at_becomes_article_date(self):
        articles = [
            {
                'company_id': 'msft',
                'published_at': datetime(2024, 4, 30),
                'headline': 'h',
                'description': 'd',
                'compound_score': 0.0,
            },
        ]
        df = DataLoader._normalise_articles(articles)
        assert 'article_date' in df.columns
        assert pd.notna(df['article_date'].iloc[0])

    def test_source_name_to_source_domain(self):
        articles = [{
            'company_id': 'A',
            'source_name': 'bloomberg.com',
            'headline': 'h', 'description': 'd',
            'compound_score': 0.1, 'published_at': datetime(2024, 1, 1),
        }]
        df = DataLoader._normalise_articles(articles)
        assert df['source_domain'].iloc[0] == 'bloomberg.com'

    def test_word_count_from_headline_plus_description(self):
        articles = [{
            'company_id': 'A',
            'headline': 'one two three',
            'description': 'four five',
            'source_name': 'reuters.com',
            'published_at': datetime(2024, 1, 1),
            'compound_score': 0.0,
        }]
        df = DataLoader._normalise_articles(articles)
        assert df['word_count'].iloc[0] == 5

    def test_company_id_normalised_upper(self):
        articles = [{
            'company_id': '  aapl ',
            'headline': 'h', 'description': 'd',
            'source_name': 'reuters.com',
            'published_at': datetime(2024, 1, 1),
            'compound_score': 0.0,
        }]
        df = DataLoader._normalise_articles(articles)
        assert df['company_id'].iloc[0] == 'AAPL'

    def test_missing_compound_score_falls_back(self):
        """If neither compound_score nor vader_compound exist → NaN."""
        articles = [{
            'company_id': 'A',
            'headline': 'h', 'description': 'd',
            'source_name': 'reuters.com',
            'published_at': datetime(2024, 1, 1),
        }]
        df = DataLoader._normalise_articles(articles)
        assert df['vader_compound'].isna().iloc[0]

    def test_missing_published_at_uses_fetched_at(self):
        articles = [{
            'company_id': 'A',
            'headline': 'h', 'description': 'd',
            'source_name': 'reuters.com',
            'fetched_at': datetime(2024, 5, 1),
            'compound_score': 0.0,
        }]
        df = DataLoader._normalise_articles(articles)
        assert pd.notna(df['article_date'].iloc[0])

    def test_empty_articles_returns_empty_df(self):
        df = DataLoader._normalise_articles([])
        assert df.empty

    def test_legacy_vader_compound_field_still_works(self):
        """Older Mongo dumps may have used `vader_compound` directly."""
        articles = [{
            'company_id': 'A',
            'headline': 'h', 'description': 'd',
            'source_name': 'reuters.com',
            'published_at': datetime(2024, 1, 1),
            'vader_compound': 0.42,
        }]
        df = DataLoader._normalise_articles(articles)
        assert df['vader_compound'].iloc[0] == pytest.approx(0.42)
