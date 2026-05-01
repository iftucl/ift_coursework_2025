"""Unit tests for Pipeline C composite factor model module."""

import numpy as np
import pandas as pd
import pytest
from modules.factor.factor_model import (
    _assign_groups,
    _to_zscore,
    _winsorise,
    apply_eligibility_filter,
    compute_composite,
    compute_quality_score,
    compute_raw_metrics,
    compute_value_score,
    run_factor_pipeline,
    run_value_factor,
    score_all_metrics,
)


def _sample_df(n=6):
    """Minimal eligible universe: all EPS > 0, no Financials/Real Estate."""
    return pd.DataFrame(
        {
            "symbol": [f"SYM{i}" for i in range(n)],
            "gics_sector": [
                "Technology",
                "Technology",
                "Health Care",
                "Industrials",
                "Energy",
                "Technology",
            ],
            "closing_price": [100.0, 50.0, 200.0, 80.0, 60.0, 120.0],
            "shares_outstanding": [1_000_000, 2_000_000, 500_000, 1_500_000, 1_200_000, 800_000],
            "total_assets": [500e6, 300e6, 800e6, 200e6, 400e6, 600e6],
            "total_liabilities": [200e6, 250e6, 400e6, 100e6, 150e6, 250e6],
            "net_income_ttm": [10e6, 8e6, 30e6, 6e6, 12e6, 20e6],
            "ebitda_ttm": [20e6, 15e6, 50e6, 10e6, 18e6, 35e6],
            "total_debt": [50e6, 80e6, 100e6, 30e6, 60e6, 70e6],
            "cash_and_equivalents": [10e6, 5e6, 20e6, 8e6, 12e6, 15e6],
            "book_value": [300e6, 50e6, 400e6, 100e6, 250e6, 350e6],
            "revenue": [120e6, 100e6, 300e6, 80e6, 150e6, 200e6],
            "gross_profit": [60e6, 45e6, 150e6, 35e6, 70e6, 100e6],
            "free_cash_flow": [8e6, 6e6, 25e6, 5e6, 10e6, 18e6],
            "current_assets": [80e6, 40e6, 120e6, 50e6, 90e6, 110e6],
            "current_liabilities": [40e6, 35e6, 60e6, 25e6, 45e6, 55e6],
            "annual_dividend_rate": [0.96, 0.0, 1.20, 0.0, 0.60, 0.0],
        }
    )


# ---------------------------------------------------------------------------
# apply_eligibility_filter
# ---------------------------------------------------------------------------


class TestEligibilityFilter:
    def test_removes_eps_negative(self):
        df = _sample_df()
        df.loc[0, "net_income_ttm"] = -1e6  # negative EPS
        result = apply_eligibility_filter(df)
        assert "SYM0" not in result["symbol"].values

    def test_removes_financials_sector(self):
        df = _sample_df()
        df.loc[1, "gics_sector"] = "Financials"
        result = apply_eligibility_filter(df)
        assert "SYM1" not in result["symbol"].values

    def test_removes_real_estate_sector(self):
        df = _sample_df()
        df.loc[2, "gics_sector"] = "Real Estate"
        result = apply_eligibility_filter(df)
        assert "SYM2" not in result["symbol"].values

    def test_eligible_companies_kept(self):
        df = _sample_df()
        result = apply_eligibility_filter(df)
        assert len(result) == len(df)

    def test_index_is_reset_after_filter(self):
        df = _sample_df()
        df.loc[0, "net_income_ttm"] = -1e6
        result = apply_eligibility_filter(df)
        assert list(result.index) == list(range(len(result)))


# ---------------------------------------------------------------------------
# compute_raw_metrics
# ---------------------------------------------------------------------------


