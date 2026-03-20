"""
Tests for NewsAPI news extraction module.
"""

from unittest.mock import MagicMock, patch


class TestFetchNewsNewsapi:
    """Tests for fetch_news_newsapi function."""

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_successful_fetch(self, mock_get):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "articles": [
                {
                    "title": "Apple reports strong earnings",
                    "description": "Revenue beats expectations",
                    "url": "http://test.com/article1",
                    "source": {"name": "Reuters"},
                    "publishedAt": "2025-01-15T10:00:00Z",
                    "author": "Jane Doe",
                }
            ]
        }
        mock_get.return_value = mock_response
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=1)
        assert len(articles) == 1
        assert articles[0]["company_id"] == "AAPL"
        assert articles[0]["headline"] == "Apple reports strong earnings"
        assert articles[0]["source"] == "newsapi"
        assert articles[0]["source_name"] == "Reuters"
        assert articles[0]["url"] == "http://test.com/article1"

    def test_no_api_key_returns_empty(self):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        with patch.dict("os.environ", {}, clear=True):
            articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key=None)
            assert articles == []

    @patch("modules.extraction.newsapi_extractor.os.environ", {"NEWSAPI_KEY": "env_key"})
    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_uses_env_api_key(self, mock_get):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"articles": []}
        mock_get.return_value = mock_response
        fetch_news_newsapi("Apple Inc", "AAPL", api_key=None, max_retries=1)
        # Verify API was called (env key was used)
        assert mock_get.called

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_401_returns_empty(self, mock_get):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="bad_key", max_retries=1)
        assert articles == []
        assert mock_get.call_count == 1  # No retries on 401

    @patch("modules.extraction.newsapi_extractor.time.sleep")
    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_429_rate_limit_retries(self, mock_get, mock_sleep):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"articles": [{"title": "After retry", "source": {"name": "BBC"}}]}
        mock_get.side_effect = [mock_429, mock_200]
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=2)
        assert len(articles) == 1
        assert articles[0]["headline"] == "After retry"

    @patch("modules.extraction.newsapi_extractor.time.sleep")
    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_500_server_error_retries(self, mock_get, mock_sleep):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_500 = MagicMock()
        mock_500.status_code = 500
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"articles": []}
        mock_get.side_effect = [mock_500, mock_200]
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=2)
        assert articles == []
        assert mock_get.call_count == 2

    @patch("modules.extraction.newsapi_extractor.time.sleep")
    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_timeout_retries(self, mock_get, mock_sleep):
        import requests

        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_get.side_effect = requests.exceptions.Timeout("Timeout")
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=2)
        assert articles == []
        assert mock_get.call_count == 2

    @patch("modules.extraction.newsapi_extractor.time.sleep")
    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_connection_error_retries(self, mock_get, mock_sleep):
        import requests

        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_get.side_effect = requests.exceptions.ConnectionError("Failed")
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=2)
        assert articles == []

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_parse_error_returns_empty(self, mock_get):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=1)
        assert articles == []

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_empty_articles_response(self, mock_get):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"articles": []}
        mock_get.return_value = mock_response
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=1)
        assert articles == []

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_multiple_articles(self, mock_get):
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "articles": [
                {
                    "title": "Article 1",
                    "description": "Desc 1",
                    "url": "http://a.com",
                    "source": {"name": "Reuters"},
                    "publishedAt": "2025-01-01T00:00:00Z",
                    "author": "Author A",
                },
                {
                    "title": "Article 2",
                    "description": "Desc 2",
                    "url": "http://b.com",
                    "source": {"name": "Bloomberg"},
                    "publishedAt": "2025-01-02T00:00:00Z",
                    "author": "Author B",
                },
                {
                    "title": "Article 3",
                    "description": None,
                    "url": "http://c.com",
                    "source": None,
                    "publishedAt": "2025-01-03T00:00:00Z",
                    "author": None,
                },
            ]
        }
        mock_get.return_value = mock_response
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=1)
        assert len(articles) == 3
        assert articles[0]["source_name"] == "Reuters"
        assert articles[1]["source_name"] == "Bloomberg"
        # None source handled gracefully
        assert articles[2]["source_name"] == ""
        assert articles[2]["description"] == ""

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_query_building_with_name(self, mock_get):
        """Test that company name is cleaned and used in query."""
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"articles": []}
        mock_get.return_value = mock_response
        fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=1)
        # Verify the query parameter was built correctly
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert "Apple" in params["q"]
        assert "AAPL" in params["q"]

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_query_building_with_suffix(self, mock_get):
        """Test that ticker dot-suffix is stripped in query."""
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"articles": []}
        mock_get.return_value = mock_response
        fetch_news_newsapi("Vodafone Group", "VOD.L", api_key="test_key", max_retries=1)
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert "VOD" in params["q"]
        assert ".L" not in params["q"]

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_page_size_capped_at_100(self, mock_get):
        """Test that page_size > 100 is capped to 100 (API limit)."""
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"articles": []}
        mock_get.return_value = mock_response
        fetch_news_newsapi(
            "Apple Inc",
            "AAPL",
            api_key="test_key",
            page_size=200,
            max_retries=1,
        )
        call_args = mock_get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["pageSize"] == 100

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_unexpected_http_status(self, mock_get):
        """Test handling of unexpected HTTP status codes (e.g. 403)."""
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_get.return_value = mock_response
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=1)
        assert articles == []

    @patch("modules.extraction.newsapi_extractor.time.sleep")
    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_max_retries_exhausted(self, mock_get, mock_sleep):
        """Test returns empty after exhausting all retries."""
        import requests

        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_get.side_effect = requests.exceptions.Timeout("Timeout")
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=3)
        assert articles == []
        assert mock_get.call_count == 3

    @patch("modules.extraction.newsapi_extractor.requests.get")
    def test_article_record_structure(self, mock_get):
        """Test that returned article dicts have all expected fields."""
        from modules.extraction.newsapi_extractor import fetch_news_newsapi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "articles": [
                {
                    "title": "Test",
                    "description": "Desc",
                    "url": "http://test.com",
                    "source": {"name": "Reuters"},
                    "publishedAt": "2025-01-01T00:00:00Z",
                    "author": "Author",
                }
            ]
        }
        mock_get.return_value = mock_response
        articles = fetch_news_newsapi("Apple Inc", "AAPL", api_key="test_key", max_retries=1)
        art = articles[0]
        expected_fields = [
            "company_id",
            "company_name",
            "headline",
            "description",
            "url",
            "source_name",
            "published_at",
            "author",
            "source",
        ]
        for field in expected_fields:
            assert field in art, f"Missing field: {field}"
        assert art["source"] == "newsapi"
        assert art["company_id"] == "AAPL"
        assert art["company_name"] == "Apple Inc"
