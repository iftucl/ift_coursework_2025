"""Tests for step09_long_short.py — build_ls and ann_stats."""

import numpy as np
import pandas as pd
import pytest
import step09_long_short as s09

# ── shared fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def raw_df():
    """Aggregated Q1/Q5 returns DataFrame matching load_data() output."""
    np.random.seed(9)
    n = 8
    dates_start = pd.date_range("2022-03-31", periods=n, freq="QE")
    dates_end = pd.date_range("2022-06-30", periods=n, freq="QE")
    return pd.DataFrame(
        {
            "start_date": dates_start,
            "end_date": dates_end,
            "q1_gross": np.random.uniform(-0.05, 0.12, n),
            "q5_gross": np.random.uniform(-0.05, 0.12, n),
            "bm_gross": np.random.uniform(-0.03, 0.10, n),
        }
    )


# ── build_ls ──────────────────────────────────────────────────────────────────


class TestBuildLs:
    def test_returns_dataframe(self, raw_df):
        result = s09.build_ls(raw_df)
        assert isinstance(result, pd.DataFrame)

    def test_same_row_count(self, raw_df):
        result = s09.build_ls(raw_df)
        assert len(result) == len(raw_df)

    def test_ls_return_column_present(self, raw_df):
        result = s09.build_ls(raw_df)
        assert "ls_return" in result.columns

    def test_q1_net_is_q1_gross_minus_tc(self, raw_df):
        result = s09.build_ls(raw_df)
        expected = raw_df["q1_gross"].values - s09.TC_RT
        np.testing.assert_allclose(result["q1_net"].values, expected)

    def test_q5_short_net_includes_borrow_cost(self, raw_df):
        result = s09.build_ls(raw_df)
        # q5_short_net = -q5_gross - BORROW_COST - TC_RT
        expected = -raw_df["q5_gross"].values - s09.BORROW_COST_PER_QUARTER - s09.TC_RT
        np.testing.assert_allclose(result["q5_short_net"].values, expected)

    def test_ls_return_is_average_of_legs(self, raw_df):
        result = s09.build_ls(raw_df)
        expected = (result["q1_net"] + result["q5_short_net"]) / 2
        pd.testing.assert_series_equal(
            result["ls_return"].round(10),
            expected.round(10),
            check_names=False,
        )

    def test_bm_net_is_bm_gross_minus_tc(self, raw_df):
        result = s09.build_ls(raw_df)
        expected = raw_df["bm_gross"].values - s09.TC_RT
        np.testing.assert_allclose(result["bm_net"].values, expected)

    def test_q5_outperforming_q1_gives_negative_ls(self):
        # If Q5 rises a lot, short leg loses money → negative L/S return
        df = pd.DataFrame(
            {
                "start_date": [pd.Timestamp("2022-03-31")],
                "end_date": [pd.Timestamp("2022-06-30")],
                "q1_gross": [0.01],
                "q5_gross": [0.15],  # Q5 strongly outperforms
                "bm_gross": [0.08],
            }
        )
        result = s09.build_ls(df)
        assert result.iloc[0]["ls_return"] < 0


def _rf_q(n, rate=0.005):
    """Constant quarterly rf Series of length n for test use (rate=0.005 ≈ 2% p.a.)."""
    return pd.Series(np.full(n, rate))


# ── ann_stats ─────────────────────────────────────────────────────────────────


class TestLsAnnStats:
    def test_returns_dict(self):
        s = pd.Series([0.03, -0.02, 0.05, 0.01, -0.03, 0.04])
        result = s09.ann_stats(s, _rf_q(len(s)))
        assert isinstance(result, dict)

    def test_required_keys(self):
        s = pd.Series([0.03, -0.02, 0.05, 0.01])
        result = s09.ann_stats(s, _rf_q(len(s)))
        for key in ["ann_ret", "ann_vol", "sharpe", "sortino", "hit_rate", "max_dd"]:
            assert key in result

    def test_hit_rate_between_0_and_1(self):
        s = pd.Series([0.03, -0.02, 0.05, 0.01, -0.03, 0.04])
        result = s09.ann_stats(s, _rf_q(len(s)))
        assert 0 <= result["hit_rate"] <= 1

    def test_hit_rate_all_positive(self):
        s = pd.Series([0.02, 0.03, 0.04, 0.05])
        result = s09.ann_stats(s, _rf_q(len(s)))
        assert result["hit_rate"] == pytest.approx(1.0)

    def test_hit_rate_all_negative(self):
        s = pd.Series([-0.02, -0.03, -0.04, -0.05])
        result = s09.ann_stats(s, _rf_q(len(s)))
        assert result["hit_rate"] == pytest.approx(0.0)

    def test_max_dd_is_non_negative(self):
        s = pd.Series([0.05, -0.10, 0.03, -0.05, 0.08])
        result = s09.ann_stats(s, _rf_q(len(s)))
        assert result["max_dd"] >= 0

    def test_max_dd_zero_for_monotone_increasing(self):
        s = pd.Series([0.01, 0.02, 0.03, 0.04])
        result = s09.ann_stats(s, _rf_q(len(s)))
        assert result["max_dd"] == pytest.approx(0.0, abs=1e-9)

    def test_ann_ret_formula(self):
        s = pd.Series([0.05, 0.05, 0.05, 0.05])
        result = s09.ann_stats(s, _rf_q(len(s)))
        expected = (1.05**4) - 1
        assert result["ann_ret"] == pytest.approx(expected)

    def test_sortino_with_mixed_returns(self):
        s = pd.Series([0.05, -0.03, 0.08, -0.02, 0.04, -0.01])
        result = s09.ann_stats(s, _rf_q(len(s)))
        assert not np.isnan(result["sortino"])
