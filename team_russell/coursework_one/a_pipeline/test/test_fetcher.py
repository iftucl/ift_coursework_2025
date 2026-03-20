"""Unit tests for Pipeline A fetcher modules."""

from unittest.mock import MagicMock, patch

import pandas as pd
from modules.fetcher.alpha_vantage_fetcher import fetch_balance_sheet, fetch_income_statement
from modules.fetcher.yfinance_fetcher import fetch_prices
from modules.fetcher.yfinance_financial_fetcher import (
    _extract_bs_reports,
    _extract_inc_reports,
    fetch_financials_yfinance,
)


class TestYfinanceFetcher:
    @patch("modules.fetcher.yfinance_fetcher.yf.Ticker")
    def test_fetch_prices_returns_dict(self, mock_ticker):
        mock_hist = pd.DataFrame(
            {"Close": [150.0, 151.0]},
            index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
        )
        mock_ticker.return_value.history.return_value = mock_hist
        mock_ticker.return_value.info = {"sharesOutstanding": 1_000_000}

        result = fetch_prices("AAPL", "2024-01-01", "2024-01-03")

        assert result is not None
        assert result["symbol"] == "AAPL"
        assert "prices" in result
        assert result["shares_outstanding"] == 1_000_000

    @patch("modules.fetcher.yfinance_fetcher.yf.Ticker")
    def test_fetch_prices_returns_none_on_empty(self, mock_ticker):
        mock_ticker.return_value.history.return_value = pd.DataFrame()

        result = fetch_prices("INVALID", "2024-01-01", "2024-01-03")

        assert result is None

    @patch("modules.fetcher.yfinance_fetcher.yf.Ticker")
    def test_fetch_prices_returns_none_on_exception(self, mock_ticker):
        mock_ticker.return_value.history.side_effect = Exception("network error")

        result = fetch_prices("AAPL", "2024-01-01", "2024-01-03")

        assert result is None


class TestAlphaVantageFetcher:
    @patch("modules.fetcher.alpha_vantage_fetcher.requests.get")
    @patch("modules.fetcher.alpha_vantage_fetcher.time.sleep")
    def test_fetch_balance_sheet_success(self, mock_sleep, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "symbol": "AAPL",
            "quarterlyReports": [{"fiscalDateEnding": "2024-09-30", "totalAssets": "300000000"}],
        }

        result = fetch_balance_sheet("AAPL", "demo")

        assert result is not None
        assert result["type"] == "balance_sheet"
        assert result["symbol"] == "AAPL"

    @patch("modules.fetcher.alpha_vantage_fetcher.requests.get")
    @patch("modules.fetcher.alpha_vantage_fetcher.time.sleep")
    def test_fetch_balance_sheet_returns_none_on_rate_limit(self, mock_sleep, mock_get):
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {"Note": "API call frequency limit reached."}

        result = fetch_balance_sheet("AAPL", "demo")

        assert result is None

    @patch("modules.fetcher.alpha_vantage_fetcher.requests.get")
    @patch("modules.fetcher.alpha_vantage_fetcher.time.sleep")
    def test_fetch_income_statement_success(self, mock_sleep, mock_get):
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json.return_value = {
            "symbol": "AAPL",
            "quarterlyReports": [{"fiscalDateEnding": "2024-09-30", "netIncome": "20000000"}],
        }

        result = fetch_income_statement("AAPL", "demo")

        assert result is not None
        assert result["type"] == "income_statement"


def _make_bs_df():
    """Minimal balance sheet DataFrame matching yfinance structure."""
    date = pd.Timestamp("2024-12-31")
    return pd.DataFrame(
        {
            date: {
                "Total Assets": 500_000_000,
                "Total Liabilities Net Minority Interest": 200_000_000,
                "Total Debt": 80_000_000,
                "Cash And Cash Equivalents": 30_000_000,
                "Current Assets": 120_000_000,
                "Current Liabilities": 60_000_000,
            }
        }
    )


def _make_inc_df():
    """Minimal income statement DataFrame matching yfinance structure."""
    date = pd.Timestamp("2024-12-31")
    return pd.DataFrame(
        {
            date: {
                "Net Income": 40_000_000,
                "EBITDA": 70_000_000,
                "Total Revenue": 300_000_000,
                "Gross Profit": 150_000_000,
            }
        }
    )


def _make_cf_df():
    """Minimal cash flow DataFrame matching yfinance structure."""
    date = pd.Timestamp("2024-12-31")
    return pd.DataFrame({date: {"Free Cash Flow": 35_000_000}})


