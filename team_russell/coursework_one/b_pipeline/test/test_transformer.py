"""Unit tests for Pipeline B transformer module."""

import pytest
from modules.transformer.transformer import _safe_float, transform_financials, transform_prices


class TestSafeFloat:
    def test_nan_input_returns_none(self):
        # float('nan') must become None so PostgreSQL stores NULL, not NUMERIC NaN
        assert _safe_float(float("nan")) is None

    def test_none_input_returns_none(self):
        assert _safe_float(None) is None

    def test_valid_string_converts(self):
        assert _safe_float("123.45") == pytest.approx(123.45)


class TestTransformPrices:
    def test_returns_one_record_per_date(self):
        raw = {
            "symbol": "AAPL",
            "prices": {"2024-01-02": 150.0, "2024-01-03": 151.5},
            "shares_outstanding": 1_000_000,
        }
        records = transform_prices(raw)
        assert len(records) == 2

    def test_record_fields_are_correct(self):
        raw = {
            "symbol": "AAPL ",
            "prices": {"2024-01-02": 150.0},
            "shares_outstanding": 500_000,
        }
        record = transform_prices(raw)[0]
        assert record["symbol"] == "AAPL"
        assert record["price_date"] == "2024-01-02"
        assert record["closing_price"] == 150.0
        assert record["shares_outstanding"] == 500_000

    def test_empty_prices_returns_empty_list(self):
        raw = {"symbol": "AAPL", "prices": {}, "shares_outstanding": None}
        assert transform_prices(raw) == []


class TestTransformFinancials:
    def _make_bs(self, date="2024-09-30"):
        return {
            "data": {
                "quarterlyReports": [
                    {
                        "fiscalDateEnding": date,
                        "totalAssets": "300000000",
                        "totalLiabilities": "150000000",
                        "totalDebt": "50000000",
                        "cashAndCashEquivalentsAtCarryingValue": "20000000",
                        "currentAssets": "80000000",
                        "currentLiabilities": "40000000",
                    }
                ]
            }
        }

    def _make_inc(self, date="2024-09-30"):
        return {
            "data": {
                "quarterlyReports": [
                    {
                        "fiscalDateEnding": date,
                        "netIncome": "30000000",
                        "ebitda": "45000000",
                        "totalRevenue": "120000000",
                        "grossProfit": "60000000",
                        "freeCashFlow": "25000000",
                        "annualDividendRate": "0.96",
                    }
                ]
            }
        }

    def test_returns_one_record_per_matched_quarter(self):
        records = transform_financials(self._make_bs(), self._make_inc())
        assert len(records) == 1

    def test_book_value_computed_correctly(self):
        records = transform_financials(self._make_bs(), self._make_inc())
        assert records[0]["book_value"] == pytest.approx(150_000_000.0)

    def test_unmatched_date_excluded(self):
        records = transform_financials(self._make_bs("2024-09-30"), self._make_inc("2024-06-30"))
        assert records[0]["net_income_ttm"] is None

    def test_revenue_extracted_from_income_statement(self):
        records = transform_financials(self._make_bs(), self._make_inc())
        assert records[0]["revenue"] == pytest.approx(120_000_000.0)

    def test_gross_profit_extracted(self):
        records = transform_financials(self._make_bs(), self._make_inc())
        assert records[0]["gross_profit"] == pytest.approx(60_000_000.0)

    def test_free_cash_flow_extracted(self):
        records = transform_financials(self._make_bs(), self._make_inc())
        assert records[0]["free_cash_flow"] == pytest.approx(25_000_000.0)

    def test_current_assets_and_liabilities_extracted(self):
        records = transform_financials(self._make_bs(), self._make_inc())
        assert records[0]["current_assets"] == pytest.approx(80_000_000.0)
        assert records[0]["current_liabilities"] == pytest.approx(40_000_000.0)

    def test_annual_dividend_rate_extracted(self):
        records = transform_financials(self._make_bs(), self._make_inc())
        assert records[0]["annual_dividend_rate"] == pytest.approx(0.96)

    def test_missing_value_returns_none(self):
        bs = {"data": {"quarterlyReports": [{"fiscalDateEnding": "2024-09-30"}]}}
        inc = {"data": {"quarterlyReports": [{"fiscalDateEnding": "2024-09-30"}]}}
        records = transform_financials(bs, inc)
        assert records[0]["total_assets"] is None
        assert records[0]["book_value"] is None
        assert records[0]["gross_profit"] is None
        assert records[0]["free_cash_flow"] is None
