"""
Tests for the value_calculator module — computes financial ratios from
raw financial statements and ranks companies by percentile.

Tests each individual ratio calculator, the enhancement/fallback mechanism,
and the percentile-ranking + composite Value Score computation.
"""

import pytest

from modules.processing.value_calculator import (
    _extract_field,
    _safe_float,
    calculate_debt_equity,
    calculate_dividend_yield,
    calculate_ev_ebitda,
    calculate_pb_ratio,
    calculate_pe_ratio,
    calculate_ratios_from_financials,
    compute_value_score,
    enhance_company_info,
    rank_companies,
)

# ---------------------------------------------------------------------------
# Sample financial data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_income_statement():
    """Income statement with typical yfinance fields."""
    return {
        "Net Income": {"2024-09-30": 25000000000, "2024-06-30": 22000000000},
        "Total Revenue": {"2024-09-30": 95000000000, "2024-06-30": 85000000000},
        "EBITDA": {"2024-09-30": 35000000000, "2024-06-30": 30000000000},
        "Operating Income": {"2024-09-30": 30000000000, "2024-06-30": 26000000000},
        "Basic EPS": {"2024-09-30": 1.65, "2024-06-30": 1.45},
    }


@pytest.fixture
def sample_balance_sheet():
    """Balance sheet with typical yfinance fields."""
    return {
        "Stockholders Equity": {"2024-09-30": 62000000000, "2024-06-30": 58000000000},
        "Total Debt": {"2024-09-30": 110000000000, "2024-06-30": 105000000000},
        "Total Assets": {"2024-09-30": 350000000000, "2024-06-30": 340000000000},
        "Cash And Cash Equivalents": {"2024-09-30": 30000000000, "2024-06-30": 28000000000},
        "Share Issued": {"2024-09-30": 15200000000, "2024-06-30": 15200000000},
    }


@pytest.fixture
def sample_cash_flow():
    """Cash flow statement with dividends paid."""
    return {
        "Cash Dividends Paid": {"2024-09-30": -3800000000, "2024-06-30": -3700000000},
        "Operating Cash Flow": {"2024-09-30": 28000000000, "2024-06-30": 25000000000},
        "Free Cash Flow": {"2024-09-30": 22000000000, "2024-06-30": 19000000000},
    }


@pytest.fixture
def sample_financials(sample_income_statement, sample_balance_sheet, sample_cash_flow):
    """Complete financial data dict."""
    return {
        "income_statement": sample_income_statement,
        "balance_sheet": sample_balance_sheet,
        "cash_flow": sample_cash_flow,
    }


@pytest.fixture
def sample_company_info():
    """Company info dict with market cap but missing some ratios."""
    return {
        "symbol": "AAPL",
        "market_cap": 3000000000000,  # $3 trillion
        "pe_ratio": None,
        "pb_ratio": None,
        "ev_ebitda": None,
        "dividend_yield": None,
        "debt_equity": None,
    }


# ---------------------------------------------------------------------------
# Tests: _safe_float helper
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_valid_float(self):
        assert _safe_float(42.5) == 42.5

    def test_valid_int(self):
        assert _safe_float(10) == 10.0

    def test_valid_string(self):
        assert _safe_float("3.14") == 3.14

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_inf(self):
        assert _safe_float(float("inf")) is None

    def test_invalid_string(self):
        assert _safe_float("not_a_number") is None


# ---------------------------------------------------------------------------
# Tests: _extract_field helper
# ---------------------------------------------------------------------------


class TestExtractField:
    def test_extracts_most_recent_value(self, sample_income_statement):
        val = _extract_field(sample_income_statement, ["Net Income"])
        assert val == 25000000000  # Most recent date

    def test_tries_aliases(self, sample_balance_sheet):
        val = _extract_field(sample_balance_sheet, ["NonExistent", "Total Debt"])
        assert val == 110000000000

    def test_returns_none_for_no_match(self, sample_income_statement):
        val = _extract_field(sample_income_statement, ["NonExistentField"])
        assert val is None

    def test_empty_statement(self):
        assert _extract_field({}, ["Net Income"]) is None

    def test_none_statement(self):
        assert _extract_field(None, ["Net Income"]) is None


