"""
Tests for the sentiment_analyzer module — VADER-based news sentiment scoring.

Tests both the sentiment_analyzer wrapper interface and the underlying
sentiment_scorer implementation.
"""

import pytest

from modules.processing.sentiment_analyzer import (
    analyze_company_articles,
    analyze_single_article,
    compute_sentiment_score,
    process_all_companies,
)


class TestAnalyzeSingleArticle:
    """Tests for analyze_single_article function."""

    def test_positive_article(self):
        result = analyze_single_article("Apple reports record earnings and massive growth")
        assert result["compound"] > 0.05
        assert result["classification"] == "positive"
        assert "headline" in result

    def test_negative_article(self):
        result = analyze_single_article("Company faces bankruptcy and huge losses")
        assert result["compound"] < -0.05
        assert result["classification"] == "negative"

    def test_neutral_article(self):
        result = analyze_single_article("Company announces quarterly results")
        assert result["classification"] in ("neutral", "positive", "negative")

    def test_with_description(self):
        result = analyze_single_article(
            "Apple earnings beat expectations", "Revenue grew 20% year over year with strong demand"
        )
        assert result["compound"] > 0
        assert "positive" in result
        assert "negative" in result
        assert "neutral" in result

    def test_empty_headline(self):
        result = analyze_single_article("")
        assert "compound" in result


class TestComputeSentimentScore:
    """Tests for compute_sentiment_score function."""

    def test_perfect_positive(self):
        score = compute_sentiment_score(avg_sentiment=1.0, positive_ratio=1.0, article_count=20)
        # (1.0+1)/2*100*0.5 + 1.0*100*0.3 + 1.0*100*0.2 = 50 + 30 + 20 = 100
        assert score == pytest.approx(100.0, rel=0.01)

    def test_perfect_negative(self):
        score = compute_sentiment_score(avg_sentiment=-1.0, positive_ratio=0.0, article_count=20)
        # (-1+1)/2*100*0.5 + 0 + 1.0*100*0.2 = 0 + 0 + 20 = 20
        assert score == pytest.approx(20.0, rel=0.01)

    def test_neutral_sentiment(self):
        score = compute_sentiment_score(avg_sentiment=0.0, positive_ratio=0.5, article_count=10)
        # (0+1)/2*100*0.5 + 0.5*100*0.3 + 0.5*100*0.2 = 25 + 15 + 10 = 50
        assert score == pytest.approx(50.0, rel=0.01)

    def test_low_volume_penalty(self):
        score_low = compute_sentiment_score(avg_sentiment=0.5, positive_ratio=0.7, article_count=2)
        score_high = compute_sentiment_score(avg_sentiment=0.5, positive_ratio=0.7, article_count=20)
        assert score_high > score_low


class TestAnalyzeCompanyArticles:
    """Tests for analyze_company_articles function."""

    def test_positive_company(self):
        articles = [
            {"headline": "Record profits and amazing growth"},
            {"headline": "Revenue beats all expectations"},
        ]
        result = analyze_company_articles("AAPL", articles)
        assert "avg_sentiment" in result or "sentiment_score" in result
        assert result.get("company_id") == "AAPL" or "AAPL" in str(result)

    def test_empty_articles(self):
        result = analyze_company_articles("TEST", [])
        assert isinstance(result, dict)

    def test_mixed_sentiment(self):
        articles = [
            {"headline": "Great earnings beat expectations"},
            {"headline": "Terrible losses and bankruptcy fears"},
        ]
        result = analyze_company_articles("MIX", articles)
        assert isinstance(result, dict)


class TestProcessAllCompanies:
    """Tests for process_all_companies function."""

    def test_multiple_companies(self):
        from datetime import date

        all_articles = {
            "GOOD": [{"headline": "Amazing growth and profits"}],
            "BAD": [{"headline": "Devastating losses and decline"}],
        }
        results = process_all_companies(all_articles, date(2025, 3, 1))
        assert isinstance(results, list)
        assert len(results) >= 2

    def test_empty_input(self):
        results = process_all_companies({})
        assert isinstance(results, list)
        assert len(results) == 0
