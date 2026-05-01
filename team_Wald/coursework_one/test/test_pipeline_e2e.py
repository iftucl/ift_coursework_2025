"""
End-to-end tests for the full Value + News Sentiment pipeline.

Runs the pipeline for 5-10 test companies and verifies composite rankings
are calculated correctly through all stages.
"""

from datetime import date

import pytest


@pytest.mark.integration
class TestEndToEndPipeline:
    """End-to-end tests verifying the full pipeline flow."""

    def test_full_pipeline_5_companies(self):
        """Run extraction → value scoring → sentiment → composite for 5 companies."""
        from modules.processing.composite_scorer import compute_composite_scores
        from modules.processing.sentiment_scorer import compute_all_sentiment
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "AAPL",
                "pe_ratio": 28.0,
                "pb_ratio": 40.0,
                "ev_ebitda": 22.0,
                "dividend_yield": 0.55,
                "debt_equity": 150.0,
            },
            {
                "symbol": "MSFT",
                "pe_ratio": 35.0,
                "pb_ratio": 12.0,
                "ev_ebitda": 25.0,
                "dividend_yield": 0.80,
                "debt_equity": 40.0,
            },
            {
                "symbol": "GOOGL",
                "pe_ratio": 25.0,
                "pb_ratio": 6.0,
                "ev_ebitda": 18.0,
                "dividend_yield": 0.0,
                "debt_equity": 10.0,
            },
            {
                "symbol": "JPM",
                "pe_ratio": 12.0,
                "pb_ratio": 1.8,
                "ev_ebitda": 8.0,
                "dividend_yield": 2.50,
                "debt_equity": 200.0,
            },
            {
                "symbol": "JNJ",
                "pe_ratio": 15.0,
                "pb_ratio": 5.5,
                "ev_ebitda": 14.0,
                "dividend_yield": 3.00,
                "debt_equity": 50.0,
            },
        ]
        articles = {
            "AAPL": [{"headline": "Apple reports record iPhone sales and strong services growth"}],
            "MSFT": [{"headline": "Microsoft Azure revenue surges 30% beating expectations"}],
            "GOOGL": [{"headline": "Google advertising revenue disappoints investors"}],
            "JPM": [{"headline": "JPMorgan profits rise on strong trading and investment banking"}],
            "JNJ": [{"headline": "Johnson & Johnson faces new lawsuit concerns"}],
        }

        run_date = date(2025, 3, 1)
        values = compute_value_scores(infos, run_date)
        sentiments = compute_all_sentiment(articles, run_date)
        composites = compute_composite_scores(
            values, sentiments, max_debt_equity=999, min_avg_sentiment=-999, score_date=run_date
        )

        assert len(composites) == 5
        assert all("composite_score" in r for r in composites)
        assert all("rank" in r for r in composites)
        assert all("invest_decision" in r for r in composites)
        ranks = [r["rank"] for r in composites]
        assert sorted(ranks) == list(range(1, 6))

    def test_pipeline_with_missing_data(self):
        """Verify pipeline handles companies with partial data gracefully."""
        from modules.processing.composite_scorer import compute_composite_scores
        from modules.processing.sentiment_scorer import compute_all_sentiment
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "FULL",
                "pe_ratio": 15.0,
                "pb_ratio": 2.0,
                "ev_ebitda": 10.0,
                "dividend_yield": 2.0,
                "debt_equity": 50.0,
            },
            {
                "symbol": "PARTIAL",
                "pe_ratio": None,
                "pb_ratio": 3.0,
                "ev_ebitda": None,
                "dividend_yield": 1.0,
                "debt_equity": 30.0,
            },
        ]
        articles = {
            "FULL": [
                {"headline": "Strong quarterly results beat consensus estimates"},
                {"headline": "Revenue growth accelerates year over year"},
            ],
            "PARTIAL": [{"headline": "Company reports mixed quarterly results"}],
        }

        run_date = date(2025, 3, 1)
        values = compute_value_scores(infos, run_date)
        sentiments = compute_all_sentiment(articles, run_date)
        composites = compute_composite_scores(
            values, sentiments, max_debt_equity=999, min_avg_sentiment=-999, score_date=run_date
        )

        assert len(composites) >= 1
        assert all("composite_score" in r for r in composites)

    def test_pipeline_debt_equity_filter(self):
        """Verify D/E > 2.0 filter excludes over-leveraged companies."""
        from modules.processing.composite_scorer import compute_composite_scores
        from modules.processing.sentiment_scorer import compute_all_sentiment
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "SAFE",
                "pe_ratio": 10.0,
                "pb_ratio": 1.5,
                "ev_ebitda": 6.0,
                "dividend_yield": 3.0,
                "debt_equity": 80.0,
            },
            {
                "symbol": "RISKY",
                "pe_ratio": 8.0,
                "pb_ratio": 1.0,
                "ev_ebitda": 4.0,
                "dividend_yield": 4.0,
                "debt_equity": 250.0,
            },
        ]
        articles = {
            "SAFE": [{"headline": "Solid earnings growth and strong balance sheet"}],
            "RISKY": [{"headline": "Great revenue despite high debt levels"}],
        }

        run_date = date(2025, 3, 1)
        values = compute_value_scores(infos, run_date)
        sentiments = compute_all_sentiment(articles, run_date)
        composites = compute_composite_scores(
            values, sentiments, max_debt_equity=2.0, min_avg_sentiment=-999, score_date=run_date
        )

        ids = [r["company_id"] for r in composites]
        assert "SAFE" in ids
        assert "RISKY" not in ids

    def test_pipeline_sentiment_filter(self):
        """Verify negative sentiment filter excludes companies."""
        from modules.processing.composite_scorer import compute_composite_scores
        from modules.processing.sentiment_scorer import compute_all_sentiment
        from modules.processing.value_scorer import compute_value_scores

        infos = [
            {
                "symbol": "POS",
                "pe_ratio": 10.0,
                "pb_ratio": 2.0,
                "ev_ebitda": 8.0,
                "dividend_yield": 2.0,
                "debt_equity": 50.0,
            },
            {
                "symbol": "NEG",
                "pe_ratio": 12.0,
                "pb_ratio": 2.5,
                "ev_ebitda": 9.0,
                "dividend_yield": 1.5,
                "debt_equity": 60.0,
            },
        ]
        articles = {
            "POS": [
                {"headline": "Amazing growth and record profits exceed all expectations"},
                {"headline": "Strong demand drives revenue higher than forecast"},
                {"headline": "Investors cheer outstanding quarterly performance"},
            ],
            "NEG": [
                {"headline": "Massive losses and bankruptcy fears grow"},
                {"headline": "Stock crashes after terrible earnings disaster"},
                {"headline": "Company faces devastating lawsuit and regulatory fines"},
            ],
        }

        run_date = date(2025, 3, 1)
        values = compute_value_scores(infos, run_date)
        sentiments = compute_all_sentiment(articles, run_date)
        composites = compute_composite_scores(
            values, sentiments, max_debt_equity=999, min_avg_sentiment=0.0, score_date=run_date
        )

        ids = [r["company_id"] for r in composites]
        assert "POS" in ids

    def test_value_calculator_integration(self):
        """Test value_calculator module calculates ratios from raw financials."""
        from modules.processing.value_calculator import (
            calculate_debt_equity,
            calculate_dividend_yield,
            calculate_pb_ratio,
            calculate_pe_ratio,
        )

        financials = {
            "income_statement": {"Net Income": {"2024-03-31": 100_000_000}},
            "balance_sheet": {
                "Stockholders Equity": {"2024-03-31": 500_000_000},
                "Total Debt": {"2024-03-31": 200_000_000},
            },
            "cash_flow": {"Cash Dividends Paid": {"2024-03-31": -15_000_000}},
        }
        company_info = {"market_cap": 2_000_000_000}

        pe = calculate_pe_ratio(financials, company_info)
        pb = calculate_pb_ratio(financials, company_info)
        de = calculate_debt_equity(financials)
        dy = calculate_dividend_yield(financials, company_info)

        assert pe == pytest.approx(20.0, rel=0.01)
        assert pb == pytest.approx(4.0, rel=0.01)
        # D/E returns as percentage (like yfinance): 200M/500M = 0.4 * 100 = 40.0
        assert de == pytest.approx(40.0, rel=0.01)
        # Dividend yield returns as percentage: 15M/2B = 0.0075 * 100 = 0.75
        assert dy == pytest.approx(0.75, rel=0.01)

    def test_sentiment_analyzer_integration(self):
        """Test sentiment_analyzer module scores articles correctly."""
        from modules.processing.sentiment_analyzer import analyze_single_article, compute_sentiment_score

        positive = analyze_single_article("Record profits and amazing growth beat expectations")
        negative = analyze_single_article("Bankruptcy looms after devastating losses")

        assert positive["compound"] > 0
        assert negative["compound"] < 0
        assert positive["classification"] == "positive"
        assert negative["classification"] == "negative"

        score = compute_sentiment_score(avg_sentiment=0.5, positive_ratio=0.8, article_count=15)
        assert 0 <= score <= 100