# ---------------------------------------------------------------------------
# Tests: Individual ratio calculators
# ---------------------------------------------------------------------------


class TestCalculatePeRatio:
    def test_from_market_cap_and_net_income(self, sample_financials, sample_company_info):
        pe = calculate_pe_ratio(sample_financials, sample_company_info)
        # 3T / 25B = 120
        assert pe is not None
        assert pe == pytest.approx(120.0, rel=0.01)

    def test_uses_precomputed_if_available(self, sample_financials):
        info = {"pe_ratio": 28.5, "market_cap": 3e12}
        pe = calculate_pe_ratio(sample_financials, info)
        assert pe == 28.5

    def test_returns_none_with_no_data(self):
        assert calculate_pe_ratio({}) is None

    def test_negative_net_income_returns_negative_pe(self):
        """Negative P/E is computed here; filtering happens in value_scorer."""
        financials = {"income_statement": {"Net Income": {"2024-09-30": -5000000}}}
        info = {"market_cap": 1000000000}
        pe = calculate_pe_ratio(financials, info)
        assert pe is not None
        assert pe < 0  # 1e9 / -5e6 = -200.0


class TestCalculatePbRatio:
    def test_from_market_cap_and_equity(self, sample_financials, sample_company_info):
        pb = calculate_pb_ratio(sample_financials, sample_company_info)
        # 3T / 62B = 48.39
        assert pb is not None
        assert pb == pytest.approx(48.3871, rel=0.01)

    def test_uses_precomputed(self, sample_financials):
        info = {"pb_ratio": 4.21}
        pb = calculate_pb_ratio(sample_financials, info)
        assert pb == 4.21

    def test_returns_none_without_equity(self):
        financials = {"balance_sheet": {}}
        info = {"market_cap": 1e12}
        assert calculate_pb_ratio(financials, info) is None


class TestCalculateEvEbitda:
    def test_from_financials(self, sample_financials, sample_company_info):
        ev_ebitda = calculate_ev_ebitda(sample_financials, sample_company_info)
        # EV = 3T + 110B - 30B = 3.08T; EBITDA = 35B
        # EV/EBITDA = 88.0
        assert ev_ebitda is not None
        assert ev_ebitda == pytest.approx(88.0, rel=0.01)

    def test_fallback_to_operating_income(self, sample_company_info):
        """When EBITDA is missing, use Operating Income + Depreciation."""
        financials = {
            "income_statement": {
                "Operating Income": {"2024-09-30": 30000000000},
                "Depreciation And Amortization": {"2024-09-30": 5000000000},
            },
            "balance_sheet": {
                "Total Debt": {"2024-09-30": 110000000000},
                "Cash And Cash Equivalents": {"2024-09-30": 30000000000},
            },
        }
        ev_ebitda = calculate_ev_ebitda(financials, sample_company_info)
        # EV = 3T + 110B - 30B = 3.08T; EBITDA = 30B + 5B = 35B
        assert ev_ebitda is not None
        assert ev_ebitda == pytest.approx(88.0, rel=0.01)

    def test_returns_none_without_market_cap(self, sample_financials):
        info = {"market_cap": None}
        assert calculate_ev_ebitda(sample_financials, info) is None


class TestCalculateDividendYield:
    def test_from_cash_flow(self, sample_financials, sample_company_info):
        dy = calculate_dividend_yield(sample_financials, sample_company_info)
        # |−3.8B| / 3T * 100 = 0.1267%
        assert dy is not None
        assert dy == pytest.approx(0.1267, rel=0.01)

    def test_uses_precomputed(self, sample_financials):
        info = {"dividend_yield": 2.7}
        dy = calculate_dividend_yield(sample_financials, info)
        assert dy == 2.7

    def test_returns_zero_for_non_payer(self):
        """Companies with no dividend data but valid market_cap return 0% yield."""
        financials = {"cash_flow": {}}
        info = {"market_cap": 1e12}
        assert calculate_dividend_yield(financials, info) == 0.0

    def test_returns_none_without_market_cap(self):
        financials = {"cash_flow": {}}
        info = {}
        assert calculate_dividend_yield(financials, info) is None


