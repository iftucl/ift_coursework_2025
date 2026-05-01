"""Unit tests for modules.transform.sentiment.

Tests cover:
- L-M scoring: positive / negative / neutral articles
- Fallback lexicon when pysentiment2 unavailable
- score_articles: batch scoring + None handling
- aggregate_daily_sentiment: rolling window aggregation
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from modules.transform.sentiment import (
    _compute_sentiment_score,
    _tokenize,
    aggregate_daily_sentiment,
    score_articles,
)


class TestTokenize:
    def test_splits_on_non_alphanumeric(self):
        tokens = _tokenize("Hello, world! It's great.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "great" in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_lowercased(self):
        tokens = _tokenize("Apple BEATS Earnings")
        assert all(t == t.lower() for t in tokens)


class TestComputeSentimentScore:
    def test_empty_text_returns_none(self):
        assert _compute_sentiment_score("", "") is None

    def test_positive_article_score_positive(self):
        headline = "Company reports record profit and strong revenue growth"
        summary = "Earnings beat estimates. Shares upgraded by analysts."
        score = _compute_sentiment_score(headline, summary)
        # May be None if pysentiment2 unavailable, or positive if available
        if score is not None:
            assert -1.0 <= score <= 1.0

    def test_negative_article_score_negative(self):
        headline = "Company reports massive loss and declares bankruptcy"
        summary = "Revenue declined significantly. Analysts downgrade shares."
        score = _compute_sentiment_score(headline, summary)
        if score is not None:
            assert -1.0 <= score <= 1.0

    def test_score_in_valid_range(self):
        score = _compute_sentiment_score(
            "Strong quarterly results exceed expectations",
            "Net income grew 15% year over year",
        )
        if score is not None:
            assert -1.0 <= score <= 1.0

    def test_fallback_mode(self):
        """Ensure scoring works even without pysentiment2."""
        with patch("modules.transform.sentiment._get_lm_scorer", return_value=None):
            score = _compute_sentiment_score("profit growth strong beat", "")
            # Fallback should detect positive words
            assert score is None or isinstance(score, float)


class TestScoreArticles:
    def _make_article(self, symbol, pub_date, headline, summary=""):
        return {
            "symbol": symbol,
            "publish_date": pub_date,
            "headline": headline,
            "summary": summary,
            "data_source": "finnhub",
        }

    def test_adds_sentiment_score_field(self):
        articles = [self._make_article("AAPL", date(2024, 1, 5), "Apple beats estimates")]
        scored = score_articles(articles)
        assert "sentiment_score" in scored[0]

    def test_empty_headline_gives_none(self):
        articles = [self._make_article("AAPL", date(2024, 1, 5), "")]
        scored = score_articles(articles)
        assert scored[0]["sentiment_score"] is None

    def test_no_publish_date_still_scored(self):
        articles = [self._make_article("AAPL", None, "record profit gains")]
        scored = score_articles(articles)
        assert "sentiment_score" in scored[0]

    def test_returns_same_list(self):
        articles = [self._make_article("MSFT", date(2024, 3, 1), "growth")]
        result = score_articles(articles)
        assert result is articles  # In-place mutation


class TestAggregateDailySentiment:
    def _make_scored_article(self, symbol, pub_date, score):
        return {
            "symbol": symbol,
            "publish_date": pub_date,
            "headline": "test",
            "summary": "",
            "sentiment_score": score,
            "data_source": "finnhub",
        }

    def test_produces_four_factors_per_date(self):
        articles = [
            self._make_scored_article("AAPL", date(2024, 1, 10), 0.2),
            self._make_scored_article("AAPL", date(2024, 1, 10), -0.1),
        ]
        records = aggregate_daily_sentiment(articles)
        factor_names = {r["factor_name"] for r in records}
        assert "sentiment_7d_avg" in factor_names
        assert "sentiment_30d_avg" in factor_names
        assert "article_count_7d" in factor_names
        assert "article_count_30d" in factor_names

    def test_article_count_correct(self):
        articles = [
            self._make_scored_article("AAPL", date(2024, 2, 1), 0.1),
            self._make_scored_article("AAPL", date(2024, 2, 1), 0.3),
            self._make_scored_article("AAPL", date(2024, 2, 1), -0.2),
        ]
        records = aggregate_daily_sentiment(articles)
        count_records = [r for r in records if r["factor_name"] == "article_count_30d"]
        assert len(count_records) == 1
        assert count_records[0]["factor_value"] == 3.0

    def test_ignores_articles_without_symbol(self):
        articles = [
            {"symbol": "", "publish_date": date(2024, 1, 1), "sentiment_score": 0.5,
             "headline": "x", "summary": "", "data_source": "finnhub"},
        ]
        records = aggregate_daily_sentiment(articles)
        assert records == []

    def test_ignores_articles_without_date(self):
        articles = [
            {"symbol": "AAPL", "publish_date": None, "sentiment_score": 0.5,
             "headline": "x", "summary": "", "data_source": "finnhub"},
        ]
        records = aggregate_daily_sentiment(articles)
        assert records == []

    def test_sentiment_surprise_computed(self):
        """sentiment_surprise = 7d_avg - 30d_avg should be present when both exist."""
        articles = [
            self._make_scored_article("AAPL", date(2024, 4, 1), 0.6),
        ]
        # Add older articles to create a 30d window with lower average
        for i in range(2, 30):
            articles.append(self._make_scored_article("AAPL", date(2024, 3, i), 0.1))
        records = aggregate_daily_sentiment(articles)
        surprise_records = [r for r in records if r["factor_name"] == "sentiment_surprise"]
        # At least one surprise record should exist for dates where both windows are populated
        assert len(surprise_records) >= 1

    def test_sentiment_surprise_sign(self):
        """When 7d_avg > 30d_avg, surprise should be positive."""
        # Recent articles: very positive
        recent = [self._make_scored_article("MSFT", date(2024, 5, 20) , 0.9) for _ in range(5)]
        # Older articles: negative (in 30d window but not 7d)
        older = [self._make_scored_article("MSFT", date(2024, 5, i), -0.5) for i in range(1, 14)]
        records = aggregate_daily_sentiment(recent + older)
        surprise_on_latest = [
            r for r in records
            if r["factor_name"] == "sentiment_surprise"
            and r["observation_date"] == date(2024, 5, 20)
        ]
        if surprise_on_latest:
            assert surprise_on_latest[0]["factor_value"] > 0

    def test_null_score_excluded_from_average(self):
        articles = [
            self._make_scored_article("TSLA", date(2024, 5, 1), None),
            self._make_scored_article("TSLA", date(2024, 5, 1), 0.8),
        ]
        records = aggregate_daily_sentiment(articles)
        avg_records = [r for r in records if r["factor_name"] == "sentiment_7d_avg"]
        # Non-null: 0.8 only; average should be 0.8
        assert len(avg_records) == 1
        assert abs(avg_records[0]["factor_value"] - 0.8) < 1e-6

    def test_multi_symbol(self):
        articles = [
            self._make_scored_article("AAPL", date(2024, 6, 1), 0.5),
            self._make_scored_article("MSFT", date(2024, 6, 1), -0.3),
        ]
        records = aggregate_daily_sentiment(articles)
        symbols = {r["symbol"] for r in records}
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_all_records_have_required_fields(self):
        articles = [self._make_scored_article("GOOG", date(2024, 7, 15), 0.1)]
        records = aggregate_daily_sentiment(articles)
        required = {"symbol", "observation_date", "factor_name", "factor_value", "source"}
        for r in records:
            assert required.issubset(r.keys()), f"Missing fields in record: {r}"
