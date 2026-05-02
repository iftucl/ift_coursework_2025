"""Tests for pure computation functions in step02_extend_2015.py."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
import step02_extend_2015 as s02

# ── _clean ────────────────────────────────────────────────────────────────────


class TestClean:
    def test_integer_returns_float(self):
        assert s02._clean(5) == 5.0
        assert isinstance(s02._clean(5), float)

    def test_float_passthrough(self):
        assert s02._clean(3.14) == pytest.approx(3.14)

    def test_none_returns_none(self):
        assert s02._clean(None) is None

    def test_nan_returns_none(self):
        assert s02._clean(float("nan")) is None

    def test_pos_inf_returns_none(self):
        assert s02._clean(float("inf")) is None

    def test_neg_inf_returns_none(self):
        assert s02._clean(float("-inf")) is None

    def test_zero_returns_zero(self):
        assert s02._clean(0) == 0.0

    def test_negative_float(self):
        assert s02._clean(-2.5) == pytest.approx(-2.5)

    def test_string_returns_none(self):
        assert s02._clean("abc") is None

    def test_numeric_string_converts(self):
        assert s02._clean("3.14") == pytest.approx(3.14)


# ── _assign_groups ────────────────────────────────────────────────────────────


class TestAssignGroups:
    def test_large_sectors_kept(self):
        sectors = pd.Series(["Tech"] * 10 + ["Finance"] * 8)
        result = s02._assign_groups(sectors)
        assert "Tech" in result.values
        assert "Finance" in result.values
        assert "__pooled__" not in result.values

    def test_small_sectors_pooled(self):
        sectors = pd.Series(["Tech"] * 10 + ["Tiny"] * 2)
        result = s02._assign_groups(sectors)
        assert "__pooled__" in result.values
        assert "Tiny" not in result.values

    def test_boundary_exactly_at_min_not_pooled(self):
        # SMALL_SECTOR_MIN = 5; a sector with exactly 5 entries should NOT be pooled
        sectors = pd.Series(["Large"] * 10 + ["Edge"] * s02.SMALL_SECTOR_MIN)
        result = s02._assign_groups(sectors)
        assert "Edge" in result.values
        assert "__pooled__" not in result.values

    def test_all_small_all_pooled(self):
        sectors = pd.Series(["A"] * 2 + ["B"] * 2 + ["C"] * 1)
        result = s02._assign_groups(sectors)
        assert set(result.values) == {"__pooled__"}

    def test_preserves_index(self):
        sectors = pd.Series(["Tech"] * 10 + ["Tiny"] * 2, index=range(12))
        result = s02._assign_groups(sectors)
        assert list(result.index) == list(sectors.index)


# ── _winsorise ────────────────────────────────────────────────────────────────


class TestWinsorise:
    def test_clips_upper_outlier(self):
        s = pd.Series(list(range(100)) + [10_000])
        result = s02._winsorise(s)
        assert result.max() < 10_000

    def test_clips_lower_outlier(self):
        s = pd.Series(list(range(100)) + [-10_000])
        result = s02._winsorise(s)
        assert result.min() > -10_000

    def test_middle_values_unchanged(self):
        s = pd.Series(list(range(100)))
        result = s02._winsorise(s)
        # Median value (50) should be identical
        assert result.iloc[50] == 50

    def test_all_same_values_unchanged(self):
        s = pd.Series([5.0] * 20)
        result = s02._winsorise(s)
        assert (result == 5.0).all()

    def test_length_preserved(self):
        s = pd.Series(np.random.randn(50))
        result = s02._winsorise(s)
        assert len(result) == 50

    def test_single_value_returns_unchanged(self):
        s = pd.Series([3.0])
        result = s02._winsorise(s)
        assert len(result) == 1


# ── _to_zscore ────────────────────────────────────────────────────────────────


class TestToZscore:
    def test_output_length_matches_input(self):
        s = pd.Series(np.random.randn(20))
        assert len(s02._to_zscore(s)) == 20

    def test_monotonically_increasing(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = s02._to_zscore(s)
        diffs = result.diff().dropna()
        assert (diffs > 0).all()

    def test_nan_in_nan_out(self):
        s = pd.Series([1.0, np.nan, 3.0, 4.0, 5.0])
        result = s02._to_zscore(s)
        assert np.isnan(result.iloc[1])

    def test_non_nan_values_computed(self):
        s = pd.Series([1.0, np.nan, 3.0, 4.0, 5.0])
        result = s02._to_zscore(s)
        assert not np.isnan(result.iloc[0])

    def test_single_value_returns_nan(self):
        s = pd.Series([5.0])
        result = s02._to_zscore(s)
        assert np.isnan(result.iloc[0])

    def test_two_values_no_nan(self):
        s = pd.Series([1.0, 2.0])
        result = s02._to_zscore(s)
        assert result.notna().all()


# ── sector_neutral_zscore ─────────────────────────────────────────────────────


class TestSectorNeutralZscore:
    def test_output_length_matches_input(self):
        values = pd.Series(range(20), dtype=float)
        sectors = pd.Series(["Tech"] * 10 + ["Finance"] * 10)
        result = s02.sector_neutral_zscore(values, sectors)
        assert len(result) == 20

    def test_returns_series(self):
        values = pd.Series(range(10), dtype=float)
        sectors = pd.Series(["A"] * 5 + ["B"] * 5)
        result = s02.sector_neutral_zscore(values, sectors)
        assert isinstance(result, pd.Series)

    def test_within_sector_monotonicity(self):
        # Within each sector, higher value → higher z-score
        values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0])
        sectors = pd.Series(["A"] * 5 + ["B"] * 5)
        result = s02.sector_neutral_zscore(values, sectors)
        assert result.iloc[0] < result.iloc[1] < result.iloc[2]
        assert result.iloc[5] < result.iloc[6] < result.iloc[7]

    def test_small_sector_pooled_and_scored(self):
        # Two stocks in Tiny sector — pooled with others
        values = pd.Series(list(range(12)), dtype=float)
        sectors = pd.Series(["Large"] * 10 + ["Tiny"] * 2)
        result = s02.sector_neutral_zscore(values, sectors)
        assert result.notna().sum() > 0

    def test_nan_input_produces_nan_output(self):
        values = pd.Series([1.0, np.nan, 3.0, 4.0, 5.0] * 2)
        sectors = pd.Series(["A"] * 5 + ["B"] * 5)
        result = s02.sector_neutral_zscore(values, sectors)
        assert isinstance(result, pd.Series)


# ── _normalise_01 ─────────────────────────────────────────────────────────────


class TestNormalise01:
    def test_min_is_zero(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = s02._normalise_01(s)
        assert result.min() == pytest.approx(0.0)

    def test_max_is_one(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = s02._normalise_01(s)
        assert result.max() == pytest.approx(1.0)

    def test_monotonically_increasing(self):
        s = pd.Series([1.0, 2.0, 3.0])
        result = s02._normalise_01(s)
        assert result.iloc[0] < result.iloc[1] < result.iloc[2]

    def test_all_same_returns_half(self):
        s = pd.Series([7.0] * 5)
        result = s02._normalise_01(s)
        assert (result == 0.5).all()

    def test_negative_values(self):
        s = pd.Series([-3.0, 0.0, 3.0])
        result = s02._normalise_01(s)
        assert result.min() == pytest.approx(0.0)
        assert result.max() == pytest.approx(1.0)

    def test_length_preserved(self):
        s = pd.Series(np.random.randn(30))
        assert len(s02._normalise_01(s)) == 30


# ── build_composite ───────────────────────────────────────────────────────────


class TestBuildComposite:
    @pytest.fixture
    def composite_df(self):
        np.random.seed(1)
        n = 100
        return pd.DataFrame(
            {
                "symbol": [f"SYM{i:03d}" for i in range(n)],
                "value_score": np.random.uniform(0, 1, n),
                "quality_score": np.random.uniform(0, 1, n),
                "momentum_score": np.random.randn(n),
            }
        )

    def test_composite_score_column_added(self, composite_df):
        result = s02.build_composite(composite_df)
        assert "composite_score" in result.columns

    def test_quintile_column_added(self, composite_df):
        result = s02.build_composite(composite_df)
        assert "quintile" in result.columns

    def test_composite_percentile_column_added(self, composite_df):
        result = s02.build_composite(composite_df)
        assert "composite_percentile" in result.columns

    def test_quintiles_are_1_to_5(self, composite_df):
        result = s02.build_composite(composite_df)
        valid = result["quintile"].dropna().astype(int)
        assert set(valid.unique()).issubset({1, 2, 3, 4, 5})

    def test_q1_has_higher_score_than_q5(self, composite_df):
        result = s02.build_composite(composite_df)
        q1_mean = result[result["quintile"] == 1]["composite_score"].mean()
        q5_mean = result[result["quintile"] == 5]["composite_score"].mean()
        assert q1_mean > q5_mean

    def test_with_some_nan_scores(self):
        n = 50
        df = pd.DataFrame(
            {
                "value_score": [np.nan if i % 5 == 0 else float(i) / n for i in range(n)],
                "quality_score": np.random.uniform(0, 1, n),
                "momentum_score": np.random.randn(n),
            }
        )
        result = s02.build_composite(df)
        assert "composite_score" in result.columns
        assert result["quintile"].notna().sum() > 0

    def test_all_nan_returns_nan_quintile(self):
        df = pd.DataFrame(
            {
                "value_score": [np.nan] * 10,
                "quality_score": [np.nan] * 10,
                "momentum_score": [np.nan] * 10,
            }
        )
        result = s02.build_composite(df)
        assert result["quintile"].isna().all()


# ── price_on_or_before / price_on_or_after ────────────────────────────────────


class TestPriceHelpers:
    @pytest.fixture
    def price_series(self):
        dates = pd.date_range("2020-01-02", periods=250, freq="B")
        return pd.Series(np.linspace(100.0, 125.0, 250), index=dates)

    def test_price_on_or_before_exact_date(self, price_series):
        result = s02.price_on_or_before(price_series, "2020-01-02")
        assert isinstance(result, float)
        assert result == pytest.approx(100.0)

    def test_price_on_or_before_before_series_returns_none(self, price_series):
        assert s02.price_on_or_before(price_series, "2019-01-01") is None

    def test_price_on_or_before_midpoint(self, price_series):
        result = s02.price_on_or_before(price_series, "2020-06-01")
        assert result is not None
        assert 100.0 <= result <= 125.0

    def test_price_on_or_after_exact_date(self, price_series):
        result = s02.price_on_or_after(price_series, "2020-01-02")
        assert isinstance(result, float)
        assert result == pytest.approx(100.0)

    def test_price_on_or_after_after_series_returns_none(self, price_series):
        assert s02.price_on_or_after(price_series, "2025-01-01") is None

    def test_price_on_or_after_midpoint(self, price_series):
        result = s02.price_on_or_after(price_series, "2020-06-01")
        assert result is not None
        assert 100.0 <= result <= 125.0


# ── compute_momentum ──────────────────────────────────────────────────────────


class TestComputeMomentum:
    @pytest.fixture
    def prices_dict(self):
        dates = pd.date_range("2019-12-01", periods=400, freq="B")
        return {
            "AAPL": pd.Series(np.linspace(100, 130, 400), index=dates),
            "MSFT": pd.Series(np.linspace(200, 180, 400), index=dates),  # falling
        }

    def test_positive_momentum_for_rising_stock(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_momentum(prices_dict, ["AAPL"], r_dt)
        assert "AAPL" in result
        assert result["AAPL"] > 0

    def test_negative_momentum_for_falling_stock(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_momentum(prices_dict, ["MSFT"], r_dt)
        assert "MSFT" in result
        assert result["MSFT"] < 0

    def test_missing_symbol_returns_nan(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_momentum(prices_dict, ["UNKNOWN"], r_dt)
        assert np.isnan(result["UNKNOWN"])

    def test_returns_dict(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_momentum(prices_dict, ["AAPL"], r_dt)
        assert isinstance(result, dict)


# ── compute_low_vol ───────────────────────────────────────────────────────────


class TestComputeLowVol:
    @pytest.fixture
    def prices_dict(self):
        dates = pd.date_range("2019-01-01", periods=600, freq="B")
        np.random.seed(7)
        low_vol_prices = pd.Series(
            100 * np.cumprod(1 + np.random.normal(0, 0.005, 600)), index=dates
        )
        high_vol_prices = pd.Series(
            100 * np.cumprod(1 + np.random.normal(0, 0.03, 600)), index=dates
        )
        return {"LOW": low_vol_prices, "HIGH": high_vol_prices}

    def test_returns_dict(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_low_vol(prices_dict, ["LOW", "HIGH"], r_dt)
        assert isinstance(result, dict)

    def test_low_vol_stock_has_smaller_vol(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_low_vol(prices_dict, ["LOW", "HIGH"], r_dt)
        assert result["LOW"] < result["HIGH"]

    def test_vol_is_positive(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_low_vol(prices_dict, ["LOW"], r_dt)
        assert result["LOW"] > 0

    def test_missing_symbol_returns_nan(self, prices_dict):
        r_dt = date(2020, 12, 31)
        result = s02.compute_low_vol(prices_dict, ["MISSING"], r_dt)
        assert np.isnan(result["MISSING"])

    def test_too_short_window_returns_nan(self):
        # Only 5 days of data — less than MIN_DAYS (20) → nan
        dates = pd.date_range("2020-12-20", periods=5, freq="B")
        tiny = {"TINY": pd.Series([100.0, 101.0, 99.0, 100.5, 100.2], index=dates)}
        r_dt = date(2020, 12, 31)
        result = s02.compute_low_vol(tiny, ["TINY"], r_dt)
        assert np.isnan(result["TINY"])


class TestComputeMomentumBranches:
    def test_price_before_unavailable_returns_nan(self):
        # Symbol exists but the 13-month look-back date is before the series starts
        # → p_den is None → returns nan
        dates = pd.date_range("2020-12-01", periods=30, freq="B")
        # Only 30 days — skip_dt ~30 days ago is at start, start_dt ~13 months ago is before series
        prices = {"SYM": pd.Series(np.linspace(100, 110, 30), index=dates)}
        r_dt = date(2020, 12, 31)
        result = s02.compute_momentum(prices, ["SYM"], r_dt)
        assert np.isnan(result["SYM"])