class TestCalculateDebtEquity:
    def test_from_balance_sheet(self, sample_financials, sample_company_info):
        de = calculate_debt_equity(sample_financials, sample_company_info)
        # 110B / 62B * 100 = 177.42
        assert de is not None
        assert de == pytest.approx(177.4194, rel=0.01)

    def test_uses_precomputed(self, sample_financials):
        info = {"debt_equity": 102.63}
        de = calculate_debt_equity(sample_financials, info)
        assert de == 102.63

    def test_returns_none_without_equity(self):
        financials = {"balance_sheet": {"Total Debt": {"2024-09-30": 1000}}}
        assert calculate_debt_equity(financials) is None


# ---------------------------------------------------------------------------
# Tests: enhance_company_info
# ---------------------------------------------------------------------------


class TestEnhanceCompanyInfo:
    def test_fills_missing_ratios(self, sample_financials, sample_company_info):
        enhanced = enhance_company_info(sample_company_info, sample_financials)
        assert enhanced["pe_ratio"] is not None
        assert enhanced["pb_ratio"] is not None
        assert enhanced["ev_ebitda"] is not None
        assert enhanced["debt_equity"] is not None

    def test_preserves_existing_values(self, sample_financials):
        info = {"symbol": "AAPL", "pe_ratio": 28.5, "market_cap": 3e12}
        enhanced = enhance_company_info(info, sample_financials)
        assert enhanced["pe_ratio"] == 28.5  # Not overwritten

    def test_no_change_without_financials(self, sample_company_info):
        enhanced = enhance_company_info(sample_company_info, {})
        assert enhanced == sample_company_info


# ---------------------------------------------------------------------------
# Tests: calculate_ratios_from_financials
# ---------------------------------------------------------------------------


class TestCalculateRatiosFromFinancials:
    def test_calculates_with_market_cap(self, sample_financials):
        result = calculate_ratios_from_financials("AAPL", sample_financials, 3e12)
        assert result["symbol"] == "AAPL"
        assert result["pe_ratio"] is not None
        assert result["pb_ratio"] is not None

    def test_returns_empty_without_data(self):
        result = calculate_ratios_from_financials("AAPL", {})
        assert result == {}


# ---------------------------------------------------------------------------
# Tests: rank_companies
# ---------------------------------------------------------------------------


class TestRankCompanies:
    def test_ranks_multiple_companies(self):
        companies = [
            {"symbol": "A", "pe_ratio": 10, "pb_ratio": 1.0, "ev_ebitda": 5, "dividend_yield": 3.0},
            {"symbol": "B", "pe_ratio": 20, "pb_ratio": 2.0, "ev_ebitda": 10, "dividend_yield": 2.0},
            {"symbol": "C", "pe_ratio": 30, "pb_ratio": 3.0, "ev_ebitda": 15, "dividend_yield": 1.0},
        ]
        ranked = rank_companies(companies)
        assert len(ranked) == 3
        # Company A has lowest P/E → should have highest inverted rank
        assert ranked[0]["pe_ratio_pctile"] == 100.0  # Inverted: rank 0 → (1-0)*100
        assert ranked[2]["pe_ratio_pctile"] == 0.0  # Inverted: rank 1 → (1-1)*100

    def test_handles_missing_values(self):
        companies = [
            {"symbol": "A", "pe_ratio": 10, "pb_ratio": None, "ev_ebitda": 5, "dividend_yield": 3.0},
            {"symbol": "B", "pe_ratio": 20, "pb_ratio": 2.0, "ev_ebitda": None, "dividend_yield": 2.0},
        ]
        ranked = rank_companies(companies)
        assert ranked[0]["pb_ratio_pctile"] is None
        assert ranked[1]["ev_ebitda_pctile"] is None

    def test_excludes_negative_pe(self):
        companies = [
            {"symbol": "A", "pe_ratio": -5, "pb_ratio": 1.0, "ev_ebitda": 5, "dividend_yield": 3.0},
            {"symbol": "B", "pe_ratio": 20, "pb_ratio": 2.0, "ev_ebitda": 10, "dividend_yield": 2.0},
        ]
        ranked = rank_companies(companies)
        assert ranked[0]["pe_ratio_pctile"] is None  # Negative excluded from ranking
        assert ranked[0]["pe_ratio"] == -5  # Original P/E preserved for storage

    def test_excludes_extreme_pe(self):
        companies = [
            {"symbol": "A", "pe_ratio": 600, "pb_ratio": 1.0, "ev_ebitda": 5, "dividend_yield": 3.0},
        ]
        ranked = rank_companies(companies)
        assert ranked[0]["pe_ratio_pctile"] is None  # P/E > 500 excluded from ranking
        assert ranked[0]["pe_ratio"] == 600  # Original P/E preserved for storage

    def test_empty_input(self):
        assert rank_companies([]) == []


