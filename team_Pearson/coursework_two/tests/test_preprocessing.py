"""Unit tests for CW2 preprocessing pipeline."""

import numpy as np
import pandas as pd
from team_Pearson.coursework_two.modules.feature.preprocessing import (
    neutralize_by_group,
    preprocess_cross_section,
    winsorize_cross_section,
    zscore_cross_section,
)


class TestWinsorize:
    def test_clips_extremes(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
        result = winsorize_cross_section(s, lower_pct=0.1, upper_pct=0.9)
        assert result.max() <= 100
        assert result.min() >= 1
        # The 100 should be clipped to 90th percentile
        assert result.iloc[-1] < 100

    def test_empty_series(self):
        s = pd.Series([], dtype=float)
        result = winsorize_cross_section(s)
        assert len(result) == 0

    def test_all_nan(self):
        s = pd.Series([np.nan, np.nan, np.nan])
        result = winsorize_cross_section(s)
        assert result.isna().all()

    def test_preserves_normal_values(self):
        s = pd.Series([10, 20, 30, 40, 50])
        result = winsorize_cross_section(s, lower_pct=0.0, upper_pct=1.0)
        pd.testing.assert_series_equal(result, s)


class TestNeutralize:
    def test_demeans_within_groups(self):
        df = pd.DataFrame(
            {
                "value": [10.0, 20.0, 30.0, 100.0, 200.0],
                "gics_sector": ["Tech", "Tech", "Tech", "Energy", "Energy"],
            }
        )
        result = neutralize_by_group(df, "value", "gics_sector")
        # Tech mean = 20, Energy mean = 150
        assert abs(result.iloc[0] - (-10.0)) < 1e-10
        assert abs(result.iloc[1] - 0.0) < 1e-10
        assert abs(result.iloc[2] - 10.0) < 1e-10
        assert abs(result.iloc[3] - (-50.0)) < 1e-10
        assert abs(result.iloc[4] - 50.0) < 1e-10

    def test_single_member_group_unchanged(self):
        df = pd.DataFrame(
            {
                "value": [10.0, 20.0, 30.0],
                "gics_sector": ["Tech", "Tech", "Solo"],
            }
        )
        result = neutralize_by_group(df, "value", "gics_sector")
        # Solo group has only 1 member — no neutralization
        assert result.iloc[2] == 30.0

    def test_missing_group_col(self):
        df = pd.DataFrame({"value": [1.0, 2.0, 3.0]})
        result = neutralize_by_group(df, "value", "nonexistent")
        pd.testing.assert_series_equal(result, df["value"])


class TestZscore:
    def test_standard_zscore(self):
        s = pd.Series([10, 20, 30, 40, 50])
        result = zscore_cross_section(s)
        assert abs(result.mean()) < 1e-10
        assert abs(result.std(ddof=1) - 1.0) < 1e-10

    def test_single_value_returns_nan(self):
        s = pd.Series([42.0])
        result = zscore_cross_section(s)
        assert result.isna().all()

    def test_constant_values_returns_nan(self):
        s = pd.Series([5.0, 5.0, 5.0, 5.0])
        result = zscore_cross_section(s)
        assert result.isna().all()

    def test_with_nans(self):
        s = pd.Series([10.0, np.nan, 30.0, 40.0])
        result = zscore_cross_section(s)
        assert pd.isna(result.iloc[1])
        valid = result.dropna()
        assert abs(valid.mean()) < 1e-10


class TestPreprocessCrossSection:
    def test_full_pipeline(self):
        df = pd.DataFrame(
            {
                "symbol": ["A", "B", "C", "D", "E", "F"],
                "raw_value": [10, 20, 30, 40, 50, 200],
                "gics_sector": ["Tech", "Tech", "Tech", "Energy", "Energy", "Energy"],
            }
        )
        result = preprocess_cross_section(df, lower_pct=0.05, upper_pct=0.95)

        assert "winsorized_value" in result.columns
        assert "neutralized_value" in result.columns
        assert "z_score" in result.columns
        # Extreme value (200) should be clipped
        assert result["winsorized_value"].max() < 200
        # Z-scores should be roughly centered
        z_valid = result["z_score"].dropna()
        if len(z_valid) > 1:
            assert abs(z_valid.mean()) < 0.5  # approximately centered

    def test_preserves_symbol_column(self):
        df = pd.DataFrame(
            {
                "symbol": ["X", "Y", "Z"],
                "raw_value": [1.0, 2.0, 3.0],
                "gics_sector": ["A", "A", "A"],
            }
        )
        result = preprocess_cross_section(df)
        assert list(result["symbol"]) == ["X", "Y", "Z"]

    def test_min_observations_blocks_zscore(self):
        df = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "raw_value": [1.0, 2.0, 3.0],
                "gics_sector": ["Tech", "Tech", "Energy"],
            }
        )
        result = preprocess_cross_section(df, min_observations=5)
        assert result["z_score"].isna().all()
