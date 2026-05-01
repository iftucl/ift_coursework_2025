"""
Tests for composite factor scoring module.
"""

from datetime import date


class TestCompositeScoring:
    """Tests for compute_composite_scores."""

    def test_basic_composite(self, sample_value_records, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores(sample_value_records, sample_sentiment_records, score_date=date(2025, 1, 1))
        assert len(results) > 0
        assert all("composite_score" in r for r in results)

    def test_ranks_assigned(self, sample_value_records, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores(sample_value_records, sample_sentiment_records)
        ranks = [r["rank"] for r in results]
        assert ranks == sorted(ranks)
        assert ranks[0] == 1

    def test_invest_decision_top_quintile(self, sample_value_records, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores(sample_value_records, sample_sentiment_records, top_quintile=True)
        invest_count = sum(1 for r in results if r["invest_decision"])
        assert invest_count >= 1

    def test_debt_equity_filter(self, sample_value_records, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores(sample_value_records, sample_sentiment_records, max_debt_equity=2.0)
        company_ids = {r["company_id"] for r in results}
        # JPM has D/E = 2.5, should be filtered out
        assert "JPM" not in company_ids

    def test_sentiment_filter(self, sample_value_records, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores(sample_value_records, sample_sentiment_records, min_avg_sentiment=0.0)
        company_ids = {r["company_id"] for r in results}
        # JPM has avg_sentiment = -0.10, should be filtered
        assert "JPM" not in company_ids

    def test_custom_weights(self, sample_value_records, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        r1 = compute_composite_scores(
            sample_value_records,
            sample_sentiment_records,
            value_weight=1.0,
            sentiment_weight=0.0,
            max_debt_equity=999,
            min_avg_sentiment=-999,
        )
        r2 = compute_composite_scores(
            sample_value_records,
            sample_sentiment_records,
            value_weight=0.0,
            sentiment_weight=1.0,
            max_debt_equity=999,
            min_avg_sentiment=-999,
        )
        # With different weights, rankings should differ
        ranks1 = [r["company_id"] for r in r1]
        ranks2 = [r["company_id"] for r in r2]
        assert ranks1 != ranks2 or len(ranks1) <= 1

    def test_empty_inputs(self):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores([], [])
        assert results == []

    def test_value_only(self, sample_value_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores(sample_value_records, [], max_debt_equity=999)
        assert len(results) > 0

    def test_sentiment_only(self, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores([], sample_sentiment_records, min_avg_sentiment=-999)
        assert len(results) > 0

    def test_date_assignment(self, sample_value_records, sample_sentiment_records):
        from modules.processing.composite_scorer import compute_composite_scores

        results = compute_composite_scores(sample_value_records, sample_sentiment_records, score_date=date(2025, 6, 1))
        assert all(r["date"] == "2025-06-01" for r in results)


class TestWeightedComposite:
    """Tests for _weighted_composite helper."""

    def test_both_scores(self):
        from modules.processing.composite_scorer import _weighted_composite

        result = _weighted_composite(80.0, 60.0, 0.6, 0.4)
        assert abs(result - 72.0) < 0.01

    def test_value_only(self):
        from modules.processing.composite_scorer import _weighted_composite

        # With only value, score is scaled by value weight (0.6 * 80 = 48)
        result = _weighted_composite(80.0, None, 0.6, 0.4)
        assert result == 48.0

    def test_sentiment_only(self):
        from modules.processing.composite_scorer import _weighted_composite

        # With only sentiment, score is scaled by sentiment weight (0.4 * 60 = 24)
        result = _weighted_composite(None, 60.0, 0.6, 0.4)
        assert result == 24.0

    def test_neither_score(self):
        from modules.processing.composite_scorer import _weighted_composite

        result = _weighted_composite(None, None, 0.6, 0.4)
        assert result is None
