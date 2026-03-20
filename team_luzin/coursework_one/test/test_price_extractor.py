"""
Comprehensive tests for PriceDataExtractor to improve coverage beyond 80%
Targeting all untested code paths and edge cases
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


class TestPriceDataExtractorComprehensive:
    """Comprehensive tests for PriceDataExtractor"""

    def test_init_default_years(self):
        """Test initialization with default 5 years"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()
        assert extractor.years == 5
        assert extractor.start_date is not None
        assert extractor.end_date is not None

    def test_init_custom_years(self):
        """Test initialization with custom years"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor(years=3)
        assert extractor.years == 3

    @patch("modules.extraction.price_extractor.yf.Ticker")
    def test_fetch_price_data_success(self, mock_ticker_class):
        """Test successful price data fetch"""
        from modules.extraction.price_extractor import PriceDataExtractor

        mock_ticker = MagicMock()
        dates = pd.date_range("2020-01-01", periods=100, freq="D")
        mock_ticker.history.return_value = pd.DataFrame(
            {
                "Close": np.linspace(100, 150, 100),
                "High": np.linspace(105, 155, 100),
                "Low": np.linspace(95, 145, 100),
                "Volume": [1000000] * 100,
            },
            index=dates,
        )
        mock_ticker_class.return_value = mock_ticker

        extractor = PriceDataExtractor()
        result = extractor.fetch_price_data("AAPL")

        assert result is not None
        assert len(result) == 100

    @patch("modules.extraction.price_extractor.yf.Ticker")
    def test_fetch_price_data_empty(self, mock_ticker_class):
        """Test fetch returns None for empty data"""
        from modules.extraction.price_extractor import PriceDataExtractor

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker_class.return_value = mock_ticker

        extractor = PriceDataExtractor()
        result = extractor.fetch_price_data("INVALID")

        assert result is None

    @patch("modules.extraction.price_extractor.yf.Ticker")
    def test_fetch_price_data_error(self, mock_ticker_class):
        """Test fetch handles errors gracefully"""
        from modules.extraction.price_extractor import PriceDataExtractor

        mock_ticker_class.side_effect = Exception("API Error")

        extractor = PriceDataExtractor()
        result = extractor.fetch_price_data("ERROR")

        assert result is None

    @patch("modules.extraction.price_extractor.yf.Ticker")
    def test_fetch_multiple_prices_success(self, mock_ticker_class):
        """Test fetching multiple prices"""
        from modules.extraction.price_extractor import PriceDataExtractor

        mock_ticker = MagicMock()
        dates = pd.date_range("2020-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {"Close": np.linspace(100, 150, 100), "Volume": [1000000] * 100},
            index=dates,
        )
        mock_ticker.history.return_value = df
        mock_ticker_class.return_value = mock_ticker

        extractor = PriceDataExtractor()
        result = extractor.fetch_multiple_prices(["AAPL", "MSFT", "GOOGL"])

        assert len(result) == 3
        assert "AAPL" in result
        assert "MSFT" in result

    @patch("modules.extraction.price_extractor.yf.Ticker")
    def test_fetch_multiple_prices_mixed(self, mock_ticker_class):
        """Test fetching multiple prices with some failures"""
        from modules.extraction.price_extractor import PriceDataExtractor

        def ticker_side_effect(symbol):
            mock = MagicMock()
            if symbol == "AAPL":
                dates = pd.date_range("2020-01-01", periods=100, freq="D")
                df = pd.DataFrame(
                    {"Close": np.linspace(100, 150, 100), "Volume": [1000000] * 100},
                    index=dates,
                )
                mock.history.return_value = df
            else:
                mock.history.return_value = pd.DataFrame()
            return mock

        mock_ticker_class.side_effect = ticker_side_effect

        extractor = PriceDataExtractor()
        result = extractor.fetch_multiple_prices(["AAPL", "INVALID"])

        assert len(result) == 1
        assert "AAPL" in result

    def test_calculate_returns_default_periods(self):
        """Test returns calculation with default periods"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        # Create price data with 300 days
        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        df = pd.DataFrame({"Close": np.linspace(100, 150, 300)}, index=dates)

        result = extractor.calculate_returns(df)

        assert len(result) > 0
        assert any("return" in key for key in result.keys())

    def test_calculate_returns_custom_periods(self):
        """Test returns calculation with custom periods"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        df = pd.DataFrame({"Close": np.linspace(100, 150, 300)}, index=dates)

        result = extractor.calculate_returns(df, periods=[30, 60, 90])

        assert len(result) > 0

    def test_calculate_returns_empty_data(self):
        """Test returns calculation with empty data"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        df = pd.DataFrame()
        result = extractor.calculate_returns(df)

        assert result == {}

    def test_calculate_returns_insufficient_data(self):
        """Test returns calculation with insufficient data"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        dates = pd.date_range("2020-01-01", periods=10, freq="D")
        df = pd.DataFrame({"Close": np.linspace(100, 110, 10)}, index=dates)

        result = extractor.calculate_returns(df, periods=[252])

        assert result == {}

    def test_calculate_momentum_score_sufficient_data(self):
        """Test momentum score with sufficient data"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        dates = pd.date_range("2020-01-01", periods=100, freq="D")
        df = pd.DataFrame({"Close": np.linspace(100, 120, 100)}, index=dates)

        result = extractor.calculate_momentum_score(df)

        assert isinstance(result, (float, int))
        assert result > 0

    def test_calculate_momentum_score_insufficient_data(self):
        """Test momentum score with insufficient data"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        dates = pd.date_range("2020-01-01", periods=30, freq="D")
        df = pd.DataFrame({"Close": np.linspace(100, 110, 30)}, index=dates)

        result = extractor.calculate_momentum_score(df)

        assert result == 0.0

    def test_calculate_momentum_score_error(self):
        """Test momentum score error handling"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        df = pd.DataFrame({"Close": [None] * 100})

        result = extractor.calculate_momentum_score(df)

        assert result == 0.0

    def test_extract_company_metrics_success(self):
        """Test company metrics extraction"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        df = pd.DataFrame({"Close": np.linspace(100, 150, 300)}, index=dates)

        result = extractor.extract_company_metrics("AAPL", df)

        assert "symbol" in result
        assert "current_price" in result
        assert "momentum_score" in result
        assert "volatility" in result

    def test_extract_company_metrics_empty_data(self):
        """Test metrics extraction with empty data"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        result = extractor.extract_company_metrics("AAPL", None)

        assert result == {}

    def test_extract_company_metrics_empty_dataframe(self):
        """Test metrics extraction with empty dataframe"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        df = pd.DataFrame()
        result = extractor.extract_company_metrics("AAPL", df)

        assert result == {}

    def test_extract_company_metrics_error(self):
        """Test metrics extraction error handling"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        df = pd.DataFrame({"Close": [None, None, None]})

        result = extractor.extract_company_metrics("AAPL", df)

        # Should handle error gracefully
        assert isinstance(result, dict)

    @patch("modules.extraction.price_extractor.yf.Ticker")
    def test_extract_all_metrics(self, mock_ticker_class):
        """Test extracting metrics for all companies"""
        from modules.extraction.price_extractor import PriceDataExtractor

        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        df = pd.DataFrame(
            {"Close": np.linspace(100, 150, 300), "Volume": [1000000] * 300},
            index=dates,
        )

        symbols_to_data = {"AAPL": df, "MSFT": df, "GOOGL": df}

        extractor = PriceDataExtractor()
        result = extractor.extract_all_metrics(symbols_to_data)

        assert len(result) == 3
        assert all("symbol" in m for m in result)

    def test_organize_prices_by_ticker_year(self):
        """Test organizing prices by ticker and year"""
        from modules.extraction.price_extractor import PriceDataExtractor

        # Create multi-year data
        dates = pd.date_range("2020-01-01", periods=730, freq="D")
        df = pd.DataFrame(
            {"Close": np.linspace(100, 200, 730), "Volume": [1000000] * 730},
            index=dates,
        )
        df.index.name = "Date"

        symbols_to_data = {"AAPL": df, "MSFT": df}

        extractor = PriceDataExtractor()
        result = extractor.organize_prices_by_ticker_year(symbols_to_data)

        assert "AAPL" in result
        assert "MSFT" in result
        assert len(result["AAPL"]) > 0

    def test_organize_prices_by_ticker_year_with_date_column(self):
        """Test organizing prices when Date is a column"""
        from modules.extraction.price_extractor import PriceDataExtractor

        dates = pd.date_range("2020-01-01", periods=730, freq="D")
        df = pd.DataFrame(
            {
                "Date": dates,
                "Close": np.linspace(100, 200, 730),
                "Volume": [1000000] * 730,
            }
        )

        symbols_to_data = {
            "AAPL": df,
        }

        extractor = PriceDataExtractor()
        result = extractor.organize_prices_by_ticker_year(symbols_to_data)

        assert "AAPL" in result
        assert len(result["AAPL"]) > 0

    def test_organize_prices_multiple_years(self):
        """Test organizing prices correctly partitions by year"""
        from modules.extraction.price_extractor import PriceDataExtractor

        dates = pd.date_range("2020-01-01", periods=730, freq="D")
        df = pd.DataFrame(
            {
                "Close": np.linspace(100, 200, 730),
            },
            index=dates,
        )
        df.index.name = "Date"

        symbols_to_data = {"AAPL": df}

        extractor = PriceDataExtractor()
        result = extractor.organize_prices_by_ticker_year(symbols_to_data)

        # Should have data for 2020 and 2021
        assert 2020 in result["AAPL"]
        assert 2021 in result["AAPL"]

    def test_extract_with_high_volatility(self):
        """Test extraction with volatile price data"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        # Highly volatile data
        prices = 100 + np.random.normal(0, 20, 300)
        df = pd.DataFrame({"Close": prices}, index=dates)

        result = extractor.extract_company_metrics("AAPL", df)

        assert "volatility" in result
        assert result["volatility"] > 0

    def test_extract_with_stable_prices(self):
        """Test extraction with very stable prices"""
        from modules.extraction.price_extractor import PriceDataExtractor

        extractor = PriceDataExtractor()

        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        df = pd.DataFrame({"Close": [100.0] * 300}, index=dates)

        result = extractor.extract_company_metrics("AAPL", df)

        assert result["momentum_score"] == 0.0  # No change
        assert result["volatility"] == 0.0  # No volatility