# ---------------------------------------------------------------------------
# Tests: compute_value_score
# ---------------------------------------------------------------------------


class TestComputeValueScore:
    def test_computes_average_of_percentiles(self):
        ranked = [
            {
                "symbol": "A",
                "pe_ratio": 10,
                "pb_ratio": 1.0,
                "ev_ebitda": 5,
                "dividend_yield": 3.0,
                "debt_equity": 100,
                "pe_ratio_pctile": 80.0,
                "pb_ratio_pctile": 70.0,
                "ev_ebitda_pctile": 90.0,
                "dividend_yield_pctile": 60.0,
            },
        ]
        from datetime import date

        result = compute_value_score(ranked, date(2025, 3, 1))
        assert len(result) == 1
        assert result[0]["company_id"] == "A"
        # Average: (80 + 70 + 90 + 60) / 4 = 75.0
        assert result[0]["value_score"] == pytest.approx(75.0, rel=0.01)

    def test_handles_missing_percentiles(self):
        ranked = [
            {
                "symbol": "A",
                "pe_ratio": None,
                "pb_ratio": 1.0,
                "ev_ebitda": 5,
                "dividend_yield": 3.0,
                "debt_equity": 100,
                "pe_ratio_pctile": None,
                "pb_ratio_pctile": 70.0,
                "ev_ebitda_pctile": 90.0,
                "dividend_yield_pctile": 60.0,
            },
        ]
        result = compute_value_score(ranked)
        # Average of 3 available: (70 + 90 + 60) / 3 = 73.33
        assert result[0]["value_score"] == pytest.approx(73.333, rel=0.01)

    def test_converts_dividend_yield_to_decimal(self):
        ranked = [
            {
                "symbol": "A",
                "pe_ratio": 10,
                "pb_ratio": 1.0,
                "ev_ebitda": 5,
                "dividend_yield": 2.7,
                "debt_equity": 150,
                "pe_ratio_pctile": 50.0,
                "pb_ratio_pctile": 50.0,
                "ev_ebitda_pctile": 50.0,
                "dividend_yield_pctile": 50.0,
            },
        ]
        result = compute_value_score(ranked)
        # 2.7% → 0.027
        assert result[0]["dividend_yield"] == pytest.approx(0.027, rel=0.01)
        # 150% → 1.50
        assert result[0]["debt_equity"] == pytest.approx(1.50, rel=0.01)

    def test_none_score_when_no_percentiles(self):
        ranked = [
            {
                "symbol": "A",
                "pe_ratio": None,
                "pb_ratio": None,
                "ev_ebitda": None,
                "dividend_yield": None,
                "debt_equity": None,
                "pe_ratio_pctile": None,
                "pb_ratio_pctile": None,
                "ev_ebitda_pctile": None,
                "dividend_yield_pctile": None,
            },
        ]
        result = compute_value_score(ranked)
        assert result[0]["value_score"] is None
