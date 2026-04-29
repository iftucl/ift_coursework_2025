"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Unit tests for backtester module
Project : CW2 - Value-Sentiment Investment Strategy

Tests specifically for the Backtester class:
  - Turnover calculation (known-answer tests)
  - Transaction cost model
  - Rebalance schedule generation

Performance metric tests are in test_performance.py (per guide D1).

Test types per D8:
  - Known-answer: exact turnover values for known weight changes
  - Invariants: turnover in [0, 1], weights sum to 1
  - Edge cases: empty portfolios, from-cash transitions
"""

import numpy as np
import pandas as pd
import pytest

from modules.backtest.backtester import Backtester
from modules.backtest.transaction_costs import TransactionCostModel
from modules.backtest.rebalance_schedule import get_rebalance_dates


class TestTurnoverCalculation:
    """Known-answer tests for one-way turnover."""

    def test_no_change_zero_turnover(self):
        """Identical weights should give zero turnover."""
        w = pd.Series([0.5, 0.5], index=['A', 'B'])
        turnover = Backtester._calc_turnover(w, w)
        assert turnover == 0.0

    def test_complete_change_full_turnover(self):
        """Completely disjoint portfolios should give turnover = 1.0."""
        old_w = pd.Series([1.0], index=['A'])
        new_w = pd.Series([1.0], index=['B'])
        turnover = Backtester._calc_turnover(old_w, new_w)
        assert abs(turnover - 1.0) < 1e-10

    def test_partial_change_known_answer(self):
        """Known answer: shift 30% from A to B gives turnover = 0.3."""
        old_w = pd.Series([0.7, 0.3], index=['A', 'B'])
        new_w = pd.Series([0.4, 0.6], index=['A', 'B'])
        turnover = Backtester._calc_turnover(old_w, new_w)
        assert abs(turnover - 0.3) < 1e-10

    def test_from_cash_to_invested(self):
        """From cash (empty) to invested gives turnover = 0.5 (one-way)."""
        old_w = pd.Series(dtype=float)
        new_w = pd.Series([0.5, 0.5], index=['A', 'B'])
        turnover = Backtester._calc_turnover(old_w, new_w)
        assert abs(turnover - 0.5) < 1e-10

    def test_from_invested_to_cash(self):
        """From invested to cash gives turnover = 0.5 (one-way)."""
        old_w = pd.Series([0.5, 0.5], index=['A', 'B'])
        new_w = pd.Series(dtype=float)
        turnover = Backtester._calc_turnover(old_w, new_w)
        assert abs(turnover - 0.5) < 1e-10

    def test_turnover_invariant_range(self):
        """Invariant: one-way turnover is always in [0, 1]."""
        rng = np.random.RandomState(42)
        for _ in range(50):
            n = rng.randint(5, 20)
            old_w = pd.Series(rng.dirichlet(np.ones(n)),
                              index=[f'T{i}' for i in range(n)])
            new_w = pd.Series(rng.dirichlet(np.ones(n)),
                              index=[f'T{i}' for i in range(n)])
            turnover = Backtester._calc_turnover(old_w, new_w)
            assert 0 <= turnover <= 1.0 + 1e-10


class TestTransactionCosts:
    """Tests for transaction cost model."""

    def test_zero_turnover_zero_cost(self):
        """No turnover should give no cost."""
        config = {'costs': {'transaction_cost_bps': 25, 'stress_test_bps': 50}}
        model = TransactionCostModel(config)
        w = pd.Series([0.5, 0.5], index=['A', 'B'])
        cost = model.calculate(w, w)
        assert cost == 0.0

    def test_full_turnover_cost_known_answer(self):
        """Known: full turnover at 25 bps gives cost = 1.0 * 25/10000 = 0.0025."""
        config = {'costs': {'transaction_cost_bps': 25, 'stress_test_bps': 50}}
        model = TransactionCostModel(config)
        old_w = pd.Series([1.0], index=['A'])
        new_w = pd.Series([1.0], index=['B'])
        cost = model.calculate(old_w, new_w)
        assert abs(cost - 0.0025) < 1e-10

    def test_stress_test_higher_cost(self):
        """Stress test should use higher cost rate (50 vs 25 bps)."""
        config = {'costs': {'transaction_cost_bps': 25, 'stress_test_bps': 50}}
        model = TransactionCostModel(config)
        old_w = pd.Series([1.0], index=['A'])
        new_w = pd.Series([1.0], index=['B'])
        baseline = model.calculate(old_w, new_w, use_stress=False)
        stress = model.calculate(old_w, new_w, use_stress=True)
        assert stress > baseline
        assert abs(stress - 0.005) < 1e-10


class TestRebalanceSchedule:
    """Tests for rebalance date generation."""

    def test_quarterly_generates_four_per_year(self):
        """Quarterly schedule should produce 4 dates per full year."""
        dates = get_rebalance_dates('2023-01-01', '2023-12-31', [1, 4, 7, 10])
        assert len(dates) == 4

    def test_dates_are_sorted(self):
        """Rebalance dates should be in ascending order."""
        dates = get_rebalance_dates('2021-01-01', '2025-12-31', [1, 4, 7, 10])
        for i in range(1, len(dates)):
            assert dates[i] > dates[i - 1]

    def test_dates_within_range(self):
        """All dates should fall within start/end range."""
        start = '2022-06-01'
        end = '2023-06-30'
        dates = get_rebalance_dates(start, end, [1, 4, 7, 10])
        for d in dates:
            assert pd.Timestamp(start) <= d <= pd.Timestamp(end)

    def test_empty_range(self):
        """Narrow date range with no matching month gives empty list."""
        dates = get_rebalance_dates('2024-02-01', '2024-03-15', [7])
        assert len(dates) == 0
