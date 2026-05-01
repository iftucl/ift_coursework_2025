"""Unit tests for modules.extract.edgar_xbrl.

Tests cover:
- _parse_edgar_date: date parsing and edge cases
- _get_tag_units: nested XBRL fact traversal
- _extract_metric_filings: PIT date, form filtering, deduplication
- extract_financial_records: derived metrics (total_debt, ebitda)
- _derive_total_debt / _derive_ebitda: component combination
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from modules.extract.edgar_xbrl import (
    EDGAR_COMPANY_FACTS_URL,
    _derive_ebitda,
    _derive_roe,
    _derive_total_debt,
    _extract_metric_filings,
    _fetch_facts_raw,
    _get_tag_units,
    _parse_edgar_date,
    _ticker_to_cik,
    extract_financial_records,
    fetch_company_facts,
    run_edgar_extraction,
)


# ---------------------------------------------------------------------------
# _parse_edgar_date
# ---------------------------------------------------------------------------

class TestParseEdgarDate:
    def test_valid_iso_date(self):
        assert _parse_edgar_date("2023-03-31") == date(2023, 3, 31)

    def test_none_returns_none(self):
        assert _parse_edgar_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_edgar_date("") is None

    def test_invalid_format_returns_none(self):
        assert _parse_edgar_date("31/03/2023") is None

    def test_truncates_to_10_chars(self):
        assert _parse_edgar_date("2023-03-31T00:00:00Z") == date(2023, 3, 31)


# ---------------------------------------------------------------------------
# _get_tag_units
# ---------------------------------------------------------------------------

class TestGetTagUnits:
    def _make_facts(self, tag_full: str, units: dict) -> dict:
        taxonomy, tag = tag_full.split(":", 1)
        return {"facts": {taxonomy: {tag: {"units": units}}}}

    def test_returns_units_for_valid_tag(self):
        facts = self._make_facts("us-gaap:Assets", {"USD": [{"val": 1000}]})
        result = _get_tag_units(facts, "us-gaap:Assets")
        assert result == {"USD": [{"val": 1000}]}

    def test_returns_none_for_missing_tag(self):
        facts = {"facts": {"us-gaap": {}}}
        assert _get_tag_units(facts, "us-gaap:Assets") is None

    def test_returns_none_for_missing_taxonomy(self):
        facts = {"facts": {}}
        assert _get_tag_units(facts, "us-gaap:Assets") is None

    def test_handles_empty_facts(self):
        assert _get_tag_units({}, "us-gaap:Assets") is None


# ---------------------------------------------------------------------------
# _extract_metric_filings
# ---------------------------------------------------------------------------

class TestExtractMetricFilings:
    def _make_facts_with_rows(self, rows: list) -> dict:
        return {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {"USD": rows}
                    }
                }
            }
        }

    def test_filters_non_accepted_forms(self):
        facts = self._make_facts_with_rows([
            {"form": "8-K", "end": "2023-03-31", "filed": "2023-04-10", "val": 999}
        ])
        results = _extract_metric_filings(
            facts, "total_assets", ["us-gaap:Assets"],
            cutoff_date=date(2024, 1, 1),
            start_date=date(2020, 1, 1),
        )
        assert results == []

    def test_includes_10q_form(self):
        facts = self._make_facts_with_rows([
            {"form": "10-Q", "end": "2023-03-31", "filed": "2023-04-10", "val": 500}
        ])
        results = _extract_metric_filings(
            facts, "total_assets", ["us-gaap:Assets"],
            cutoff_date=date(2024, 1, 1),
            start_date=date(2020, 1, 1),
        )
        assert len(results) == 1
        assert results[0]["period_type"] == "quarterly"

    def test_10k_mapped_to_annual(self):
        facts = self._make_facts_with_rows([
            {"form": "10-K", "end": "2022-12-31", "filed": "2023-02-03", "val": 1000}
        ])
        results = _extract_metric_filings(
            facts, "total_assets", ["us-gaap:Assets"],
            cutoff_date=date(2024, 1, 1),
            start_date=date(2020, 1, 1),
        )
        assert results[0]["period_type"] == "annual"

    def test_pit_uses_filed_date(self):
        facts = self._make_facts_with_rows([
            {"form": "10-Q", "end": "2023-03-31", "filed": "2023-04-14", "val": 200}
        ])
        results = _extract_metric_filings(
            facts, "total_assets", ["us-gaap:Assets"],
            cutoff_date=date(2024, 1, 1),
            start_date=date(2020, 1, 1),
        )
        assert results[0]["publish_date"] == date(2023, 4, 14)

    def test_pit_fallback_when_filed_missing(self):
        facts = self._make_facts_with_rows([
            {"form": "10-Q", "end": "2023-03-31", "val": 200}  # no filed
        ])
        results = _extract_metric_filings(
            facts, "total_assets", ["us-gaap:Assets"],
            cutoff_date=date(2024, 1, 1),
            start_date=date(2020, 1, 1),
        )
        from datetime import timedelta
        expected = date(2023, 3, 31) + timedelta(days=45)
        assert results[0]["publish_date"] == expected

    def test_excludes_dates_outside_range(self):
        facts = self._make_facts_with_rows([
            {"form": "10-Q", "end": "2015-03-31", "filed": "2015-04-10", "val": 100}
        ])
        results = _extract_metric_filings(
            facts, "total_assets", ["us-gaap:Assets"],
            cutoff_date=date(2024, 1, 1),
            start_date=date(2020, 1, 1),
        )
        assert results == []

    def test_deduplicates_same_end_form(self):
        facts = self._make_facts_with_rows([
            {"form": "10-Q", "end": "2023-03-31", "filed": "2023-04-10", "val": 100},
            {"form": "10-Q", "end": "2023-03-31", "filed": "2023-04-15", "val": 200},
        ])
        results = _extract_metric_filings(
            facts, "total_assets", ["us-gaap:Assets"],
            cutoff_date=date(2024, 1, 1),
            start_date=date(2020, 1, 1),
        )
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

class TestDeriveTotalDebt:
    def _base_rec(
        self,
        metric,
        val,
        report_date=date(2023, 3, 31),
        pit=date(2023, 4, 14),
        as_of=date(2024, 1, 1),
    ):
        return {
            "symbol": "AAPL",
            "report_date": report_date,
            "metric_name": metric,
            "metric_value": val,
            "period_type": "quarterly",
            "as_of": as_of,
            "publish_date": pit,
            "currency": "USD",
            "metric_definition": "provider_reported",
            "source": "edgar_xbrl",
        }

    def test_derives_total_debt_from_both_components(self):
        records = [
            self._base_rec("long_term_debt", 800.0),
            self._base_rec("short_term_debt", 200.0),
        ]
        derived = _derive_total_debt("AAPL", records)
        assert len(derived) == 1
        assert derived[0]["metric_name"] == "total_debt"
        assert derived[0]["metric_value"] == 1000.0

    def test_uses_only_long_term_when_short_missing(self):
        records = [self._base_rec("long_term_debt", 500.0)]
        derived = _derive_total_debt("AAPL", records)
        assert derived[0]["metric_value"] == 500.0

    def test_no_debt_components_returns_empty(self):
        records = [self._base_rec("total_assets", 9999.0)]
        derived = _derive_total_debt("AAPL", records)
        assert derived == []


class TestDeriveEbitda:
    def _base_rec(self, metric, val):
        return {
            "symbol": "MSFT",
            "report_date": date(2023, 6, 30),
            "metric_name": metric,
            "metric_value": val,
            "period_type": "quarterly",
            "as_of": date(2024, 1, 1),
            "publish_date": date(2023, 7, 25),
            "currency": "USD",
            "metric_definition": "provider_reported",
            "source": "edgar_xbrl",
        }

    def test_derives_ebitda_from_oi_plus_da(self):
        records = [
            self._base_rec("operating_income", 600.0),
            self._base_rec("depreciation_amortization", 150.0),
        ]
        derived = _derive_ebitda("MSFT", records)
        assert len(derived) == 1
        assert derived[0]["metric_value"] == 750.0

    def test_ebitda_from_oi_only_when_da_missing(self):
        records = [self._base_rec("operating_income", 400.0)]
        derived = _derive_ebitda("MSFT", records)
        assert derived[0]["metric_value"] == 400.0

    def test_no_operating_income_returns_empty(self):
        records = [self._base_rec("depreciation_amortization", 100.0)]
        derived = _derive_ebitda("MSFT", records)
        assert derived == []


class TestDeriveRoe:
    def _base_rec(self, metric, val):
        return {
            "symbol": "GOOG",
            "report_date": date(2023, 9, 30),
            "metric_name": metric,
            "metric_value": val,
            "period_type": "quarterly",
            "as_of": date(2024, 1, 1),
            "publish_date": date(2023, 10, 20),
            "currency": "USD",
            "metric_definition": "provider_reported",
            "source": "edgar_xbrl",
        }

    def test_derives_roe_correctly(self):
        records = [
            self._base_rec("net_income", 200.0),
            self._base_rec("stockholders_equity", 1000.0),
        ]
        derived = _derive_roe("GOOG", records)
        assert len(derived) == 1
        assert derived[0]["metric_name"] == "roe"
        assert abs(derived[0]["metric_value"] - 0.2) < 1e-9

    def test_zero_equity_returns_empty(self):
        records = [
            self._base_rec("net_income", 200.0),
            self._base_rec("stockholders_equity", 0.0),
        ]
        assert _derive_roe("GOOG", records) == []

    def test_negative_equity_negative_income_discarded(self):
        records = [
            self._base_rec("net_income", -50.0),
            self._base_rec("stockholders_equity", -200.0),
        ]
        # Both negative → distorted ROE discarded
        assert _derive_roe("GOOG", records) == []

    def test_negative_equity_positive_income_kept(self):
        records = [
            self._base_rec("net_income", 100.0),
            self._base_rec("stockholders_equity", -500.0),
        ]
        derived = _derive_roe("GOOG", records)
        assert len(derived) == 1
        assert derived[0]["metric_value"] < 0  # negative ROE (leveraged firm)

    def test_missing_equity_returns_empty(self):
        records = [self._base_rec("net_income", 100.0)]
        assert _derive_roe("GOOG", records) == []


# ---------------------------------------------------------------------------
# _ticker_to_cik
# ---------------------------------------------------------------------------

class TestTickerToCik:
    def _make_edgar_tickers_response(self, ticker: str, cik: int):
        return {
            "0": {"ticker": ticker, "cik_str": cik, "title": f"{ticker} Corp"},
        }

    def test_returns_zero_padded_cik(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_edgar_tickers_response("AAPL", 320193)
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            cik = _ticker_to_cik("AAPL")
        assert cik == "0000320193"

    def test_case_insensitive_ticker_match(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._make_edgar_tickers_response("MSFT", 789019)
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            cik = _ticker_to_cik("msft")
        assert cik == "0000789019"

    def test_returns_none_for_unknown_ticker(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"0": {"ticker": "AAPL", "cik_str": 320193}}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            cik = _ticker_to_cik("UNKN")
        assert cik is None

    def test_returns_none_on_request_exception(self):
        with patch("requests.get", side_effect=Exception("network error")):
            cik = _ticker_to_cik("AAPL")
        assert cik is None


# ---------------------------------------------------------------------------
# fetch_company_facts
# ---------------------------------------------------------------------------

class TestFetchCompanyFacts:
    def test_company_facts_url_includes_cik_prefix(self):
        assert EDGAR_COMPANY_FACTS_URL.endswith("/companyfacts/CIK{cik}.json")

    def test_fetch_facts_raw_uses_cik_prefixed_url(self):
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"facts": {}}
        with patch("modules.extract.edgar_xbrl.requests.get", return_value=fake_response) as mock_get:
            _fetch_facts_raw("0000320193")
        called_url = mock_get.call_args.kwargs["url"] if "url" in mock_get.call_args.kwargs else mock_get.call_args.args[0]
        assert called_url.endswith("/companyfacts/CIK0000320193.json")

    def test_returns_none_when_no_cik(self):
        with patch("modules.extract.edgar_xbrl._ticker_to_cik", return_value=None):
            result = fetch_company_facts("UNKN")
        assert result is None

    def test_returns_facts_for_valid_ticker(self):
        fake_facts = {"facts": {"us-gaap": {}}}
        with patch("modules.extract.edgar_xbrl._ticker_to_cik", return_value="0000320193"), \
             patch("modules.extract.edgar_xbrl._fetch_facts_raw", return_value=fake_facts):
            result = fetch_company_facts("AAPL")
        assert result == fake_facts

    def test_returns_none_on_fetch_exception(self):
        with patch("modules.extract.edgar_xbrl._ticker_to_cik", return_value="0000320193"), \
             patch("modules.extract.edgar_xbrl._fetch_facts_raw",
                   side_effect=Exception("API error")):
            result = fetch_company_facts("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# extract_financial_records
# ---------------------------------------------------------------------------

class TestExtractFinancialRecords:
    def _make_facts(self, val=1000):
        """Minimal EDGAR facts JSON with one 10-K filing for total_assets."""
        return {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "form": "10-K",
                                    "end": "2022-12-31",
                                    "filed": "2023-02-03",
                                    "val": val,
                                }
                            ]
                        }
                    }
                }
            }
        }

    def test_empty_facts_returns_empty_list(self):
        result = extract_financial_records("AAPL", {}, as_of=date(2024, 1, 1))
        assert result == []

    def test_none_facts_returns_empty_list(self):
        result = extract_financial_records("AAPL", None, as_of=date(2024, 1, 1))
        assert result == []

    def test_extracts_total_assets_record(self):
        facts = self._make_facts(val=5_000_000_000)
        records = extract_financial_records("AAPL", facts, backfill_years=5, as_of=date(2024, 1, 1))
        names = {r["metric_name"] for r in records}
        assert "total_assets" in names
        assert all(r["as_of"] == date(2024, 1, 1) for r in records)

    def test_all_records_have_required_fields(self):
        facts = self._make_facts()
        records = extract_financial_records("AAPL", facts, backfill_years=5, as_of=date(2024, 1, 1))
        required = {"symbol", "report_date", "metric_name", "metric_value",
                    "currency", "period_type", "source", "value_source", "publish_date",
                    "publish_date_source"}
        for r in records:
            assert required.issubset(r.keys()), f"Missing fields: {r}"

    def test_records_mark_edgar_as_publish_date_source(self):
        facts = self._make_facts()
        records = extract_financial_records("AAPL", facts, backfill_years=5, as_of=date(2024, 1, 1))
        assert records
        assert all(r["publish_date_source"] == "edgar_xbrl" for r in records)

    def test_symbol_set_correctly(self):
        facts = self._make_facts()
        records = extract_financial_records("TSLA", facts, as_of=date(2024, 1, 1))
        for r in records:
            assert r["symbol"] == "TSLA"


# ---------------------------------------------------------------------------
# run_edgar_extraction
# ---------------------------------------------------------------------------

class TestRunEdgarExtraction:
    def test_processes_all_symbols(self):
        fake_facts = {"facts": {"us-gaap": {}}}
        fake_records = [
            {
                "symbol": "AAPL",
                "report_date": date(2022, 12, 31),
                "metric_name": "total_assets",
                "metric_value": 1e9,
                "currency": "USD",
                "period_type": "annual",
                "source": "edgar_xbrl",
                "publish_date": date(2023, 2, 3),
                "as_of": date(2024, 1, 1),
                "metric_definition": "provider_reported",
            }
        ]
        with patch("modules.extract.edgar_xbrl.fetch_company_facts", return_value=fake_facts), \
             patch("modules.extract.edgar_xbrl.extract_financial_records", return_value=fake_records):
            result = run_edgar_extraction(
                ["AAPL", "MSFT"],
                backfill_years=1,
                as_of=date(2024, 1, 1),
            )
        assert len(result) == 2  # 1 record × 2 symbols

    def test_skips_symbols_with_no_facts(self):
        with patch("modules.extract.edgar_xbrl.fetch_company_facts", return_value=None):
            result = run_edgar_extraction(["UNKN"], backfill_years=1)
        assert result == []

    def test_empty_symbols_returns_empty(self):
        result = run_edgar_extraction([], backfill_years=1)
        assert result == []
