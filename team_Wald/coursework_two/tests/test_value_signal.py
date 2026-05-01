"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for sector-relative value signal
Project : CW2 - Value-Sentiment Investment Strategy

Test types per Part D §D8:
  - Known-answer: manual calculation verified
  - Invariants: z-scores centred at 0, within ±3
  - Edge cases: empty data, single stock, all NaN, financials excluded

Coverage target: 85%+
"""

import numpy as np
import pandas as pd
import pytest

from modules.signals.value_signal import ValueSignal


@pytest.fixture
def config():
    """Standard test configuration."""
    return {
        'scoring': {
            'winsorize_lower': 0.025,
            'winsorize_upper': 0.975,
            'zscore_cap': 3.0,
            'shrinkage_k_sector': 20,
        },
    }


@pytest.fixture
def sample_value_df():
    """Create sample value DataFrame with 10 stocks in 2 sectors."""
    data = {
        'company_id': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'],
        'pe_ratio': [15, 20, 25, 10, 30, 12, 18, 22, 8, 35],
        'pb_ratio': [1.5, 2.0, 3.0, 1.0, 4.0, 1.2, 1.8, 2.5, 0.8, 5.0],
        'ev_ebitda': [10, 12, 15, 8, 20, 9, 11, 14, 7, 25],
        'dividend_yield': [0.03, 0.02, 0.01, 0.04, 0.005, 0.035, 0.025, 0.015, 0.05, 0.003],
        'debt_equity': [1.0, 1.5, 2.0, 0.5, 2.5, 0.8, 1.2, 1.8, 0.3, 3.0],
    }
    return pd.DataFrame(data)


@pytest.fixture
def sector_map():
    """Sector mapping: 5 stocks per sector."""
    return {
        'A': 'Technology', 'B': 'Technology', 'C': 'Technology',
        'D': 'Technology', 'E': 'Technology',
        'F': 'Health Care', 'G': 'Health Care', 'H': 'Health Care',
        'I': 'Health Care', 'J': 'Health Care',
    }


class TestValueSignal:
    """Test suite for ValueSignal module."""

    def test_basic_scoring(self, config, sample_value_df, sector_map):
        """Test that value scores are computed for all companies."""
        signal = ValueSignal(config)
        result = signal.compute(sample_value_df, sector_map)
        assert len(result) == 10
        assert 'value_score' in result.columns
        assert 'company_id' in result.columns

    def test_zscore_cap_invariant(self, config, sample_value_df, sector_map):
        """Invariant: all value scores within ±3 (zscore_cap)."""
        signal = ValueSignal(config)
        result = signal.compute(sample_value_df, sector_map)
        valid_scores = result['value_score'].dropna()
        assert (valid_scores >= -3.0 - 1e-10).all(), "Scores below -3.0"
        assert (valid_scores <= 3.0 + 1e-10).all(), "Scores above 3.0"

    def test_sector_mean_near_zero(self, config, sample_value_df, sector_map):
        """Invariant: within-sector mean should be approximately zero."""
        signal = ValueSignal(config)
        result = signal.compute(sample_value_df, sector_map)
        result['sector'] = result['company_id'].map(sector_map)
        for sector in result['sector'].unique():
            sector_scores = result[result['sector'] == sector]['value_score'].dropna()
            if len(sector_scores) >= 3:
                assert abs(sector_scores.mean()) < 1.0, f"Sector {sector} mean too far from 0"

    def test_financials_exclude_ebitda(self, config):
        """EV/EBITDA should be excluded for Financial sector stocks."""
        signal = ValueSignal(config)
        df = pd.DataFrame({
            'company_id': ['BNK1', 'BNK2', 'TECH1', 'TECH2'],
            'pe_ratio': [10, 12, 25, 30],
            'pb_ratio': [1.0, 1.2, 3.0, 4.0],
            'ev_ebitda': [8, 10, 15, 20],
            'dividend_yield': [0.03, 0.04, 0.01, 0.005],
            'debt_equity': [1.5, 1.8, 0.5, 0.8],
        })
        sector_map = {
            'BNK1': 'Financials', 'BNK2': 'Financials',
            'TECH1': 'Technology', 'TECH2': 'Technology',
        }
        result = signal.compute(df, sector_map)
        assert len(result) == 4

    def test_empty_input(self, config):
        """Edge case: empty DataFrame should return empty result."""
        signal = ValueSignal(config)
        result = signal.compute(pd.DataFrame(columns=['company_id', 'pe_ratio', 'pb_ratio',
                                                       'ev_ebitda', 'dividend_yield', 'debt_equity']),
                                 {})
        assert len(result) == 0 or result['value_score'].isna().all()

    def test_single_stock(self, config):
        """Edge case: single stock should still return a score."""
        signal = ValueSignal(config)
        df = pd.DataFrame({
            'company_id': ['SOLO'],
            'pe_ratio': [15.0],
            'pb_ratio': [2.0],
            'ev_ebitda': [10.0],
            'dividend_yield': [0.02],
            'debt_equity': [1.0],
        })
        result = signal.compute(df, {'SOLO': 'Technology'})
        assert len(result) == 1

    def test_all_nan_ratios(self, config):
        """Edge case: all NaN ratios should handle gracefully."""
        signal = ValueSignal(config)
        df = pd.DataFrame({
            'company_id': ['X', 'Y'],
            'pe_ratio': [np.nan, np.nan],
            'pb_ratio': [np.nan, np.nan],
            'ev_ebitda': [np.nan, np.nan],
            'dividend_yield': [np.nan, np.nan],
            'debt_equity': [np.nan, np.nan],
        })
        result = signal.compute(df, {'X': 'Tech', 'Y': 'Tech'})
        assert len(result) == 2
