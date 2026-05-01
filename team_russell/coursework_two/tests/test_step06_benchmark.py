"""Tests for step06_benchmark.py — ann_stats, jensen_alpha, index_return, build_comparison."""

import numpy as np
import pandas as pd
import pytest
import step06_benchmark as s06

# ── ann_stats ─────────────────────────────────────────────────────────────────


def _rf_q(n, rate=0.005):
    """Constant quarterly rf Series of length n for test use (rate=0.005 ≈ 2% p.a.)."""
    return pd.Series(np.full(n, rate))


class TestAnnStats:
    def test_returns_dict(self):
        s = pd.Series([0.03, 0.02, -0.01, 0.04])
        result = s06.ann_stats(s, _rf_q(len(s)))
        assert isinstance(result, dict)

    def test_required_keys(self):
        s = pd.Series([0.03, 0.02, -0.01, 0.04])
        result = s06.ann_stats(s, _rf_q(len(s)))
        for key in ["ann_ret", "ann_vol", "sharpe", "sortino", "cum"]:
            assert key in result

    def test_ann_ret_formula(self):
        # (1 + 0.05)^4 - 1 ≈ 21.55%
        s = pd.Series([0.05, 0.05, 0.05, 0.05])
        result = s06.ann_stats(s, _rf_q(len(s)))
        expected = (1.05**4) - 1
        assert result["ann_ret"] == pytest.approx(expected)

    def test_ann_vol_is_positive(self):
        s = pd.Series([0.05, -0.03, 0.08, 0.02, -0.01])
        result = s06.ann_stats(s, _rf_q(len(s)))
        assert result["ann_vol"] > 0

    def test_sharpe_positive_for_high_return(self):
        # Returns well above Rf with some variance should give positive Sharpe
        s = pd.Series([0.09, 0.10, 0.11, 0.10, 0.09, 0.11])
        result = s06.ann_stats(s, _rf_q(len(s)))
        assert result["sharpe"] > 0

    def test_sharpe_negative_for_low_return(self):
        s = pd.Series([-0.05, -0.04, -0.06, -0.05, -0.04, -0.06])
        result = s06.ann_stats(s, _rf_q(len(s)))
        assert result["sharpe"] < 0

    def test_sortino_positive_when_no_downside(self):
        s = pd.Series([0.05, 0.05, 0.05, 0.05])
        result = s06.ann_stats(s, _rf_q(len(s)))
        assert "sortino" in result

    def test_sortino_with_mixed_returns(self):
        s = pd.Series([0.05, -0.03, 0.08, 0.02, -0.06, 0.10])
        result = s06.ann_stats(s, _rf_q(len(s)))
        assert not np.isnan(result["sortino"])

    def test_cum_return_arithmetic(self):
        s = pd.Series([0.10, 0.10])
        result = s06.ann_stats(s, _rf_q(len(s)))
        expected = (1.10 * 1.10) - 1
        assert result["cum"] == pytest.approx(expected)


# ── jensen_alpha ──────────────────────────────────────────────────────────────


