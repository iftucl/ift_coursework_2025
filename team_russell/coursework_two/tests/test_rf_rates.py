"""Tests for _rf_rates.py — mean_rf_annual, get_rf_annual, get_rf_quarterly, rf_quarterly_series."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _rf_rates as rf

# ── mean_rf_annual ────────────────────────────────────────────────────────────


class TestMeanRfAnnual:
    def test_returns_float(self):
        assert isinstance(rf.mean_rf_annual(), float)

    def test_covers_all_40_periods(self):
        # mean = sum / count, so count must equal 40
        assert len(rf._RF_TABLE) == 40

    def test_value_between_zero_and_ten_percent(self):
        # Sanity: mean T-bill rate should be between 0% and 10%
        assert 0.0 < rf.mean_rf_annual() < 0.10

    def test_approximately_two_percent(self):
        # Historically ~2.17% over Dec 2015–Sep 2025
        assert pytest.approx(rf.mean_rf_annual(), abs=0.005) == 0.0217


# ── get_rf_annual ─────────────────────────────────────────────────────────────


class TestGetRfAnnual:
    def test_known_date_string(self):
        assert rf.get_rf_annual("2022-12-31") == pytest.approx(0.0442)

    def test_known_date_timestamp(self):
        assert rf.get_rf_annual(pd.Timestamp("2022-12-31")) == pytest.approx(0.0442)

    def test_near_zero_era(self):
        # 2021 rates should be near zero
        assert rf.get_rf_annual("2021-03-31") < 0.001

    def test_high_rate_era(self):
        # 2024 peak should be above 5%
        assert rf.get_rf_annual("2024-03-31") > 0.05

    def test_first_period(self):
        assert rf.get_rf_annual("2015-12-31") == pytest.approx(0.0016)

    def test_last_period(self):
        assert rf.get_rf_annual("2025-09-30") == pytest.approx(0.0420)

    def test_unknown_date_falls_back_to_mean(self):
        fallback = rf.get_rf_annual("2000-01-01")
        assert fallback == pytest.approx(rf.mean_rf_annual())

    def test_all_rates_positive(self):
        for date, rate in rf._RF_TABLE.items():
            assert rate > 0, f"{date} has non-positive rate {rate}"

    def test_all_rates_below_ten_percent(self):
        for date, rate in rf._RF_TABLE.items():
            assert rate < 0.10, f"{date} has implausibly high rate {rate}"


# ── get_rf_quarterly ──────────────────────────────────────────────────────────


class TestGetRfQuarterly:
    def test_equals_annual_divided_by_four(self):
        annual = rf.get_rf_annual("2023-06-30")
        assert rf.get_rf_quarterly("2023-06-30") == pytest.approx(annual / 4)

    def test_returns_float(self):
        assert isinstance(rf.get_rf_quarterly("2022-03-31"), float)

    def test_value_is_smaller_than_annual(self):
        assert rf.get_rf_quarterly("2024-03-31") < rf.get_rf_annual("2024-03-31")

    def test_unknown_date_fallback(self):
        expected = rf.mean_rf_annual() / 4
        assert rf.get_rf_quarterly("1999-01-01") == pytest.approx(expected)


# ── rf_quarterly_series ───────────────────────────────────────────────────────


class TestRfQuarterlySeries:
    def test_accepts_pd_index(self):
        idx = pd.Index(["2022-03-31", "2022-06-30", "2022-09-30"])
        result = rf.rf_quarterly_series(idx)
        assert isinstance(result, pd.Series)
        assert len(result) == 3

    def test_accepts_pd_series(self):
        s = pd.Series(["2022-03-31", "2022-06-30"])
        result = rf.rf_quarterly_series(s)
        assert isinstance(result, pd.Series)
        assert len(result) == 2

    def test_accepts_list(self):
        result = rf.rf_quarterly_series(["2023-03-31", "2023-06-30"])
        assert isinstance(result, pd.Series)
        assert len(result) == 2

    def test_accepts_timestamps(self):
        dates = [pd.Timestamp("2022-03-31"), pd.Timestamp("2022-06-30")]
        result = rf.rf_quarterly_series(dates)
        assert len(result) == 2

    def test_index_preserved_for_pd_index(self):
        idx = pd.DatetimeIndex(["2022-03-31", "2022-06-30"])
        result = rf.rf_quarterly_series(idx)
        assert list(result.index) == list(idx)

    def test_values_equal_get_rf_quarterly(self):
        dates = ["2022-03-31", "2022-06-30", "2022-09-30"]
        result = rf.rf_quarterly_series(dates)
        for i, d in enumerate(dates):
            assert result.iloc[i] == pytest.approx(rf.get_rf_quarterly(d))

    def test_all_values_positive(self):
        dates = list(rf._RF_TABLE.keys())
        result = rf.rf_quarterly_series(dates)
        assert (result > 0).all()

    def test_high_rate_period_larger_than_low_rate_period(self):
        dates = pd.Series(["2021-03-31", "2024-03-31"])
        result = rf.rf_quarterly_series(dates)
        assert result.iloc[1] > result.iloc[0]

    def test_length_matches_input(self):
        dates = list(rf._RF_TABLE.keys())
        result = rf.rf_quarterly_series(dates)
        assert len(result) == 40
