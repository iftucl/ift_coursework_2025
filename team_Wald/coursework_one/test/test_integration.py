"""
Integration and end-to-end tests for the Value + Sentiment pipeline.
These tests verify module interactions without requiring live services.
"""

from datetime import date

import pandas as pd
import pytest


@pytest.mark.integration
class TestPipelineIntegration:
    """Integration tests for cross-module data flow."""

    def test_extraction_to_cleaning(self):
        """Test that extraction output feeds into cleaning correctly."""
        from modules.processing.data_cleaner import clean_price_dataframe

        idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
        df = pd.DataFrame(
            {
                "Open": [150.0, 151.0],
                "High": [152.0, 153.0],
                "Low": [149.0, 150.0],
                "Close": [151.0, 152.0],
                "Adj Close": [150.5, 151.5],
                "Volume": [1e6, 1.1e6],
            },
            index=idx,
        )
        records = clean_price_dataframe(df, "AAPL", "USD")
        assert len(records) == 2
        assert all(r["symbol"] == "AAPL" for r in records)

    def test_info_to_value_scoring(self):
        """Test that company info flows into value scoring."""
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "A",
                "pe_ratio": 10.0,
                "pb_ratio": 1.0,
                "ev_ebitda": 5.0,
                "dividend_yield": 0.04,
                "debt_equity": 0.3,
            },
            {
                "symbol": "B",
                "pe_ratio": 30.0,
                "pb_ratio": 5.0,
                "ev_ebitda": 20.0,
                "dividend_yield": 0.01,
                "debt_equity": 1.5,
            },
        ]
        scores = compute_value_scores(infos, date(2025, 1, 1))
        assert len(scores) == 2
        # Company A should have higher value score (cheaper)
        a_score = next(s for s in scores if s["company_id"] == "A")
        b_score = next(s for s in scores if s["company_id"] == "B")
        assert a_score["value_score"] > b_score["value_score"]

    def test_articles_to_sentiment_scoring(self):
        """Test that articles flow into sentiment scoring."""
        from modules.processing.sentiment_scorer import compute_all_sentiment

        articles = {
            "GOOD": [{"headline": "Record profits and strong growth"}],
            "BAD": [{"headline": "Company faces bankruptcy and massive losses"}],
        }
        results = compute_all_sentiment(articles, date(2025, 1, 1))
        good = next(r for r in results if r["company_id"] == "GOOD")
        bad = next(r for r in results if r["company_id"] == "BAD")
        assert good["sentiment_score"] > bad["sentiment_score"]

    def test_full_scoring_pipeline(self):
        """Test value + sentiment → composite scoring pipeline."""
        from modules.processing.composite_scorer import compute_composite_scores
        from modules.processing.sentiment_scorer import compute_all_sentiment
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "WINNER",
                "pe_ratio": 8.0,
                "pb_ratio": 1.2,
                "ev_ebitda": 5.0,
                "dividend_yield": 0.04,
                "debt_equity": 0.3,
            },
            {
                "symbol": "LOSER",
                "pe_ratio": 50.0,
                "pb_ratio": 8.0,
                "ev_ebitda": 30.0,
                "dividend_yield": 0.001,
                "debt_equity": 1.8,
            },
        ]
        articles = {
            "WINNER": [{"headline": "Amazing revenue growth beats all expectations"}],
            "LOSER": [{"headline": "Stock crashes after terrible earnings miss"}],
        }

        values = compute_value_scores(infos, date(2025, 1, 1))
        sentiments = compute_all_sentiment(articles, date(2025, 1, 1))
        composites = compute_composite_scores(
            values, sentiments, max_debt_equity=999, min_avg_sentiment=-999, score_date=date(2025, 1, 1)
        )

        assert len(composites) == 2
        winner = next(r for r in composites if r["company_id"] == "WINNER")
        loser = next(r for r in composites if r["company_id"] == "LOSER")
        assert winner["rank"] < loser["rank"]
        assert winner["composite_score"] > loser["composite_score"]

    def test_fx_data_cleaning(self):
        """Test that FX data is properly cleaned."""
        from modules.processing.data_cleaner import clean_fx_dataframe

        idx = pd.to_datetime(["2024-01-02"])
        df = pd.DataFrame(
            {"Open": [1.265], "High": [1.270], "Low": [1.260], "Close": [1.268]},
            index=idx,
        )
        records = clean_fx_dataframe(df, "GBPUSD=X")
        assert len(records) == 1
        assert records[0]["currency_pair"] == "GBPUSD=X"

    def test_ticker_preparation_pipeline(self):
        """Test full ticker preparation chain."""
        from modules.extraction.company_loader import infer_currency, prepare_ticker

        raw = "NESN.S  "
        clean = prepare_ticker(raw)
        assert clean == "NESN.SW"
        currency = infer_currency(clean)
        assert currency == "CHF"