class TestComputeRawMetrics:
    def test_bp_equals_book_over_price(self):
        df = compute_raw_metrics(_sample_df())
        expected = 300e6 / 100.0
        assert df.loc[0, "bp"] == pytest.approx(expected)

    def test_bp_nan_when_book_value_zero(self):
        df = _sample_df()
        df.loc[0, "book_value"] = 0.0
        result = compute_raw_metrics(df)
        assert np.isnan(result.loc[0, "bp"])

    def test_dy_zero_for_non_payers(self):
        df = compute_raw_metrics(_sample_df())
        assert df.loc[1, "dy"] == pytest.approx(0.0)

    def test_dy_nonzero_for_payers(self):
        df = compute_raw_metrics(_sample_df())
        # SYM0: annual_dividend_rate=0.96, price=100 -> dy=0.0096
        assert df.loc[0, "dy"] == pytest.approx(0.96 / 100.0)

    def test_wca_is_current_ratio(self):
        df = compute_raw_metrics(_sample_df())
        expected = 80e6 / 40e6
        assert df.loc[0, "wca"] == pytest.approx(expected)

    def test_ltde_is_negative_leverage(self):
        df = compute_raw_metrics(_sample_df())
        # SYM0: total_debt=50M, book_value=300M -> ltde = -50/300
        assert df.loc[0, "ltde"] == pytest.approx(-50e6 / 300e6)

    def test_roa_is_net_income_over_assets(self):
        df = compute_raw_metrics(_sample_df())
        assert df.loc[0, "roa"] == pytest.approx(10e6 / 500e6)

    def test_gpa_fallback_when_profit_margin_zero(self):
        df = _sample_df()
        df.loc[0, "net_income_ttm"] = 0.0  # profit_margin = 0 -> fallback to gross_margin
        result = compute_raw_metrics(df)
        # fallback: gross_margin = gross_profit / revenue = 60/120 = 0.5
        assert result.loc[0, "gpa"] == pytest.approx(60e6 / 120e6)


# ---------------------------------------------------------------------------
# score_all_metrics
# ---------------------------------------------------------------------------


