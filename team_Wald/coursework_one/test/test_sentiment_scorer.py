"""
Tests for VADER sentiment scoring module.
"""

from datetime import date


class TestGetAnalyser:
    """Tests for VADER analyser initialisation."""

    def test_analyser_created(self):
        from modules.processing.sentiment_scorer import get_analyser

        a = get_analyser()
        assert a is not None

    def test_analyser_has_polarity(self):
        from modules.processing.sentiment_scorer import get_analyser

        a = get_analyser()
        assert hasattr(a, "polarity_scores")


class TestScoreHeadline:
    """Tests for individual headline scoring."""

    def test_positive_headline(self):
        from modules.processing.sentiment_scorer import get_analyser, score_headline

        a = get_analyser()
        result = score_headline(a, "Company reports excellent results and strong growth")
        assert result["compound"] > 0

    def test_negative_headline(self):
        from modules.processing.sentiment_scorer import get_analyser, score_headline

        a = get_analyser()
        result = score_headline(a, "Company faces massive lawsuit and regulatory crackdown")
        assert result["compound"] < 0

    def test_neutral_headline(self):
        from modules.processing.sentiment_scorer import get_analyser, score_headline

        a = get_analyser()
        result = score_headline(a, "Company schedules annual meeting for shareholders")
        assert -0.3 < result["compound"] < 0.3

    def test_empty_headline(self):
        from modules.processing.sentiment_scorer import get_analyser, score_headline

        a = get_analyser()
        result = score_headline(a, "")
        assert result["compound"] == 0.0

    def test_none_analyser(self):
        from modules.processing.sentiment_scorer import score_headline

        result = score_headline(None, "Some headline")
        assert result["compound"] == 0.0

    def test_score_keys(self):
        from modules.processing.sentiment_scorer import get_analyser, score_headline

        a = get_analyser()
        result = score_headline(a, "Test headline")
        assert "compound" in result
        assert "pos" in result
        assert "neg" in result
        assert "neu" in result


class TestScoreText:
    """Tests for general text scoring."""

    def test_score_text_positive(self):
        from modules.processing.sentiment_scorer import get_analyser, score_text

        a = get_analyser()
        result = score_text(a, "Incredible growth and record profits")
        assert result["compound"] > 0

    def test_score_text_empty(self):
        from modules.processing.sentiment_scorer import get_analyser, score_text

        a = get_analyser()
        result = score_text(a, "")
        assert result["compound"] == 0.0

    def test_score_text_none_analyser(self):
        from modules.processing.sentiment_scorer import score_text

        result = score_text(None, "Some text")
        assert result["compound"] == 0.0