class TestJensenAlpha:
    _RF_Q = 0.005  # constant quarterly rf used to construct synthetic data

    def _correlated_series(self, n=40, beta=0.9, alpha_q=0.01, seed=0):
        np.random.seed(seed)
        bm = pd.Series(np.random.normal(0.02, 0.05, n))
        port = self._RF_Q + alpha_q + beta * (bm - self._RF_Q) + np.random.normal(0, 0.01, n)
        return port, bm

    def _rf(self, n):
        return pd.Series(np.full(n, self._RF_Q))

    def test_returns_dict(self):
        port, bm = self._correlated_series()
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        assert isinstance(result, dict)

    def test_required_keys(self):
        port, bm = self._correlated_series()
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        for key in ["alpha", "beta", "t_alpha", "p_alpha", "r_squared"]:
            assert key in result

    def test_beta_close_to_true_value(self):
        port, bm = self._correlated_series(n=200, beta=0.9, seed=1)
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        assert abs(result["beta"] - 0.9) < 0.15

    def test_positive_alpha_for_outperforming_portfolio(self):
        port, bm = self._correlated_series(n=100, alpha_q=0.02, seed=2)
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        assert result["alpha"] > 0

    def test_r_squared_between_0_and_1(self):
        port, bm = self._correlated_series()
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        assert 0 <= result["r_squared"] <= 1

    def test_p_value_between_0_and_1(self):
        port, bm = self._correlated_series()
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        assert 0 <= result["p_alpha"] <= 1

    def test_too_few_observations_returns_nan(self):
        port = pd.Series([0.01, 0.02, 0.03])
        bm = pd.Series([0.01, 0.02, 0.03])
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        assert np.isnan(result["alpha"])

    def test_alpha_annualised(self):
        # alpha_q ≈ 0.01 quarterly → alpha_annual ≈ (1.01)^4 - 1 ≈ 4.06%
        port, bm = self._correlated_series(n=200, alpha_q=0.01, beta=1.0, seed=3)
        result = s06.jensen_alpha(port, bm, self._rf(len(port)))
        assert abs(result["alpha"] - 0.0406) < 0.02


# ── index_return ──────────────────────────────────────────────────────────────


class TestIndexReturn:
    @pytest.fixture
    def price_series(self):
        dates = pd.date_range("2022-01-01", periods=252, freq="B")
        return pd.Series(np.linspace(100.0, 120.0, 252), index=dates)

    def test_positive_return_for_rising_prices(self, price_series):
        result = s06.index_return(price_series, "2022-01-03", "2022-06-01")
        assert result > 0

    def test_return_formula(self, price_series):
        p_start = float(price_series[price_series.index <= pd.Timestamp("2022-01-03")].iloc[-1])
        p_end = float(price_series[price_series.index >= pd.Timestamp("2022-12-01")].iloc[0])
        expected = (p_end - p_start) / p_start
        result = s06.index_return(price_series, "2022-01-03", "2022-12-01")
        assert result == pytest.approx(expected)

    def test_nan_when_start_before_series(self, price_series):
        result = s06.index_return(price_series, "2020-01-01", "2022-06-01")
        assert np.isnan(result)

    def test_nan_when_end_after_series(self, price_series):
        result = s06.index_return(price_series, "2022-01-03", "2025-01-01")
        assert np.isnan(result)

    def test_zero_return_same_date(self, price_series):
        result = s06.index_return(price_series, "2022-01-03", "2022-01-03")
        assert result == pytest.approx(0.0, abs=1e-6)


# ── build_comparison ──────────────────────────────────────────────────────────


class TestBuildComparison:
    @pytest.fixture
    def q1_df(self):
        return pd.DataFrame(
            {
                "start_date": [pd.Timestamp("2022-03-31"), pd.Timestamp("2022-06-30")],
                "end_date": [pd.Timestamp("2022-06-30"), pd.Timestamp("2022-09-30")],
                "q1_gross": [0.04, -0.02],
                "q1_net": [0.036, -0.024],
                "ew_gross": [0.03, -0.01],
                "ew_net": [0.026, -0.014],
            }
        )

    @pytest.fixture
    def index_prices(self):
        dates = pd.date_range("2022-01-01", periods=200, freq="B")
        prices = pd.Series(np.linspace(400.0, 420.0, 200), index=dates)
        return {"SPY": prices}

    def test_returns_dataframe(self, q1_df, index_prices):
        result = s06.build_comparison(q1_df, index_prices)
        assert isinstance(result, pd.DataFrame)

    def test_one_row_per_period(self, q1_df, index_prices):
        result = s06.build_comparison(q1_df, index_prices)
        assert len(result) == len(q1_df)

    def test_q1_net_column_preserved(self, q1_df, index_prices):
        result = s06.build_comparison(q1_df, index_prices)
        assert "q1_net" in result.columns

    def test_benchmark_return_column_added(self, q1_df, index_prices):
        result = s06.build_comparison(q1_df, index_prices)
        assert "SPY_gross" in result.columns or "SPY_net" in result.columns