class TestScoreAllMetrics:
    def test_z_score_columns_created(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        for col in ["z_bp", "z_ey", "z_cfy", "z_dy", "z_gpa", "z_wca", "z_ltde", "z_roa"]:
            assert col in df.columns

    def test_z_scores_are_finite_for_valid_metrics(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        for col in ["z_bp", "z_ey", "z_cfy", "z_gpa", "z_wca", "z_ltde", "z_roa"]:
            valid = df[col].dropna()
            assert np.all(np.isfinite(valid)), f"{col} has non-finite z-scores"

    def test_small_sector_pooled(self):
        # Two 1-firm sectors get pooled together (n=2), enabling z-scores
        df = _sample_df()
        df["gics_sector"] = [
            "Technology",
            "Technology",
            "Technology",
            "Technology",
            "Rare Sector A",
            "Rare Sector B",
        ]
        df = compute_raw_metrics(df)
        df = score_all_metrics(df)
        # Both small sectors end up in __pooled__ group with n=2 -> finite z-score
        for sym in ["SYM4", "SYM5"]:
            idx = df[df["symbol"] == sym].index[0]
            assert df.loc[idx, "__group__"] == "__pooled__"
            assert not np.isnan(df.loc[idx, "z_bp"])


# ---------------------------------------------------------------------------
# compute_value_score / compute_quality_score
# ---------------------------------------------------------------------------


class TestDimensionScores:
    def test_value_score_present(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        df = compute_value_score(df)
        assert "value_score" in df.columns
        assert df["value_score"].notna().any()

    def test_quality_score_present(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        df = compute_quality_score(df)
        assert "quality_score" in df.columns
        assert df["quality_score"].notna().any()

    def test_missing_metric_renormalises_weight(self):
        # If z_cfy is all NaN, value_score should still be computed from remaining 3
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        df["z_cfy"] = np.nan
        df = compute_value_score(df)
        assert df["value_score"].notna().all()


# ---------------------------------------------------------------------------
# compute_composite
# ---------------------------------------------------------------------------


class TestComputeComposite:
    def _full_pipeline_to_scores(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        df = compute_value_score(df)
        df = compute_quality_score(df)
        return df

    def test_composite_score_present(self):
        df = compute_composite(self._full_pipeline_to_scores())
        assert "composite_score" in df.columns
        assert df["composite_score"].notna().any()

    def test_composite_percentile_in_zero_one(self):
        df = compute_composite(self._full_pipeline_to_scores())
        valid = df["composite_percentile"].dropna()
        assert (valid >= 0).all() and (valid <= 1).all()

    def test_quintile_values_are_1_to_5(self):
        df = compute_composite(self._full_pipeline_to_scores())
        valid = df["quintile"].dropna()
        assert set(valid).issubset({1, 2, 3, 4, 5})

    def test_top_composite_score_gets_quintile_1(self):
        df = compute_composite(self._full_pipeline_to_scores())
        top_idx = df["composite_score"].idxmax()
        assert df.loc[top_idx, "quintile"] == 1

    def test_bottom_composite_score_gets_quintile_5(self):
        df = compute_composite(self._full_pipeline_to_scores())
        bot_idx = df["composite_score"].idxmin()
        assert df.loc[bot_idx, "quintile"] == 5


# ---------------------------------------------------------------------------
# run_factor_pipeline (end-to-end)
# ---------------------------------------------------------------------------


class TestRunFactorPipeline:
    def test_returns_all_expected_columns(self):
        df = run_factor_pipeline(_sample_df())
        expected = [
            "bp",
            "ey",
            "cfy",
            "dy",
            "gpa",
            "wca",
            "ltde",
            "roa",
            "z_bp",
            "z_ey",
            "z_cfy",
            "z_dy",
            "z_gpa",
            "z_wca",
            "z_ltde",
            "z_roa",
            "value_score",
            "quality_score",
            "composite_score",
            "composite_percentile",
            "quintile",
        ]
        for col in expected:
            assert col in df.columns, f"Missing column: {col}"

    def test_group_column_removed_from_output(self):
        df = run_factor_pipeline(_sample_df())
        assert "__group__" not in df.columns

    def test_composite_scores_not_all_nan(self):
        df = run_factor_pipeline(_sample_df())
        assert df["composite_score"].notna().any()

    def test_ineligible_companies_excluded(self):
        df_in = _sample_df()
        df_in.loc[0, "net_income_ttm"] = -5e6
        df_in.loc[1, "gics_sector"] = "Financials"
        result = run_factor_pipeline(df_in)
        assert "SYM0" not in result["symbol"].values
        assert "SYM1" not in result["symbol"].values


# ---------------------------------------------------------------------------
# compute_raw_metrics — additional metric coverage
# ---------------------------------------------------------------------------


class TestComputeRawMetricsExtra:
    def test_market_cap_is_price_times_shares(self):
        df = compute_raw_metrics(_sample_df())
        # SYM0: price=100, shares=1_000_000 -> market_cap=100_000_000
        assert df.loc[0, "market_cap"] == pytest.approx(100.0 * 1_000_000)

    def test_ey_is_eps_over_price(self):
        df = compute_raw_metrics(_sample_df())
        # SYM0: net_income=10M, shares=1M -> eps=10; price=100 -> ey=0.1
        assert df.loc[0, "ey"] == pytest.approx(10e6 / 1_000_000 / 100.0)

    def test_ey_nan_when_eps_zero(self):
        df = _sample_df()
        df.loc[0, "net_income_ttm"] = 0.0
        result = compute_raw_metrics(df)
        assert np.isnan(result.loc[0, "ey"])

    def test_cfy_is_fcf_over_market_cap(self):
        df = compute_raw_metrics(_sample_df())
        # SYM0: fcf=8M, market_cap=100*1M=100M -> cfy=0.08
        assert df.loc[0, "cfy"] == pytest.approx(8e6 / (100.0 * 1_000_000))

    def test_cfy_nan_when_fcf_missing(self):
        df = _sample_df()
        df.loc[0, "free_cash_flow"] = np.nan
        result = compute_raw_metrics(df)
        assert np.isnan(result.loc[0, "cfy"])

    def test_gpa_normal_case(self):
        df = compute_raw_metrics(_sample_df())
        # SYM0: gross_margin=60/120=0.5, roa=10/500=0.02, profit_margin=10/120=1/12
        # gpa = 0.5 * 0.02 / (1/12) = 0.01 * 12 = 0.12
        # equivalently: gross_profit / total_assets = 60/500 = 0.12
        assert df.loc[0, "gpa"] == pytest.approx(60e6 / 500e6)

    def test_bp_nan_when_book_value_negative(self):
        df = _sample_df()
        df.loc[0, "book_value"] = -1e6
        result = compute_raw_metrics(df)
        assert np.isnan(result.loc[0, "bp"])

    def test_london_stock_price_converted_from_pence_to_gbp(self):
        # .L stocks are quoted in pence (GBX); closing_price should be /100
        # before computing price-based metrics like bp.
        df = _sample_df()
        df.loc[0, "symbol"] = "RIO.L"
        # closing_price = 5000 GBX (pence) => effective price = 50 GBP
        df.loc[0, "closing_price"] = 5000.0
        df.loc[0, "book_value"] = 100e6
        result = compute_raw_metrics(df)
        # bp should use price=50, not 5000
        assert result.loc[0, "bp"] == pytest.approx(100e6 / 50.0)

    def test_non_london_stock_price_unchanged(self):
        # Non-.L stocks should not be divided by 100
        df = _sample_df()
        df.loc[0, "symbol"] = "AAPL"
        df.loc[0, "closing_price"] = 180.0
        df.loc[0, "book_value"] = 100e6
        result = compute_raw_metrics(df)
        assert result.loc[0, "bp"] == pytest.approx(100e6 / 180.0)

    def test_london_market_cap_uses_gbp_price(self):
        # market_cap for .L stock should use GBP price (pence / 100)
        df = _sample_df()
        df.loc[0, "symbol"] = "SHEL.L"
        df.loc[0, "closing_price"] = 2800.0  # 2800 GBX = 28 GBP
        df.loc[0, "shares_outstanding"] = 10_000_000
        result = compute_raw_metrics(df)
        assert result.loc[0, "market_cap"] == pytest.approx(28.0 * 10_000_000)


# ---------------------------------------------------------------------------
# _assign_groups
# ---------------------------------------------------------------------------


class TestAssignGroups:
    def test_large_sector_keeps_name(self):
        # Build a df where one sector has >= 5 firms
        df2 = pd.concat([_sample_df(), _sample_df()], ignore_index=True)
        df2["gics_sector"] = ["Technology"] * 5 + ["Energy"] * 7
        groups = _assign_groups(df2)
        assert (groups[df2["gics_sector"] == "Technology"] == "Technology").all()
        assert (groups[df2["gics_sector"] == "Energy"] == "Energy").all()

    def test_small_sector_becomes_pooled(self):
        df = _sample_df()
        # Only 1 company in "Rare" -> pooled
        df.loc[5, "gics_sector"] = "Rare"
        groups = _assign_groups(df)
        assert groups.iloc[5] == "__pooled__"

    def test_multiple_small_sectors_all_pooled(self):
        df = _sample_df()
        df["gics_sector"] = [
            "Technology",
            "Technology",
            "Technology",
            "Technology",
            "Rare A",
            "Rare B",
        ]
        groups = _assign_groups(df)
        assert groups.iloc[4] == "__pooled__"
        assert groups.iloc[5] == "__pooled__"


# ---------------------------------------------------------------------------
# _winsorise
# ---------------------------------------------------------------------------


class TestWinsorise:
    def test_outlier_clipped_to_95th_percentile(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0])  # 100 is outlier
        result = _winsorise(s)
        assert result.iloc[4] < 100.0  # clipped down

    def test_low_outlier_clipped_to_5th_percentile(self):
        s = pd.Series([-100.0, 2.0, 3.0, 4.0, 5.0])
        result = _winsorise(s)
        assert result.iloc[0] > -100.0  # clipped up

    def test_non_outliers_unchanged(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _winsorise(s)
        assert result.iloc[2] == pytest.approx(3.0)  # middle value unchanged

    def test_returns_series_when_fewer_than_2_valid(self):
        s = pd.Series([np.nan, np.nan, 1.0])
        result = _winsorise(s)
        # Only 1 valid value, returns series unchanged
        assert result.iloc[2] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _to_zscore
# ---------------------------------------------------------------------------


class TestToZscore:
    def test_output_length_matches_input(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _to_zscore(s)
        assert len(result) == len(s)

    def test_scores_are_symmetric_around_zero(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _to_zscore(s)
        assert result.mean() == pytest.approx(0.0, abs=1e-10)

    def test_highest_value_gets_positive_zscore(self):
        s = pd.Series([1.0, 2.0, 3.0])
        result = _to_zscore(s)
        assert result.iloc[2] > 0

    def test_lowest_value_gets_negative_zscore(self):
        s = pd.Series([1.0, 2.0, 3.0])
        result = _to_zscore(s)
        assert result.iloc[0] < 0

    def test_all_nan_when_fewer_than_2_valid(self):
        s = pd.Series([1.0, np.nan, np.nan])
        result = _to_zscore(s)
        assert result.isna().all()

    def test_nan_inputs_remain_nan_in_output(self):
        s = pd.Series([1.0, np.nan, 3.0, 4.0, 5.0])
        result = _to_zscore(s)
        assert np.isnan(result.iloc[1])


# ---------------------------------------------------------------------------
# compute_composite — fallback when one dimension missing
# ---------------------------------------------------------------------------


class TestCompositeFallback:
    def test_fallback_to_value_when_quality_all_nan(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        df = compute_value_score(df)
        df = compute_quality_score(df)
        df["quality_score"] = np.nan  # wipe quality
        result = compute_composite(df)
        # Should still produce composite from value alone
        assert result["composite_score"].notna().any()

    def test_fallback_to_quality_when_value_all_nan(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        df = compute_value_score(df)
        df = compute_quality_score(df)
        df["value_score"] = np.nan  # wipe value
        result = compute_composite(df)
        assert result["composite_score"].notna().any()

    def test_highest_percentile_is_one(self):
        df = compute_raw_metrics(_sample_df())
        df = score_all_metrics(df)
        df = compute_value_score(df)
        df = compute_quality_score(df)
        result = compute_composite(df)
        assert result["composite_percentile"].max() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# run_value_factor backward-compat alias
# ---------------------------------------------------------------------------


class TestBackwardCompatAlias:
    def test_run_value_factor_is_alias_for_run_factor_pipeline(self):
        df1 = run_factor_pipeline(_sample_df())
        df2 = run_value_factor(_sample_df())
        pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))
