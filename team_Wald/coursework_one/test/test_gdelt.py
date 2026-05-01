"""
Tests for the GDELT news extraction module (modules/extraction/gdelt_extractor.py).

Tests API querying, response parsing, error handling, and batch extraction.
"""

from unittest.mock import MagicMock, patch

from modules.extraction.gdelt_extractor import fetch_all_companies_news, fetch_news_gdelt


class TestFetchNewsGdelt:
    """Tests for the fetch_news_gdelt function."""

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "articles": [
                {
                    "title": "Apple Revenue Beats Expectations",
                    "url": "https://example.com/1",
                    "source": {"name": "Reuters"},
                    "seendate": "20240115T120000Z",
                    "domain": "reuters.com",
                }
            ]
        }
        mock_get.return_value = mock_response
        result = fetch_news_gdelt("Apple Inc", "AAPL")
        assert isinstance(result, list)
        assert len(result) >= 1

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_empty_response(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"articles": []}
        mock_get.return_value = mock_response
        result = fetch_news_gdelt("NonexistentCompanyXYZ", "XYZ")
        assert isinstance(result, list)
        assert len(result) == 0

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_api_error_500(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Server Error")
        mock_get.return_value = mock_response
        result = fetch_news_gdelt("Apple Inc", "AAPL")
        assert isinstance(result, list)

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_timeout_handling(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
        result = fetch_news_gdelt("Apple Inc", "AAPL")
        assert isinstance(result, list)
        assert len(result) == 0

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_connection_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.exceptions.ConnectionError("DNS resolution failed")
        result = fetch_news_gdelt("Apple Inc", "AAPL")
        assert isinstance(result, list)
        assert len(result) == 0

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_json_parse_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response
        result = fetch_news_gdelt("Apple Inc", "AAPL")
        assert isinstance(result, list)


class TestFetchAllCompaniesNews:
    """Tests for batch GDELT extraction."""

    @patch("modules.extraction.gdelt_extractor.fetch_news_gdelt")
    def test_multiple_companies(self, mock_fetch):
        mock_fetch.return_value = [{"headline": "Test Article", "url": "https://example.com"}]
        companies = [
            {"company_id": "AAPL", "name": "Apple Inc", "ticker": "AAPL"},
            {"company_id": "MSFT", "name": "Microsoft Corp", "ticker": "MSFT"},
        ]
        result = fetch_all_companies_news(companies)
        assert isinstance(result, dict)

    @patch("modules.extraction.gdelt_extractor.fetch_news_gdelt")
    def test_empty_company_list(self, mock_fetch):
        result = fetch_all_companies_news([])
        assert isinstance(result, dict)
        assert len(result) == 0

    @patch("modules.extraction.gdelt_extractor.fetch_news_gdelt")
    def test_company_with_no_news(self, mock_fetch):
        mock_fetch.return_value = []
        companies = [{"company_id": "XYZ", "name": "Unknown Corp", "ticker": "XYZ"}]
        result = fetch_all_companies_news(companies)
        assert isinstance(result, dict)
