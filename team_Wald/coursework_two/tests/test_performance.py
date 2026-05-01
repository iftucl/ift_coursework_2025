"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for performance analytics
Project : CW2 - Value-Sentiment Investment Strategy

Tests for modules/analytics/performance.py metrics.
Separated from test_backtester.py per guide D1 architecture.

Test types per D8:
  - Known-answer: manual calculation against exact expected values
  - Invariants: drawdown always non-positive, cumulative always positive
  - Edge cases: empty returns, single-day, constant returns
"""

import numpy as np
import pandas as pd
import pytest

from modules.analytics.performance import (
    compute_cumulative_returns,
    compute_drawdown_series,
    compute_monthly_returns,
    compute_performance_summary,
    compute_rolling_sharpe,
    compute_top_drawdowns,
)


class TestReturnMetrics:
    """Known-answer tests for return calculations."""

    def test_total_return_known_answer(self):
        """Known answer: 3 days of +1% each → total = 1.01³ - 1 = 3.0301%."""
        rets = pd.Series([0.01, 0.01, 0.01], index=pd.date_range('2024-01-01', periods=3))
        metrics = compute_performance_summary(rets, risk_free_rate=0.0, portfolio_name='Test')
        expected_total = (1.01 ** 3) - 1
        assert abs(metrics['total_return'] - expected_total) < 1e-10

    def test_single_day_loss(self):
        """Known answer: single day -5% → total return = -5%."""
        rets = pd.Series([-0.05], index=pd.date_range('2024-01-01', periods=1))
        metrics = compute_performance_summary(rets, risk_free_rate=0.0)
        assert abs(metrics['total_return'] - (-0.05)) < 1e-10

    def test_alternating_returns(self):
        """Known answer: +10% then -10% → total = 1.1×0.9 - 1 = -1%."""
        rets = pd.Series([0.10, -0.10], index=pd.date_range('2024-01-01', periods=2))
        metrics = compute_performance_summary(rets, risk_free_rate=0.0)
        expected = 1.10 * 0.90 - 1.0
        assert abs(metrics['total_return'] - expected) < 1e-10


class TestRiskMetrics:
    """Tests for risk-adjusted return metrics."""

    def test_zero_volatility_sharpe(self):
        """Constant returns should handle Sharpe gracefully (no division by zero)."""
        rets = pd.Series([0.001] * 100, index=pd.date_range('2024-01-01', periods=100))
        metrics = compute_performance_summary(rets, risk_free_rate=0.0)
        assert np.isfinite(metrics['sharpe_ratio']) or metrics['sharpe_ratio'] == 0

    def test_negative_returns_sortino(self):
        """Sortino should use downside deviation only."""
        rets = pd.Series(
            [0.01, -0.02, 0.015, -0.01, 0.005],
            index=pd.date_range('2024-01-01', periods=5),
        )
        metrics = compute_performance_summary(rets, risk_free_rate=0.0)
        # Sortino should be finite
        assert np.isfinite(metrics['sortino_ratio'])

    def test_max_drawdown_after_peak_then_trough(self):
        """Known: rise to peak then drop → drawdown captures the decline."""
        rets = pd.Series(
            [0.10, -0.15, -0.05],
            index=pd.date_range('2024-01-01', periods=3),
        )
        metrics = compute_performance_summary(rets, risk_free_rate=0.0)
        # Peak at 1.10, then drops: 1.10 × 0.85 × 0.95 ≈ 0.889
        # Drawdown ≈ (0.889 - 1.10) / 1.10 ≈ -0.192
        assert metrics['max_drawdown'] < -0.10

    def test_no_drawdown_when_monotonic_up(self):
        """Strictly positive returns → max drawdown should be 0."""
        rets = pd.Series([0.01, 0.02, 0.015, 0.005],
                         index=pd.date_range('2024-01-01', periods=4))
        metrics = compute_performance_summary(rets, risk_free_rate=0.0)
        assert metrics['max_drawdown'] == 0.0


class TestDrawdownSeries:
    """Invariant tests for drawdown series."""

    def test_drawdown_always_non_positive(self):
        """Invariant: drawdown values must be ≤ 0."""
        rets = pd.Series([0.01, -0.05, 0.02, -0.03, 0.04],
                         index=pd.date_range('2024-01-01', periods=5))
        dd = compute_drawdown_series(rets)
        assert (dd <= 0 + 1e-10).all()

    def test_drawdown_zero_at_new_highs(self):
        """Invariant: drawdown should be 0 at new cumulative highs."""
        rets = pd.Series([0.10, 0.10, 0.10],
                         index=pd.date_range('2024-01-01', periods=3))
        dd = compute_drawdown_series(rets)
        assert (dd == 0).all()


class TestCumulativeReturns:
    """Tests for cumulative return calculation."""

    def test_cumulative_growth_of_one(self):
        """Known: cumulative return of [+1%, +2%, -1%] → 1.01×1.02×0.99."""
        rets = pd.Series([0.01, 0.02, -0.01],
                         index=pd.date_range('2024-01-01', periods=3))
        cum = compute_cumulative_returns(rets)
        assert abs(cum.iloc[0] - 1.01) < 1e-10
        expected_final = 1.01 * 1.02 * 0.99
        assert abs(cum.iloc[-1] - expected_final) < 1e-10

    def test_cumulative_always_positive(self):
        """Invariant: cumulative returns should be positive (no bankruptcy)."""
        rets = pd.Series([-0.01, -0.02, -0.01, 0.05, -0.03],
                         index=pd.date_range('2024-01-01', periods=5))
        cum = compute_cumulative_returns(rets)
        assert (cum > 0).all()


class TestMonthlyReturns:
    """Tests for monthly return heatmap data."""

    def test_monthly_aggregation(self):
        """Monthly return should compound daily returns within month."""
        # 22 trading days of +0.1% each ≈ 2.2% monthly
        dates = pd.bdate_range('2024-01-02', periods=22)
        rets = pd.Series(0.001, index=dates)
        monthly = compute_monthly_returns(rets)
        assert len(monthly) == 1  # One month
        expected = (1.001 ** 22) - 1
        assert abs(monthly.iloc[0, 0] - expected) < 1e-6


class TestTopDrawdowns:
    """Tests for top drawdown event identification."""

    def test_identifies_drawdown_events(self):
        """Should identify at least one drawdown event in volatile data."""
        np.random.seed(42)
        rets = pd.Series(
            np.random.normal(0, 0.02, 500),
            index=pd.bdate_range('2022-01-03', periods=500),
        )
        events = compute_top_drawdowns(rets, n=3)
        assert len(events) >= 1
        assert 'depth' in events.columns
        assert (events['depth'] < 0).all()


class TestEdgeCases:
    """Edge case tests for performance metrics."""

    def test_empty_returns(self):
        """Empty return series → all zero metrics."""
        rets = pd.Series(dtype=float)
        metrics = compute_performance_summary(rets)
        assert metrics['total_return'] == 0.0
        assert metrics['sharpe_ratio'] == 0.0
        assert metrics['max_drawdown'] == 0.0

    def test_single_zero_return(self):
        """Single zero return → total return should be 0."""
        rets = pd.Series([0.0], index=pd.date_range('2024-01-01', periods=1))
        metrics = compute_performance_summary(rets, risk_free_rate=0.0)
        assert metrics['total_return'] == 0.0

    def test_benchmark_relative_metrics(self):
        """When benchmark is provided, relative metrics should be computed."""
        port = pd.Series([0.01, 0.02, -0.01], index=pd.date_range('2024-01-01', periods=3))
        bench = pd.Series([0.005, 0.01, -0.005], index=pd.date_range('2024-01-01', periods=3))
        metrics = compute_performance_summary(port, bench, risk_free_rate=0.0)
        assert 'information_ratio' in metrics
        assert 'tracking_error' in metrics
        assert 'active_return' in metrics
