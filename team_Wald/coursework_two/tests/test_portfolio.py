"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Unit tests for portfolio construction
Project : CW2 - Value-Sentiment Investment Strategy

Tests:
  - Weights sum to 1.0 (invariant)
  - All weights non-negative (long-only)
  - Position cap ≤ 5%
  - Sector cap ≤ 25%
  - Weighting schemes produce expected distributions
"""

import numpy as np
import pandas as pd
import pytest

from modules.portfolio.constraints import apply_constraints
from modules.portfolio.weighting import (
    compute_equal_weight,
    compute_inverse_volatility_weight,
    compute_score_weight,
)


@pytest.fixture
def sector_map():
    return {f'T{i}': f'Sector{i % 4}' for i in range(40)}


class TestEqualWeight:

    def test_sum_to_one(self):
        tickers = [f'T{i}' for i in range(40)]
        w = compute_equal_weight(tickers)
        assert abs(w.sum() - 1.0) < 1e-10

    def test_equal_values(self):
        tickers = ['A', 'B', 'C']
        w = compute_equal_weight(tickers)
        assert (w == 1.0 / 3).all()

    def test_empty_list(self):
        w = compute_equal_weight([])
        assert len(w) == 0

    def test_single_stock(self):
        w = compute_equal_weight(['SOLO'])
        assert w['SOLO'] == 1.0


class TestScoreWeight:

    def test_sum_to_one(self):
        tickers = ['A', 'B', 'C']
        scores = pd.Series([80, 60, 40], index=tickers)
        w = compute_score_weight(tickers, scores)
        assert abs(w.sum() - 1.0) < 1e-10

    def test_highest_score_highest_weight(self):
        tickers = ['A', 'B', 'C']
        scores = pd.Series([100, 50, 25], index=tickers)
        w = compute_score_weight(tickers, scores)
        assert w['A'] > w['B'] > w['C']


class TestConstraints:

    def test_position_cap(self, sector_map):
        tickers = list(sector_map.keys())
        # Deliberately give one stock a huge weight
        w = pd.Series(0.01, index=tickers)
        w.iloc[0] = 0.80
        w = w / w.sum()

        constrained = apply_constraints(w, sector_map, max_position=0.05, max_sector=0.50)
        assert constrained.max() <= 0.05 + 1e-6

    def test_sum_to_one_after_constraints(self, sector_map):
        tickers = list(sector_map.keys())
        w = pd.Series(1.0 / len(tickers), index=tickers)
        constrained = apply_constraints(w, sector_map)
        assert abs(constrained.sum() - 1.0) < 1e-6

    def test_non_negative(self, sector_map):
        tickers = list(sector_map.keys())
        w = pd.Series(1.0 / len(tickers), index=tickers)
        constrained = apply_constraints(w, sector_map)
        assert (constrained >= -1e-10).all()

    def test_sector_cap(self):
        """Concentrated sector should be redistributed to meet cap."""
        # 20 stocks in one sector, 5 each in 4 other sectors
        sector_map = {f'T{i}': 'BigSector' for i in range(20)}
        for s_idx in range(4):
            for j in range(5):
                sector_map[f'S{s_idx}_{j}'] = f'Small{s_idx}'
        tickers = list(sector_map.keys())
        w = pd.Series(1.0 / len(tickers), index=tickers)
        constrained = apply_constraints(w, sector_map, max_sector=0.25)
        big_tickers = [f'T{i}' for i in range(20)]
        sector_wt = constrained.reindex(big_tickers, fill_value=0).sum()
        assert sector_wt <= 0.25 + 1e-3
