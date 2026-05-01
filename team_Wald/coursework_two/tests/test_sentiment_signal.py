"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for quality-weighted sentiment signal
Project : CW2 - Value-Sentiment Investment Strategy

Coverage target: 85%+
"""

import numpy as np
import pandas as pd
import pytest

from modules.signals.sentiment_signal import SentimentSignal


@pytest.fixture
def config():
    return {
        'sentiment': {
            'half_life_days': 7,
            'source_tiers': {
                'tier1': ['reuters.com', 'bloomberg.com'],
                'tier2': ['cnbc.com'],
                'tier3': ['seekingalpha.com'],
            },
            'tier_weights': {'tier1': 1.0, 'tier2': 0.7, 'tier3': 0.4, 'default': 0.3},
        },
        'scoring': {
            'shrinkage_k_sentiment': 5,
            'min_sentiment_confidence': 0.3,
        },
    }


@pytest.fixture
def sample_sentiment_df():
    return pd.DataFrame({
        'company_id': ['AAPL', 'MSFT', 'GOOGL', 'AMZN'],
        'date': pd.to_datetime(['2024-01-15'] * 4),
        'avg_sentiment': [0.3, 0.1, -0.1, 0.5],
        'positive_count': [8, 5, 3, 12],
        'negative_count': [2, 4, 6, 1],
        'neutral_count': [5, 6, 6, 2],
        'total_articles': [15, 15, 15, 15],
        'positive_ratio': [0.53, 0.33, 0.20, 0.80],
        'sentiment_score': [65, 52, 40, 78],
    })


class TestSentimentSignal:

    def test_basic_scoring(self, config, sample_sentiment_df):
        signal = SentimentSignal(config)
        result = signal.compute(sample_sentiment_df, pd.Timestamp('2024-01-31'))
        assert len(result) == 4
        assert 'sentiment_score' in result.columns
        assert 'confidence' in result.columns

    def test_bayesian_shrinkage(self, config):
        """Stocks with few articles should be shrunk toward zero."""
        signal = SentimentSignal(config)
        df = pd.DataFrame({
            'company_id': ['FEW', 'MANY'],
            'date': pd.to_datetime(['2024-01-15'] * 2),
            'avg_sentiment': [0.5, 0.5],
            'total_articles': [1, 50],
            'positive_ratio': [0.8, 0.8],
            'sentiment_score': [70, 70],
        })
        result = signal.compute(df, pd.Timestamp('2024-01-31'))
        few_conf = result[result['company_id'] == 'FEW']['confidence'].iloc[0]
        many_conf = result[result['company_id'] == 'MANY']['confidence'].iloc[0]
        assert many_conf > few_conf, "More articles should give higher confidence"

    def test_confidence_range(self, config, sample_sentiment_df):
        """Confidence should be between 0 and 1."""
        signal = SentimentSignal(config)
        result = signal.compute(sample_sentiment_df, pd.Timestamp('2024-01-31'))
        assert (result['confidence'] >= 0).all()
        assert (result['confidence'] <= 1).all()

    def test_zero_articles(self, config):
        """Stocks with zero articles should have zero confidence."""
        signal = SentimentSignal(config)
        df = pd.DataFrame({
            'company_id': ['NONE'],
            'date': pd.to_datetime(['2024-01-15']),
            'avg_sentiment': [None],
            'total_articles': [0],
            'positive_ratio': [None],
            'sentiment_score': [None],
        })
        result = signal.compute(df, pd.Timestamp('2024-01-31'))
        assert result['confidence'].iloc[0] == 0.0

    def test_empty_input(self, config):
        df = pd.DataFrame(columns=['company_id', 'date', 'avg_sentiment',
                                    'total_articles', 'positive_ratio', 'sentiment_score'])
        signal = SentimentSignal(config)
        result = signal.compute(df, pd.Timestamp('2024-01-31'))
        assert len(result) == 0


class TestArticleLevelRelevance:
    """Tests for the new Part A §A3 relevance scheme.

    The PDF specifies +0.5 for company in headline, +0.3 for company in
    body, +0.2 for word_count >= 500. The previous implementation used
    headline-length as a proxy; the v2.3 fidelity pass replaces that
    with real company-name matching against the ``company_name`` /
    ``company_id`` fields propagated from CW1 MongoDB.
    """

    def test_company_name_in_headline_gives_high_relevance(self):
        df = pd.DataFrame({
            'headline': ['Apple Inc beats Q4 earnings expectations'],
            'description': ['stuff'],
            'word_count': [50],
            'company_name': ['Apple Inc'],
            'company_id': ['AAPL'],
        })
        rel = SentimentSignal._compute_relevance(df)
        # company in headline → at least 0.5
        assert rel.iloc[0] >= 0.5

    def test_company_in_body_only_gets_lower_score(self):
        df = pd.DataFrame({
            'headline': ['Tech sector roundup'],  # no company
            'description': ['Apple Inc reported solid earnings.'],
            'word_count': [50],
            'company_name': ['Apple Inc'],
            'company_id': ['AAPL'],
        })
        rel = SentimentSignal._compute_relevance(df)
        # body only → 0.3
        assert 0.25 <= rel.iloc[0] <= 0.35

    def test_long_article_bonus(self):
        df = pd.DataFrame({
            'headline': ['Tech sector roundup'],
            'description': ['Generic content'],
            'word_count': [600],
            'company_name': ['Apple Inc'],
            'company_id': ['AAPL'],
        })
        rel = SentimentSignal._compute_relevance(df)
        # length bonus only → 0.2
        assert 0.15 <= rel.iloc[0] <= 0.25

    def test_all_three_bonuses_max_one(self):
        df = pd.DataFrame({
            'headline': ['Apple Inc soars on iPhone sales'],
            'description': ['Apple Inc reported record quarterly results...'],
            'word_count': [800],
            'company_name': ['Apple Inc'],
            'company_id': ['AAPL'],
        })
        rel = SentimentSignal._compute_relevance(df)
        # 0.5 + 0.3 + 0.2 = 1.0
        assert abs(rel.iloc[0] - 1.0) < 1e-9

    def test_no_company_match_falls_to_floor(self):
        df = pd.DataFrame({
            'headline': ['Microsoft beats expectations'],
            'description': ['Microsoft Corp reported earnings'],
            'word_count': [100],
            'company_name': ['Apple Inc'],
            'company_id': ['AAPL'],
        })
        rel = SentimentSignal._compute_relevance(df)
        # No Apple/AAPL match → just the 0.05 floor
        assert rel.iloc[0] == pytest.approx(0.05)

    def test_ticker_fallback_when_name_missing(self):
        df = pd.DataFrame({
            'headline': ['AAPL hits new all-time high'],
            'description': ['Trader notes'],
            'word_count': [50],
            'company_name': [''],
            'company_id': ['AAPL'],
        })
        rel = SentimentSignal._compute_relevance(df)
        # Ticker in headline → 0.5
        assert rel.iloc[0] >= 0.5

    def test_relevance_is_case_insensitive(self):
        df = pd.DataFrame({
            'headline': ['APPLE INC beats earnings'],
            'description': [''],
            'word_count': [20],
            'company_name': ['Apple Inc'],
            'company_id': ['AAPL'],
        })
        rel = SentimentSignal._compute_relevance(df)
        assert rel.iloc[0] >= 0.5


class TestArticleLevelEndToEnd:
    """Smoke test: feed the article-level path through compute() end-to-end."""

    def test_compute_with_article_level_data(self, base_config):
        df = pd.DataFrame({
            'company_id': ['AAPL', 'AAPL', 'AAPL', 'MSFT', 'MSFT'],
            'company_name': ['Apple Inc'] * 3 + ['Microsoft Corp'] * 2,
            'headline': [
                'Apple Inc beats Q4 earnings',
                'Apple Inc unveils new iPhone',
                'Tech sector wrap',  # body match only
                'Microsoft Azure growth accelerates',
                'Microsoft Corp announces buyback',
            ],
            'description': [
                'Earnings beat by 10%',
                'New product unveiled',
                'Apple Inc among the leaders',
                'Cloud revenue strong',
                'Capital return',
            ],
            'word_count': [600, 200, 100, 300, 250],
            'source_domain': ['reuters.com', 'bloomberg.com', 'cnbc.com', 'reuters.com', 'wsj.com'],
            'article_date': pd.to_datetime(['2024-04-15'] * 5),
            'vader_compound': [0.7, 0.5, 0.2, 0.6, 0.4],
        })
        signal = SentimentSignal(base_config)
        result = signal.compute(df, pd.Timestamp('2024-04-30'))
        assert 'sentiment_score' in result.columns
        assert 'confidence' in result.columns
        assert len(result) == 2  # AAPL + MSFT