class TestDeduplicateArticles:
    """Tests for article deduplication."""

    def test_removes_duplicates(self):
        from modules.processing.sentiment_scorer import deduplicate_articles

        articles = [
            {"headline": "Apple beats earnings"},
            {"headline": "Apple beats earnings"},
            {"headline": "Microsoft announces product"},
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 2

    def test_case_insensitive(self):
        from modules.processing.sentiment_scorer import deduplicate_articles

        articles = [
            {"headline": "Apple Beats Earnings"},
            {"headline": "apple beats earnings"},
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 1

    def test_keeps_empty_headlines(self):
        from modules.processing.sentiment_scorer import deduplicate_articles

        articles = [
            {"headline": ""},
            {"headline": ""},
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 2

    def test_no_duplicates(self):
        from modules.processing.sentiment_scorer import deduplicate_articles

        articles = [
            {"headline": "First headline"},
            {"headline": "Second headline"},
        ]
        result = deduplicate_articles(articles)
        assert len(result) == 2


class TestScoreArticles:
    """Tests for batch article scoring."""

    def test_articles_enriched(self, sample_articles):
        from modules.processing.sentiment_scorer import get_analyser, score_articles

        a = get_analyser()
        scored = score_articles(a, sample_articles)
        assert len(scored) == 3
        assert all("vader_compound" in art for art in scored)
        assert all("sentiment_class" in art for art in scored)

    def test_sentiment_classification(self):
        from modules.processing.sentiment_scorer import get_analyser, score_articles

        a = get_analyser()
        articles = [
            {"headline": "Stock price soars after amazing earnings report"},
            {"headline": "Company faces bankruptcy after scandal"},
            {"headline": "Annual shareholder meeting scheduled for Thursday"},
        ]
        scored = score_articles(a, articles)
        classes = [art["sentiment_class"] for art in scored]
        assert "positive" in classes
        assert "negative" in classes

    def test_description_included(self):
        from modules.processing.sentiment_scorer import get_analyser, score_articles

        a = get_analyser()
        articles = [
            {"headline": "Quarterly results", "description": "Company posts record revenue and strong earnings growth"},
        ]
        scored = score_articles(a, articles)
        assert scored[0]["vader_compound"] != 0.0

    def test_empty_articles(self):
        from modules.processing.sentiment_scorer import get_analyser, score_articles

        a = get_analyser()
        scored = score_articles(a, [])
        assert scored == []


class TestAggregateSentiment:
    """Tests for company-level sentiment aggregation."""

    def test_basic_aggregation(self, sample_articles):
        from modules.processing.sentiment_scorer import aggregate_sentiment, get_analyser, score_articles

        a = get_analyser()
        scored = score_articles(a, sample_articles)
        agg = aggregate_sentiment("AAPL", scored, date(2025, 1, 1))
        assert agg["company_id"] == "AAPL"
        assert agg["date"] == "2025-01-01"
        assert agg["total_articles"] == 3
        assert agg["sentiment_score"] is not None

    def test_sentiment_score_range(self, sample_articles):
        from modules.processing.sentiment_scorer import aggregate_sentiment, get_analyser, score_articles

        a = get_analyser()
        scored = score_articles(a, sample_articles)
        agg = aggregate_sentiment("AAPL", scored)
        assert 0 <= agg["sentiment_score"] <= 100

    def test_empty_articles_aggregation(self):
        from modules.processing.sentiment_scorer import aggregate_sentiment

        agg = aggregate_sentiment("AAPL", [])
        assert agg["total_articles"] == 0
        assert agg["sentiment_score"] is None
        assert agg["avg_sentiment"] is None

    def test_positive_ratio(self):
        from modules.processing.sentiment_scorer import aggregate_sentiment, get_analyser, score_articles

        a = get_analyser()
        articles = [
            {"headline": "Incredible growth and record profits"},
            {"headline": "Amazing breakthrough and strong sales"},
            {"headline": "Terrible losses and declining revenue"},
        ]
        scored = score_articles(a, articles)
        agg = aggregate_sentiment("TEST", scored)
        # 2 positive, 1 negative
        assert agg["positive_count"] >= 1
        assert agg["positive_ratio"] > 0

    def test_all_record_fields(self, sample_articles):
        from modules.processing.sentiment_scorer import aggregate_sentiment, get_analyser, score_articles

        a = get_analyser()
        scored = score_articles(a, sample_articles)
        agg = aggregate_sentiment("AAPL", scored)
        expected_keys = {
            "company_id",
            "date",
            "avg_sentiment",
            "positive_count",
            "negative_count",
            "neutral_count",
            "total_articles",
            "positive_ratio",
            "sentiment_score",
        }
        assert expected_keys == set(agg.keys())


class TestComputeAllSentiment:
    """Tests for universe-wide sentiment computation."""

    def test_multiple_companies(self):
        from modules.processing.sentiment_scorer import compute_all_sentiment

        articles = {
            "AAPL": [{"headline": "Apple posts record revenue"}],
            "MSFT": [{"headline": "Microsoft beats expectations"}],
        }
        results = compute_all_sentiment(articles, date(2025, 1, 1))
        assert len(results) == 2
        tickers = {r["company_id"] for r in results}
        assert tickers == {"AAPL", "MSFT"}

    def test_empty_articles_dict(self):
        from modules.processing.sentiment_scorer import compute_all_sentiment

        results = compute_all_sentiment({})
        assert results == []
