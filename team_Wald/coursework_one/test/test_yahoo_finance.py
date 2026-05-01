"""
Tests for the Yahoo Finance extraction module (modules/extraction/yahoo_finance_extractor.py).

Tests data fetching for a known company (e.g. AAPL) with mocked yfinance responses.
"""

from unittest.mock import patch

import pandas as pd

from modules.extraction.yahoo_finance_extractor import (
    fetch_company_info,
    fetch_financial_data,
    fetch_news,
    fetch_price_history,
)


class TestFetchPriceHistory:
    """Tests for fetch_price_history function."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_successful_fetch(self, mock_ticker_cls):
        idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
        df = pd.DataFrame(
            {
                "Open": [150.0, 151.0],
                "High": [152.0, 153.0],
                "Low": [149.0, 150.0],
                "Close": [151.0, 152.0],
                "Volume": [1_000_000, 1_100_000],
            },
            index=idx,
        )
        mock_ticker_cls.return_value.history.return_value = df
        result = fetch_price_history("AAPL", "2024-01-01", "2024-01-04")
        assert not result.empty
        assert len(result) == 2

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_empty_result(self, mock_ticker_cls):
        mock_ticker_cls.return_value.history.return_value = pd.DataFrame()
        result = fetch_price_history("INVALID", "2024-01-01", "2024-12-31")
        assert result.empty

    @patch("modules.extraction.yahoo_finance_extractor.yf.download")
    def test_exception_returns_empty(self, mock_download):
        mock_download.side_effect = Exception("API error")
        result = fetch_price_history("AAPL", "2024-01-01", "2024-12-31")
        assert result.empty


class TestFetchCompanyInfo:
    """Tests for fetch_company_info function."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_successful_info(self, mock_ticker_cls):
        mock_ticker_cls.return_value.info = {
            "trailingPE": 28.5,
            "priceToBook": 40.0,
            "enterpriseToEbitda": 22.3,
            "dividendYield": 0.0055,
            "debtToEquity": 150.0,
            "marketCap": 3_000_000_000_000,
            "sector": "Technology",
        }
        result = fetch_company_info("AAPL")
        assert result is not None
        assert "pe_ratio" in result or "trailingPE" in result or len(result) > 0

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_info_failure(self, mock_ticker_cls):
        mock_ticker_cls.return_value.info = {}
        result = fetch_company_info("INVALID")
        assert isinstance(result, dict)


class TestFetchFinancialData:
    """Tests for fetch_financial_data function."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_successful_financial_data(self, mock_ticker_cls):
        mock_ticker = mock_ticker_cls.return_value
        mock_ticker.quarterly_income_stmt = pd.DataFrame({"col": [1]})
        mock_ticker.quarterly_balance_sheet = pd.DataFrame({"col": [2]})
        mock_ticker.quarterly_cashflow = pd.DataFrame({"col": [3]})
        result = fetch_financial_data("AAPL")
        assert isinstance(result, dict)

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_empty_financial_data(self, mock_ticker_cls):
        mock_ticker = mock_ticker_cls.return_value
        mock_ticker.quarterly_income_stmt = pd.DataFrame()
        mock_ticker.quarterly_balance_sheet = pd.DataFrame()
        mock_ticker.quarterly_cashflow = pd.DataFrame()
        result = fetch_financial_data("INVALID")
        assert isinstance(result, dict)

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_exception_returns_dict(self, mock_ticker_cls):
        mock_ticker_cls.return_value.quarterly_income_stmt = None
        mock_ticker_cls.return_value.quarterly_balance_sheet = None
        mock_ticker_cls.return_value.quarterly_cashflow = None
        result = fetch_financial_data("AAPL")
        assert isinstance(result, dict)


class TestFetchNews:
    """Tests for fetch_news function."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_news_returned(self, mock_ticker_cls):
        mock_ticker_cls.return_value.news = [
            {
                "title": "Apple Reports Record Q4",
                "link": "https://example.com/1",
                "publisher": "Reuters",
                "providerPublishTime": 1700000000,
            }
        ]
        result = fetch_news("AAPL")
        assert isinstance(result, list)

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_no_news(self, mock_ticker_cls):
        mock_ticker_cls.return_value.news = []
        result = fetch_news("AAPL")
        assert isinstance(result, list)
        assert len(result) == 0

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_news_exception(self, mock_ticker_cls):
        mock_ticker_cls.return_value.news = None
        result = fetch_news("AAPL")
        assert isinstance(result, list)
