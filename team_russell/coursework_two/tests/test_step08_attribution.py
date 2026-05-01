"""Tests for step08_factor_attribution.py — quintile assignment, returns, stats."""

import numpy as np
import pandas as pd
import pytest
import step08_factor_attribution as s08

# ── shared fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def attribution_df():
    """Full returns DataFrame with all three individual factor scores."""
    np.random.seed(8)
    periods = [
        (
            pd.Timestamp("2022-03-31") + pd.DateOffset(months=3 * i),
            pd.Timestamp("2022-06-30") + pd.DateOffset(months=3 * i),
        )
        for i in range(4)
    ]
    rows = []
    for s, e in periods:
        for i in range(50):
            gross = np.random.uniform(-0.05, 0.12)
            rows.append(
                {
                    "symbol": f"SYM{i:03d}",
                    "start_date": s,
                    "end_date": e,
                    "quintile": (i // 10) + 1,
                    "composite_score": np.random.randn(),
                    "value_score": np.random.uniform(0, 1),
                    "quality_score": np.random.uniform(0, 1),
                    "momentum_score": np.random.randn(),
                    "gross_return": gross,
                    "net_return": gross - 0.004,
                    "gics_sector": "Technology",
                }
            )
    return pd.DataFrame(rows)


# ── assign_single_factor_quintiles ────────────────────────────────────────────


class TestAssignSingleFactorQuintiles:
    def test_adds_three_quintile_columns(self, attribution_df):
        result = s08.assign_single_factor_quintiles(attribution_df)
        for col in ["value_quintile", "quality_quintile", "momentum_quintile"]:
            assert col in result.columns

    def test_quintile_values_are_1_to_5(self, attribution_df):
        result = s08.assign_single_factor_quintiles(attribution_df)
        for col in ["value_quintile", "quality_quintile", "momentum_quintile"]:
            valid = result[col].dropna().astype(int)
            assert set(valid.unique()).issubset({1, 2, 3, 4, 5})

    def test_top_value_score_is_q1(self, attribution_df):
        # Highest value_score within a period should be in quintile 1
        result = s08.assign_single_factor_quintiles(attribution_df)
        first_period = result[result["start_date"] == result["start_date"].min()]
        top_idx = first_period["value_score"].idxmax()
        assert first_period.loc[top_idx, "value_quintile"] == 1

    def test_bottom_value_score_is_q5(self, attribution_df):
        result = s08.assign_single_factor_quintiles(attribution_df)
        first_period = result[result["start_date"] == result["start_date"].min()]
        bot_idx = first_period["value_score"].idxmin()
        assert first_period.loc[bot_idx, "value_quintile"] == 5

    def test_returns_dataframe(self, attribution_df):
        result = s08.assign_single_factor_quintiles(attribution_df)
        assert isinstance(result, pd.DataFrame)

    def test_row_count_unchanged(self, attribution_df):
        result = s08.assign_single_factor_quintiles(attribution_df)
        assert len(result) == len(attribution_df)

    def test_fewer_than_10_valid_scores_gives_nan_quintile(self):
        """With fewer than 10 non-null factor values, quintile is set to NaN."""
        df = pd.DataFrame(
            {
                "symbol": [f"S{i}" for i in range(5)],
                "start_date": [pd.Timestamp("2022-03-31")] * 5,
                "end_date": [pd.Timestamp("2022-06-30")] * 5,
                "quintile": [1, 2, 3, 4, 5],
                "composite_score": [0.5] * 5,
                "value_score": [0.1, 0.2, 0.3, 0.4, 0.5],  # only 5 valid
                "quality_score": [0.5, 0.4, 0.3, 0.2, 0.1],
                "momentum_score": [1.0, 0.5, 0.0, -0.5, -1.0],
                "gross_return": [0.02] * 5,
                "net_return": [0.016] * 5,
                "gics_sector": ["Technology"] * 5,
            }
        )
        result = s08.assign_single_factor_quintiles(df)
        # All quintile columns should be NaN since n < 10
        for col in ["value_quintile", "quality_quintile", "momentum_quintile"]:
            assert result[col].isna().all()


# ── compute_portfolio_returns ─────────────────────────────────────────────────


class TestComputePortfolioReturns:
    def test_returns_dataframe(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        result = s08.compute_portfolio_returns(df)
        assert isinstance(result, pd.DataFrame)

    def test_one_row_per_period(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        result = s08.compute_portfolio_returns(df)
        n_periods = attribution_df["start_date"].nunique()
        assert len(result) == n_periods

    def test_composite_column_present(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        result = s08.compute_portfolio_returns(df)
        # Column is named "3F Composite" in actual implementation
        assert "3F Composite" in result.columns

    def test_value_column_present(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        result = s08.compute_portfolio_returns(df)
        # Column is named "Value Only" in actual implementation
        assert "Value Only" in result.columns

    def test_returns_are_numeric(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        result = s08.compute_portfolio_returns(df)
        assert result["3F Composite"].dtype in [np.float64, np.float32, float]


# ── compute_stats ─────────────────────────────────────────────────────────────


class TestComputeStats:
    def test_returns_dataframe(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        port_df = s08.compute_portfolio_returns(df)
        result = s08.compute_stats(port_df)
        assert isinstance(result, pd.DataFrame)

    def test_has_sharpe_column(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        port_df = s08.compute_portfolio_returns(df)
        result = s08.compute_stats(port_df)
        assert "Sharpe" in result.columns

    def test_has_sortino_column(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        port_df = s08.compute_portfolio_returns(df)
        result = s08.compute_stats(port_df)
        assert "Sortino" in result.columns

    def test_one_row_per_portfolio(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        port_df = s08.compute_portfolio_returns(df)
        result = s08.compute_stats(port_df)
        # Should have one row per portfolio type (Value, Quality, Momentum, 3F, EW)
        assert len(result) >= 4

    def test_ann_vol_is_positive(self, attribution_df):
        df = s08.assign_single_factor_quintiles(attribution_df)
        port_df = s08.compute_portfolio_returns(df)
        result = s08.compute_stats(port_df)
        vol_col = [c for c in result.columns if "Vol" in c][0]
        assert (result[vol_col].dropna() >= 0).all()
