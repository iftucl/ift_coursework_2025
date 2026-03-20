"""
Tests for the MinIO uploader module (modules/loading/minio_uploader.py).

Tests upload functions for financial data, prices, news, company info,
and the convenience upload_all_raw_data function.
"""

from unittest.mock import MagicMock

import pandas as pd

from modules.loading.minio_uploader import (
    upload_all_raw_data,
    upload_company_info,
    upload_financial_data,
    upload_news_articles,
    upload_price_data,
)


class TestUploadFinancialData:
    """Tests for upload_financial_data function."""

    def test_upload_all_statements(self):
        mock_minio = MagicMock()
        data = {
            "income_statement": {"Net Income": {"2024": 1e8}},
            "balance_sheet": {"Total Assets": {"2024": 5e9}},
            "cash_flow": {"Operating Cash Flow": {"2024": 2e8}},
        }
        count = upload_financial_data(mock_minio, "AAPL", data, year="2024")
        assert count == 3
        assert mock_minio.upload_json.call_count == 3

    def test_upload_partial_statements(self):
        mock_minio = MagicMock()
        data = {"income_statement": {"Net Income": {"2024": 1e8}}}
        count = upload_financial_data(mock_minio, "MSFT", data)
        assert count == 1

    def test_upload_empty_statements(self):
        mock_minio = MagicMock()
        data = {"income_statement": None, "balance_sheet": {}, "cash_flow": None}
        count = upload_financial_data(mock_minio, "EMPTY", data)
        assert count == 0
        mock_minio.upload_json.assert_not_called()

    def test_upload_no_data(self):
        mock_minio = MagicMock()
        count = upload_financial_data(mock_minio, "NONE", {})
        assert count == 0

    def test_default_year(self):
        mock_minio = MagicMock()
        data = {"income_statement": {"data": True}}
        upload_financial_data(mock_minio, "AAPL", data)
        # Should use current year as default
        call_args = mock_minio.upload_json.call_args
        assert "financial/" in call_args.kwargs.get("category", call_args[1].get("category", ""))


class TestUploadPriceData:
    """Tests for upload_price_data function."""

    def test_upload_valid_prices(self):
        mock_minio = MagicMock()
        df = pd.DataFrame({"Close": [100.0, 101.0], "Volume": [1e6, 1.1e6]})
        upload_price_data(mock_minio, "AAPL", df, year="2024")
        mock_minio.upload_csv.assert_called_once()

    def test_skip_empty_dataframe(self):
        mock_minio = MagicMock()
        upload_price_data(mock_minio, "AAPL", pd.DataFrame())
        mock_minio.upload_csv.assert_not_called()

    def test_skip_none_dataframe(self):
        mock_minio = MagicMock()
        upload_price_data(mock_minio, "AAPL", None)
        mock_minio.upload_csv.assert_not_called()


class TestUploadNewsArticles:
    """Tests for upload_news_articles function."""

    def test_upload_articles(self):
        mock_minio = MagicMock()
        articles = [{"headline": "Test Article", "source": "Reuters"}]
        upload_news_articles(mock_minio, "AAPL", articles, date_str="2024-03-01")
        mock_minio.upload_json.assert_called_once()

    def test_skip_empty_articles(self):
        mock_minio = MagicMock()
        upload_news_articles(mock_minio, "AAPL", [])
        mock_minio.upload_json.assert_not_called()

    def test_skip_none_articles(self):
        mock_minio = MagicMock()
        upload_news_articles(mock_minio, "AAPL", None)
        mock_minio.upload_json.assert_not_called()

    def test_default_date(self):
        mock_minio = MagicMock()
        articles = [{"headline": "Test"}]
        upload_news_articles(mock_minio, "AAPL", articles)
        mock_minio.upload_json.assert_called_once()


class TestUploadCompanyInfo:
    """Tests for upload_company_info function."""

    def test_upload_info(self):
        mock_minio = MagicMock()
        info = {"pe_ratio": 28.0, "market_cap": 3e12}
        upload_company_info(mock_minio, "AAPL", info)
        mock_minio.upload_json.assert_called_once()

    def test_skip_empty_info(self):
        mock_minio = MagicMock()
        upload_company_info(mock_minio, "AAPL", {})
        mock_minio.upload_json.assert_not_called()

    def test_skip_none_info(self):
        mock_minio = MagicMock()
        upload_company_info(mock_minio, "AAPL", None)
        mock_minio.upload_json.assert_not_called()


class TestUploadAllRawData:
    """Tests for upload_all_raw_data convenience function."""

    def test_all_data_types(self):
        mock_minio = MagicMock()
        ticker_data = {
            "financials": {"income_statement": {"data": True}},
            "prices": pd.DataFrame({"Close": [100.0]}),
            "news": [{"headline": "Test"}],
            "info": {"pe_ratio": 28.0},
        }
        upload_all_raw_data(mock_minio, "AAPL", ticker_data)
        assert mock_minio.upload_json.call_count >= 2  # financials + news + info
        assert mock_minio.upload_csv.call_count == 1

    def test_only_prices(self):
        mock_minio = MagicMock()
        ticker_data = {"prices": pd.DataFrame({"Close": [100.0]})}
        upload_all_raw_data(mock_minio, "AAPL", ticker_data)
        mock_minio.upload_csv.assert_called_once()
        mock_minio.upload_json.assert_not_called()

    def test_only_info(self):
        mock_minio = MagicMock()
        ticker_data = {"info": {"market_cap": 3e12}}
        upload_all_raw_data(mock_minio, "MSFT", ticker_data)
        mock_minio.upload_json.assert_called_once()

    def test_empty_data(self):
        mock_minio = MagicMock()
        upload_all_raw_data(mock_minio, "EMPTY", {})
        mock_minio.upload_json.assert_not_called()
        mock_minio.upload_csv.assert_not_called()

    def test_none_financials_skipped(self):
        mock_minio = MagicMock()
        ticker_data = {"financials": None, "info": None, "news": [], "prices": None}
        upload_all_raw_data(mock_minio, "NONE", ticker_data)
        mock_minio.upload_json.assert_not_called()
        mock_minio.upload_csv.assert_not_called()

    def test_prices_wrong_type_skipped(self):
        mock_minio = MagicMock()
        ticker_data = {"prices": "not a dataframe"}
        upload_all_raw_data(mock_minio, "BAD", ticker_data)
        mock_minio.upload_csv.assert_not_called()
