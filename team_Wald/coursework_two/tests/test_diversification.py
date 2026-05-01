"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for diversification metrics
Project : CW2 - Value-Sentiment Investment Strategy
"""

import numpy as np
import pandas as pd
import pytest

from modules.analytics.diversification import (
    compute_diversification_metrics,
    compute_diversification_over_time,
    compute_sector_allocation,
)


@pytest.fixture
def equal_weights_40():
    tickers = [f'T{i}' for i in range(40)]
    return pd.Series(1.0 / 40, index=tickers)


@pytest.fixture
def sector_map_40():
    return {f'T{i}': f'Sector{i % 4}' for i in range(40)}


class TestHHIAndEffectiveN:

    def test_equal_weight_hhi_known_answer(self, equal_weights_40, sector_map_40):
        metrics = compute_diversification_metrics(equal_weights_40, sector_map_40)
        # HHI = N × (1/N)² = 1/N → 0.025 for N=40
        assert abs(metrics['hhi'] - 0.025) < 1e-12
        assert abs(metrics['effective_n'] - 40.0) < 1e-9

    def test_concentrated_portfolio_lower_effective_n(self, sector_map_40):
        w = pd.Series({'T0': 0.50, 'T1': 0.30, 'T2': 0.10, 'T3': 0.10})
        metrics = compute_diversification_metrics(w, sector_map_40)
        # HHI = 0.25 + 0.09 + 0.01 + 0.01 = 0.36 → effective N ≈ 2.78
        assert abs(metrics['hhi'] - 0.36) < 1e-9
        assert abs(metrics['effective_n'] - (1 / 0.36)) < 1e-6

    def test_n_holdings_counts_positive(self, sector_map_40):
        w = pd.Series({'T0': 0.5, 'T1': 0.5, 'T2': 0.0})
        metrics = compute_diversification_metrics(w, sector_map_40)
        assert metrics['n_holdings'] == 2

    def test_max_sector_weight_correct(self, sector_map_40):
        w = pd.Series({'T0': 0.40, 'T4': 0.30, 'T1': 0.30})
        # T0 and T4 are in Sector0, T1 in Sector1 → Sector0 = 0.70
        metrics = compute_diversification_metrics(w, sector_map_40)
        assert abs(metrics['max_sector_weight'] - 0.70) < 1e-9


class TestSectorAllocation:

    def test_alloc_sums_to_total_weight(self, equal_weights_40, sector_map_40):
        alloc = compute_sector_allocation(equal_weights_40, sector_map_40)
        assert abs(alloc.sum() - 1.0) < 1e-12

    def test_alloc_sorted_descending(self, sector_map_40):
        w = pd.Series({'T0': 0.5, 'T1': 0.3, 'T2': 0.2})
        alloc = compute_sector_allocation(w, sector_map_40)
        assert list(alloc.values) == sorted(alloc.values, reverse=True)


class TestDiversificationOverTime:

    def test_records_one_row_per_date(self, sector_map_40):
        history = {
            pd.Timestamp('2024-01-31'): pd.Series({'T0': 0.5, 'T1': 0.5}),
            pd.Timestamp('2024-04-30'): pd.Series({'T0': 0.4, 'T2': 0.3, 'T3': 0.3}),
            pd.Timestamp('2024-07-31'): pd.Series({'T0': 0.25, 'T1': 0.25, 'T2': 0.25, 'T3': 0.25}),
        }
        df = compute_diversification_over_time(history, sector_map_40)
        assert len(df) == 3
        assert 'effective_n' in df.columns
        assert df.index.is_monotonic_increasing

    def test_empty_history_empty_df(self):
        df = compute_diversification_over_time({}, {})
        assert len(df) == 0