class TestExtractBsReports:
    def test_returns_one_report_per_column(self):
        ticker = MagicMock()
        ticker.balance_sheet = _make_bs_df()
        reports = _extract_bs_reports(ticker)
        assert len(reports) == 1

    def test_fiscal_date_extracted(self):
        ticker = MagicMock()
        ticker.balance_sheet = _make_bs_df()
        reports = _extract_bs_reports(ticker)
        assert reports[0]["fiscalDateEnding"] == "2024-12-31"

    def test_current_assets_and_liabilities_present(self):
        ticker = MagicMock()
        ticker.balance_sheet = _make_bs_df()
        reports = _extract_bs_reports(ticker)
        assert reports[0]["currentAssets"] is not None
        assert reports[0]["currentLiabilities"] is not None

    def test_returns_empty_on_empty_balance_sheet(self):
        ticker = MagicMock()
        ticker.balance_sheet = pd.DataFrame()
        reports = _extract_bs_reports(ticker)
        assert reports == []

    def test_returns_empty_on_exception(self):
        ticker = MagicMock()
        ticker.balance_sheet = MagicMock(side_effect=Exception("error"))
        reports = _extract_bs_reports(ticker)
        assert reports == []


class TestExtractIncReports:
    def test_returns_one_report_per_column(self):
        ticker = MagicMock()
        ticker.financials = _make_inc_df()
        ticker.cashflow = _make_cf_df()
        ticker.info = {"trailingAnnualDividendRate": 1.20}
        reports = _extract_inc_reports(ticker)
        assert len(reports) == 1

    def test_gross_profit_extracted(self):
        ticker = MagicMock()
        ticker.financials = _make_inc_df()
        ticker.cashflow = _make_cf_df()
        ticker.info = {"trailingAnnualDividendRate": 0.0}
        reports = _extract_inc_reports(ticker)
        assert reports[0]["grossProfit"] is not None

    def test_free_cash_flow_extracted(self):
        ticker = MagicMock()
        ticker.financials = _make_inc_df()
        ticker.cashflow = _make_cf_df()
        ticker.info = {"trailingAnnualDividendRate": 0.0}
        reports = _extract_inc_reports(ticker)
        assert reports[0]["freeCashFlow"] is not None

    def test_annual_dividend_rate_extracted(self):
        ticker = MagicMock()
        ticker.financials = _make_inc_df()
        ticker.cashflow = _make_cf_df()
        ticker.info = {"trailingAnnualDividendRate": 2.40}
        reports = _extract_inc_reports(ticker)
        assert reports[0]["annualDividendRate"] == "2.4"

    def test_returns_empty_on_empty_financials(self):
        ticker = MagicMock()
        ticker.financials = pd.DataFrame()
        reports = _extract_inc_reports(ticker)
        assert reports == []


class TestFetchFinancialsYfinance:
    @patch("modules.fetcher.yfinance_financial_fetcher.yf.Ticker")
    def test_returns_dict_with_expected_keys(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.balance_sheet = _make_bs_df()
        mock_ticker.financials = _make_inc_df()
        mock_ticker.cashflow = _make_cf_df()
        mock_ticker.info = {"trailingAnnualDividendRate": 0.96}
        mock_ticker_cls.return_value = mock_ticker

        result = fetch_financials_yfinance("AAPL")

        assert result is not None
        assert "symbol" in result
        assert "balance_sheet" in result
        assert "income_statement" in result

    @patch("modules.fetcher.yfinance_financial_fetcher.yf.Ticker")
    def test_balance_sheet_has_correct_type(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.balance_sheet = _make_bs_df()
        mock_ticker.financials = _make_inc_df()
        mock_ticker.cashflow = _make_cf_df()
        mock_ticker.info = {"trailingAnnualDividendRate": 0.0}
        mock_ticker_cls.return_value = mock_ticker

        result = fetch_financials_yfinance("AAPL")
        assert result["balance_sheet"]["type"] == "balance_sheet"
        assert result["income_statement"]["type"] == "income_statement"

    @patch("modules.fetcher.yfinance_financial_fetcher.yf.Ticker")
    def test_returns_none_when_no_data(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.balance_sheet = pd.DataFrame()
        mock_ticker.financials = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        result = fetch_financials_yfinance("INVALID")
        assert result is None

    @patch("modules.fetcher.yfinance_financial_fetcher.yf.Ticker")
    def test_returns_none_on_exception(self, mock_ticker_cls):
        mock_ticker_cls.side_effect = Exception("network error")

        result = fetch_financials_yfinance("AAPL")
        assert result is None
