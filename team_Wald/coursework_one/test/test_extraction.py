"""
Tests for extraction modules (company_loader, yahoo_finance, gdelt).
"""

from unittest.mock import MagicMock, patch

import pandas as pd


class TestPrepareTicker:
    """Tests for ticker preparation and cleaning."""

    def test_strip_whitespace(self):
        from modules.extraction.company_loader import prepare_ticker

        assert prepare_ticker("AAPL  ") == "AAPL"

    def test_swiss_remap(self):
        from modules.extraction.company_loader import prepare_ticker

        assert prepare_ticker("NESN.S") == "NESN.SW"

    def test_swiss_remap_disabled(self):
        from modules.extraction.company_loader import prepare_ticker

        assert prepare_ticker("NESN.S", swiss_remap=False) == "NESN.S"

    def test_london_no_remap(self):
        from modules.extraction.company_loader import prepare_ticker

        assert prepare_ticker("VOD.L") == "VOD.L"

    def test_us_ticker_unchanged(self):
        from modules.extraction.company_loader import prepare_ticker

        assert prepare_ticker("AAPL") == "AAPL"

    def test_b_share_class_remap(self):
        from modules.extraction.company_loader import prepare_ticker

        assert prepare_ticker("BRK.B") == "BRK-B"


class TestInferCurrency:
    """Tests for currency inference from ticker suffix."""

    def test_us_default(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("AAPL") == "USD"

    def test_london(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("VOD.L") == "GBP"

    def test_paris(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("BNP.PA") == "EUR"

    def test_toronto(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("RY.TO") == "CAD"

    def test_swiss_remapped(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("NESN.SW") == "CHF"

    def test_amsterdam(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("ASML.AS") == "EUR"

    def test_frankfurt(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("SAP.DE") == "EUR"

    def test_custom_map(self):
        from modules.extraction.company_loader import infer_currency

        assert infer_currency("TEST.HK", {".HK": "HKD"}) == "HKD"


class TestDetectInactiveTickers:
    """Tests for detect_inactive_tickers with mocked yfinance."""

    @patch("yfinance.Ticker")
    def test_active_ticker(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        mock_ticker = MagicMock()
        mock_fi = MagicMock()
        mock_fi.last_price = 150.0
        mock_ticker.fast_info = mock_fi
        mock_ticker_cls.return_value = mock_ticker

        inactive = detect_inactive_tickers(["AAPL"], max_workers=1)
        assert len(inactive) == 0

    @patch("yfinance.Ticker")
    def test_inactive_ticker_no_price(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        mock_ticker = MagicMock()
        mock_fi = MagicMock()
        mock_fi.last_price = None
        mock_fi.regular_market_previous_close = None
        mock_ticker.fast_info = mock_fi
        mock_ticker_cls.return_value = mock_ticker

        inactive = detect_inactive_tickers(["DELISTED"], max_workers=1)
        assert "DELISTED" in inactive

    @patch("yfinance.Ticker")
    def test_inactive_ticker_zero_price(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        mock_ticker = MagicMock()
        mock_fi = MagicMock()
        mock_fi.last_price = 0
        mock_fi.regular_market_previous_close = 0
        mock_ticker.fast_info = mock_fi
        mock_ticker_cls.return_value = mock_ticker

        inactive = detect_inactive_tickers(["DEAD"], max_workers=1)
        assert "DEAD" in inactive

    @patch("yfinance.Ticker")
    def test_rate_limited_ticker_assumed_active(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        mock_ticker_cls.side_effect = Exception("401 Unauthorized")

        inactive = detect_inactive_tickers(["AAPL"], max_workers=1)
        assert "AAPL" not in inactive

    @patch("yfinance.Ticker")
    def test_timeout_error_assumed_active(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        mock_ticker_cls.side_effect = Exception("connection timeout")

        inactive = detect_inactive_tickers(["AAPL"], max_workers=1)
        assert "AAPL" not in inactive

    @patch("yfinance.Ticker")
    def test_genuine_error_marks_inactive(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        mock_ticker_cls.side_effect = Exception("No data found")

        inactive = detect_inactive_tickers(["GONE"], max_workers=1)
        assert "GONE" in inactive

    @patch("yfinance.Ticker")
    def test_mixed_tickers(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        def _make_ticker(symbol):
            mock_t = MagicMock()
            if symbol == "ACTIVE":
                mock_fi = MagicMock()
                mock_fi.last_price = 100.0
                mock_t.fast_info = mock_fi
            else:
                mock_fi = MagicMock()
                mock_fi.last_price = None
                mock_fi.regular_market_previous_close = None
                mock_t.fast_info = mock_fi
            return mock_t

        mock_ticker_cls.side_effect = _make_ticker

        inactive = detect_inactive_tickers(["ACTIVE", "DEAD"], max_workers=1)
        assert "ACTIVE" not in inactive
        assert "DEAD" in inactive

    @patch("yfinance.Ticker")
    def test_fallback_to_previous_close(self, mock_ticker_cls):
        from modules.extraction.company_loader import detect_inactive_tickers

        mock_ticker = MagicMock()
        mock_fi = MagicMock()
        mock_fi.last_price = None
        mock_fi.regular_market_previous_close = 50.0
        mock_ticker.fast_info = mock_fi
        mock_ticker_cls.return_value = mock_ticker

        inactive = detect_inactive_tickers(["AAPL"], max_workers=1)
        assert len(inactive) == 0

    @patch("yfinance.Ticker")
    def test_rate_limited_retry(self, mock_ticker_cls):
        """Rate-limited tickers are retried sequentially."""
        from modules.extraction.company_loader import detect_inactive_tickers

        # First call: rate limited (403), retry: active
        call_count = {"n": 0}

        def _side_effect(symbol):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("403 Forbidden")
            mock_t = MagicMock()
            mock_fi = MagicMock()
            mock_fi.last_price = 100.0
            mock_t.fast_info = mock_fi
            return mock_t

        mock_ticker_cls.side_effect = _side_effect

        with patch("time.sleep"):
            inactive = detect_inactive_tickers(["AAPL"], max_workers=1)
        assert "AAPL" not in inactive


class TestPartitionTickers:
    """Tests for partition_tickers with mocked detect_inactive_tickers."""

    @patch("modules.extraction.company_loader.detect_inactive_tickers")
    def test_all_active(self, mock_detect):
        from modules.extraction.company_loader import partition_tickers

        mock_detect.return_value = set()
        active, delisted = partition_tickers(["AAPL", "MSFT"])
        assert active == ["AAPL", "MSFT"]
        assert delisted == []

    @patch("modules.extraction.company_loader.detect_inactive_tickers")
    def test_some_delisted(self, mock_detect):
        from modules.extraction.company_loader import partition_tickers

        mock_detect.return_value = {"GONE"}
        active, delisted = partition_tickers(["AAPL", "GONE", "MSFT"])
        assert active == ["AAPL", "MSFT"]
        assert delisted == ["GONE"]

    @patch("modules.extraction.company_loader.detect_inactive_tickers")
    def test_all_delisted(self, mock_detect):
        from modules.extraction.company_loader import partition_tickers

        mock_detect.return_value = {"A", "B"}
        active, delisted = partition_tickers(["A", "B"])
        assert active == []
        assert delisted == ["A", "B"]


class TestLoadCompanies:
    """Tests for load_companies and get_ticker_list with mocked DB."""

    @patch("modules.extraction.company_loader.get_db_client")
    def test_load_companies_success(self, mock_get_db):
        from modules.extraction.company_loader import load_companies

        mock_client = MagicMock()
        mock_client.execute_query_df.return_value = pd.DataFrame(
            {
                "symbol": ["AAPL ", "MSFT ", "VOD.L "],
                "security": ["Apple Inc", "Microsoft Corp", "Vodafone Group"],
                "gics_sector": ["Technology", "Technology", "Communication"],
                "gics_industry": ["Hardware", "Software", "Telecom"],
                "country": ["US", "US", "UK"],
                "region": ["North America", "North America", "Europe"],
            }
        )
        mock_get_db.return_value = mock_client
        df = load_companies({"Host": "localhost"})
        assert len(df) == 3
        assert df["symbol"].iloc[0] == "AAPL"  # whitespace stripped
        mock_client.close.assert_called_once()

    @patch("modules.extraction.company_loader.get_db_client")
    def test_get_ticker_list(self, mock_get_db):
        from modules.extraction.company_loader import get_ticker_list

        mock_client = MagicMock()
        mock_client.execute_query_df.return_value = pd.DataFrame(
            {
                "symbol": ["AAPL ", "MSFT "],
                "security": ["Apple Inc", "Microsoft Corp"],
                "gics_sector": ["Tech", "Tech"],
                "gics_industry": ["HW", "SW"],
                "country": ["US", "US"],
                "region": ["NA", "NA"],
            }
        )
        mock_get_db.return_value = mock_client
        tickers = get_ticker_list({"Host": "localhost"})
        assert len(tickers) == 2
        assert "AAPL" in tickers


class TestFetchPriceHistory:
    """Tests for Yahoo Finance price fetcher with mocked API."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.download")
    def test_successful_fetch(self, mock_download):
        from modules.extraction.yahoo_finance_extractor import fetch_price_history

        idx = pd.to_datetime(["2024-01-02"])
        mock_download.return_value = pd.DataFrame(
            {"Close": [150.0], "Open": [149.0], "High": [151.0], "Low": [148.0], "Volume": [1000000]},
            index=idx,
        )
        df = fetch_price_history("AAPL", "2024-01-01", "2024-01-03", max_retries=1)
        assert not df.empty
        assert "Close" in df.columns

    @patch("modules.extraction.yahoo_finance_extractor.yf.download")
    def test_empty_result(self, mock_download):
        from modules.extraction.yahoo_finance_extractor import fetch_price_history

        mock_download.return_value = pd.DataFrame()
        df = fetch_price_history("INVALID", "2024-01-01", "2024-01-03", max_retries=1)
        assert df.empty

    @patch("modules.extraction.yahoo_finance_extractor.yf.download")
    def test_exception_returns_empty(self, mock_download):
        from modules.extraction.yahoo_finance_extractor import fetch_price_history

        mock_download.side_effect = Exception("API Error")
        df = fetch_price_history("AAPL", "2024-01-01", "2024-01-03", max_retries=1)
        assert df.empty


class TestFetchCompanyInfo:
    """Tests for company info fetcher."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_successful_info(self, mock_ticker_cls):
        from modules.extraction.yahoo_finance_extractor import fetch_company_info

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "trailingPE": 28.5,
            "priceToBook": 40.1,
            "enterpriseToEbitda": 22.0,
            "dividendYield": 0.005,
            "debtToEquity": 150.0,
            "marketCap": 3000000000000,
        }
        mock_ticker_cls.return_value = mock_ticker
        result = fetch_company_info("AAPL", max_retries=1)
        assert result["pe_ratio"] == 28.5
        assert result["pb_ratio"] == 40.1
        assert result["symbol"] == "AAPL"

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_info_failure(self, mock_ticker_cls):
        from modules.extraction.yahoo_finance_extractor import fetch_company_info

        mock_ticker_cls.side_effect = Exception("Timeout")
        result = fetch_company_info("BAD", max_retries=1)
        assert result == {}


class TestFetchFinancialData:
    """Tests for Yahoo Finance financial data fetcher."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_fetch_financial_data_success(self, mock_ticker_cls):
        from modules.extraction.yahoo_finance_extractor import fetch_financial_data

        mock_ticker = MagicMock()
        mock_ticker.quarterly_financials = pd.DataFrame({"Revenue": [1e9]})
        mock_ticker.quarterly_balance_sheet = pd.DataFrame({"TotalAssets": [5e9]})
        mock_ticker.quarterly_cashflow = pd.DataFrame({"OperatingCashflow": [2e8]})
        mock_ticker_cls.return_value = mock_ticker
        result = fetch_financial_data("AAPL", max_retries=1)
        assert "income_statement" in result
        assert "balance_sheet" in result
        assert "cash_flow" in result

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_fetch_financial_data_empty(self, mock_ticker_cls):
        """Test fetch_financial_data when all statements are empty."""
        from modules.extraction.yahoo_finance_extractor import fetch_financial_data

        mock_ticker = MagicMock()
        mock_ticker.quarterly_financials = pd.DataFrame()
        mock_ticker.quarterly_balance_sheet = pd.DataFrame()
        mock_ticker.quarterly_cashflow = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker
        result = fetch_financial_data("AAPL", max_retries=1)
        assert result == {}

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_fetch_financial_data_exception(self, mock_ticker_cls):
        """Test fetch_financial_data handles exceptions with retry."""
        from modules.extraction.yahoo_finance_extractor import fetch_financial_data

        mock_ticker_cls.side_effect = Exception("API Error")
        result = fetch_financial_data("AAPL", max_retries=1)
        assert result == {}

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_fetch_financial_data_none_dataframes(self, mock_ticker_cls):
        """Test fetch_financial_data when yfinance returns None dataframes."""
        from modules.extraction.yahoo_finance_extractor import fetch_financial_data

        mock_ticker = MagicMock()
        mock_ticker.quarterly_financials = None
        mock_ticker.quarterly_balance_sheet = None
        mock_ticker.quarterly_cashflow = None
        mock_ticker_cls.return_value = mock_ticker
        result = fetch_financial_data("AAPL", max_retries=1)
        assert result == {}


class TestFetchNews:
    """Tests for Yahoo Finance news fetcher."""

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_news_returned(self, mock_ticker_cls):
        from modules.extraction.yahoo_finance_extractor import fetch_news

        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                "id": "abc123",
                "content": {
                    "title": "Test headline",
                    "provider": {"displayName": "Reuters"},
                    "clickThroughUrl": {"url": "http://test.com"},
                    "pubDate": "2024-01-01T00:00:00Z",
                },
            }
        ]
        mock_ticker_cls.return_value = mock_ticker
        articles = fetch_news("AAPL", max_retries=1)
        assert len(articles) == 1
        assert articles[0]["headline"] == "Test headline"

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_no_news(self, mock_ticker_cls):
        from modules.extraction.yahoo_finance_extractor import fetch_news

        mock_ticker = MagicMock()
        mock_ticker.news = []
        mock_ticker_cls.return_value = mock_ticker
        articles = fetch_news("AAPL", max_retries=1)
        assert articles == []

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_news_exception_returns_empty(self, mock_ticker_cls):
        """Test fetch_news returns empty list on exception after retries."""
        from modules.extraction.yahoo_finance_extractor import fetch_news

        mock_ticker_cls.side_effect = Exception("API Timeout")
        articles = fetch_news("AAPL", max_retries=1)
        assert articles == []

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_news_none_returns_empty(self, mock_ticker_cls):
        """Test fetch_news handles None news gracefully."""
        from modules.extraction.yahoo_finance_extractor import fetch_news

        mock_ticker = MagicMock()
        mock_ticker.news = None
        mock_ticker_cls.return_value = mock_ticker
        articles = fetch_news("AAPL", max_retries=1)
        assert articles == []

    @patch("modules.extraction.yahoo_finance_extractor.yf.Ticker")
    def test_news_multiple_articles(self, mock_ticker_cls):
        """Test fetch_news processes multiple articles correctly."""
        from modules.extraction.yahoo_finance_extractor import fetch_news

        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                "id": "1",
                "content": {
                    "title": "Article 1",
                    "provider": {"displayName": "Reuters"},
                    "clickThroughUrl": {"url": "http://a.com"},
                    "pubDate": "2024-01-01T00:00:00Z",
                },
            },
            {
                "id": "2",
                "content": {
                    "title": "Article 2",
                    "provider": {"displayName": "Bloomberg"},
                    "clickThroughUrl": {"url": "http://b.com"},
                    "pubDate": "2024-01-02T00:00:00Z",
                },
            },
        ]
        mock_ticker_cls.return_value = mock_ticker
        articles = fetch_news("AAPL", max_retries=1)
        assert len(articles) == 2
        assert articles[0]["source"] == "yahoo_finance"
        assert articles[1]["publisher"] == "Bloomberg"
        assert articles[0]["company_id"] == "AAPL"


class TestDfToSerialisable:
    """Tests for _df_to_serialisable helper function."""

    def test_none_input(self):
        from modules.extraction.yahoo_finance_extractor import _df_to_serialisable

        assert _df_to_serialisable(None) == {}

    def test_empty_dataframe(self):
        from modules.extraction.yahoo_finance_extractor import _df_to_serialisable

        assert _df_to_serialisable(pd.DataFrame()) == {}

    def test_valid_dataframe(self):
        """Test with a financial statement-style DataFrame (field names as index, dates as columns)."""
        from modules.extraction.yahoo_finance_extractor import _df_to_serialisable

        # yfinance financial statements: rows=field names, columns=dates
        df = pd.DataFrame(
            {"2024-09-30": [1e9, 1e8], "2024-06-30": [2e9, 2e8]},
            index=["Total Revenue", "Net Income"],
        )
        result = _df_to_serialisable(df)
        assert isinstance(result, dict)
        # Outer keys should be field names (index), inner keys are dates (columns)
        assert "Total Revenue" in result
        assert "Net Income" in result
        assert "2024-09-30" in result["Total Revenue"]
        assert result["Total Revenue"]["2024-09-30"] == 1e9
        assert result["Net Income"]["2024-06-30"] == 2e8

    def test_non_serialisable_dataframe(self):
        """Test _df_to_serialisable with a mock that raises on to_dict."""
        from modules.extraction.yahoo_finance_extractor import _df_to_serialisable

        mock_df = MagicMock()
        mock_df.empty = False
        mock_df.to_dict.side_effect = Exception("Cannot serialize")
        result = _df_to_serialisable(mock_df)
        assert result == {}


class TestFetchAllCompanies:
    """Tests for batch Yahoo Finance extraction."""

    @patch("modules.extraction.yahoo_finance_extractor.time.sleep")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_news")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_financial_data")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_company_info")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_price_history")
    def test_fetch_all_companies_success(self, mock_prices, mock_info, mock_financials, mock_news, mock_sleep):
        from modules.extraction.yahoo_finance_extractor import fetch_all_companies

        mock_prices.return_value = pd.DataFrame({"Close": [150.0]})
        mock_info.return_value = {"symbol": "AAPL", "pe_ratio": 28.5}
        mock_financials.return_value = {"income_statement": {}}
        mock_news.return_value = [{"headline": "Test"}]
        result = fetch_all_companies(
            ["AAPL", "MSFT"],
            "2024-01-01",
            "2024-12-31",
            batch_size=50,
            delay=0.0,
            max_retries=1,
        )
        assert "AAPL" in result
        assert "MSFT" in result
        assert "prices" in result["AAPL"]
        assert "news" in result["AAPL"]

    @patch("modules.extraction.yahoo_finance_extractor.time.sleep")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_news")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_financial_data")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_company_info")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_price_history")
    def test_fetch_all_companies_with_batching(self, mock_prices, mock_info, mock_financials, mock_news, mock_sleep):
        """Test fetch_all_companies processes batches with delays."""
        from modules.extraction.yahoo_finance_extractor import fetch_all_companies

        mock_prices.return_value = pd.DataFrame({"Close": [100.0]})
        mock_info.return_value = {"symbol": "X"}
        mock_financials.return_value = {}
        mock_news.return_value = []
        # Create enough tickers to trigger batch boundaries
        tickers = ["T1", "T2", "T3"]
        result = fetch_all_companies(
            tickers,
            "2024-01-01",
            "2024-12-31",
            batch_size=2,
            delay=0.0,
            max_retries=1,
        )
        assert len(result) == 3

    @patch("modules.extraction.yahoo_finance_extractor.time.sleep")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_price_history")
    def test_fetch_all_companies_unhandled_error(self, mock_prices, mock_sleep):
        """Test fetch_all_companies handles unhandled exception per ticker."""
        from modules.extraction.yahoo_finance_extractor import fetch_all_companies

        mock_prices.side_effect = Exception("Unexpected error")
        result = fetch_all_companies(
            ["AAPL"],
            "2024-01-01",
            "2024-12-31",
            batch_size=50,
            delay=0.0,
            max_retries=1,
            sources=["prices"],
        )
        assert "AAPL" in result
        assert "error" in result["AAPL"]

    @patch("modules.extraction.yahoo_finance_extractor.time.sleep")
    @patch("modules.extraction.yahoo_finance_extractor.fetch_news")
    def test_fetch_all_companies_news_only(self, mock_news, mock_sleep):
        """Test fetch_all_companies with only news source."""
        from modules.extraction.yahoo_finance_extractor import fetch_all_companies

        mock_news.return_value = [{"headline": "News"}]
        result = fetch_all_companies(
            ["AAPL"],
            "2024-01-01",
            "2024-12-31",
            batch_size=50,
            delay=0.0,
            max_retries=1,
            sources=["news"],
        )
        assert "AAPL" in result
        assert "news" in result["AAPL"]


class TestGdeltExtractor:
    """Tests for GDELT news extraction."""

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_successful_fetch(self, mock_get):
        from modules.extraction.gdelt_extractor import fetch_news_gdelt

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "articles": [
                {
                    "title": "Apple news",
                    "url": "http://test.com",
                    "domain": "reuters.com",
                    "seendate": "20250101",
                    "tone": 2.5,
                }
            ]
        }
        mock_get.return_value = mock_response
        articles = fetch_news_gdelt("Apple Inc", "AAPL", max_retries=1)
        assert len(articles) == 1
        assert articles[0]["company_id"] == "AAPL"
        assert articles[0]["source"] == "gdelt"

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_api_error(self, mock_get):
        from modules.extraction.gdelt_extractor import fetch_news_gdelt

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response
        articles = fetch_news_gdelt("Apple Inc", "AAPL", max_retries=1)
        assert articles == []

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_timeout(self, mock_get):
        import requests

        from modules.extraction.gdelt_extractor import fetch_news_gdelt

        mock_get.side_effect = requests.exceptions.Timeout("Timeout")
        articles = fetch_news_gdelt("Apple Inc", "AAPL", max_retries=1)
        assert articles == []

    @patch("modules.extraction.gdelt_extractor.time.sleep")
    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_rate_limit_429(self, mock_get, mock_sleep):
        """Test GDELT handles 429 rate limit with retry."""
        from modules.extraction.gdelt_extractor import fetch_news_gdelt

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"articles": [{"title": "After retry"}]}
        mock_get.side_effect = [mock_response_429, mock_response_200]
        articles = fetch_news_gdelt("Apple Inc", "AAPL", max_retries=2)
        assert len(articles) == 1
        assert articles[0]["headline"] == "After retry"

    @patch("modules.extraction.gdelt_extractor.time.sleep")
    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_request_exception(self, mock_get, mock_sleep):
        """Test GDELT handles generic request exceptions."""
        import requests

        from modules.extraction.gdelt_extractor import fetch_news_gdelt

        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")
        articles = fetch_news_gdelt("Apple Inc", "AAPL", max_retries=1)
        assert articles == []

    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_parse_error(self, mock_get):
        """Test GDELT handles JSON parse errors."""
        from modules.extraction.gdelt_extractor import fetch_news_gdelt

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response
        articles = fetch_news_gdelt("Apple Inc", "AAPL", max_retries=1)
        assert articles == []

    @patch("modules.extraction.gdelt_extractor.time.sleep")
    @patch("modules.extraction.gdelt_extractor.requests.get")
    def test_max_retries_exhausted(self, mock_get, mock_sleep):
        """Test GDELT returns empty after exhausting all retries on timeout."""
        import requests

        from modules.extraction.gdelt_extractor import fetch_news_gdelt

        mock_get.side_effect = requests.exceptions.Timeout("Timeout")
        articles = fetch_news_gdelt("Apple Inc", "AAPL", max_retries=3)
        assert articles == []
        assert mock_get.call_count == 3


class TestFetchAllCompaniesNews:
    """Tests for GDELT batch news extraction."""

    @patch("modules.extraction.gdelt_extractor.time.sleep")
    @patch("modules.extraction.gdelt_extractor.fetch_news_gdelt")
    def test_fetch_all_companies_news_success(self, mock_fetch, mock_sleep):
        """Test successful batch news extraction for multiple companies."""
        from modules.extraction.gdelt_extractor import fetch_all_companies_news

        mock_fetch.return_value = [{"headline": "Test article", "company_id": "AAPL"}]
        companies = [
            {"symbol": "AAPL", "security": "Apple Inc"},
            {"symbol": "MSFT", "security": "Microsoft Corp"},
        ]
        result = fetch_all_companies_news(companies, delay_between=0.0, max_retries=1)
        assert "AAPL" in result
        assert "MSFT" in result
        assert len(result["AAPL"]) == 1

    @patch("modules.extraction.gdelt_extractor.time.sleep")
    @patch("modules.extraction.gdelt_extractor.fetch_news_gdelt")
    def test_fetch_all_companies_news_skips_empty_ticker(self, mock_fetch, mock_sleep):
        """Test that companies with empty tickers are skipped."""
        from modules.extraction.gdelt_extractor import fetch_all_companies_news

        mock_fetch.return_value = [{"headline": "Test"}]
        companies = [
            {"symbol": "", "security": "No Ticker Corp"},
            {"symbol": "AAPL", "security": "Apple Inc"},
        ]
        result = fetch_all_companies_news(companies, delay_between=0.0, max_retries=1)
        assert "AAPL" in result
        assert "" not in result

    @patch("modules.extraction.gdelt_extractor.time.sleep")
    @patch("modules.extraction.gdelt_extractor.fetch_news_gdelt")
    def test_fetch_all_companies_news_uses_ticker_as_name_fallback(self, mock_fetch, mock_sleep):
        """Test that ticker is used as company name when security is missing."""
        from modules.extraction.gdelt_extractor import fetch_all_companies_news

        mock_fetch.return_value = []
        companies = [{"symbol": "AAPL"}]
        result = fetch_all_companies_news(companies, delay_between=0.0, max_retries=1)
        assert "AAPL" in result
        # Verify fetch_news_gdelt was called with ticker as name fallback
        mock_fetch.assert_called_with(
            company_name="AAPL",
            company_id="AAPL",
            timespan="3months",
            max_records=50,
            max_retries=1,
        )

    @patch("modules.extraction.gdelt_extractor.time.sleep")
    @patch("modules.extraction.gdelt_extractor.fetch_news_gdelt")
    def test_fetch_all_companies_news_progress_logging(self, mock_fetch, mock_sleep):
        """Test fetch_all_companies_news with enough companies to trigger progress log."""
        from modules.extraction.gdelt_extractor import fetch_all_companies_news

        mock_fetch.return_value = []
        # Create 51 companies to trigger the modulo-50 progress log
        companies = [{"symbol": f"T{i:03d}", "security": f"Company {i}"} for i in range(51)]
        result = fetch_all_companies_news(companies, delay_between=0.0, max_retries=1)
        assert len(result) == 51
