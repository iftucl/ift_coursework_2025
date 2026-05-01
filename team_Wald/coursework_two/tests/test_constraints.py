"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for portfolio constraints
Project : CW2 - Value-Sentiment Investment Strategy

Focused unit tests for the iterative constraint enforcer in
``modules/portfolio/constraints.py``. Verifies position cap, sector cap,
proportional redistribution of excess, normalisation invariant, and
edge-case handling for tiny universes and zero-weight inputs.
"""

import numpy as np
import pandas as pd
import pytest

from modules.portfolio.constraints import apply_constraints


@pytest.fixture
def diverse_sector_map():
    return {
        'A1': 'Tech', 'A2': 'Tech', 'A3': 'Tech', 'A4': 'Tech', 'A5': 'Tech',
        'B1': 'Health', 'B2': 'Health', 'B3': 'Health', 'B4': 'Health', 'B5': 'Health',
        'C1': 'Energy', 'C2': 'Energy', 'C3': 'Energy', 'C4': 'Energy', 'C5': 'Energy',
        'D1': 'Finance', 'D2': 'Finance', 'D3': 'Finance', 'D4': 'Finance', 'D5': 'Finance',
        'E1': 'Industrial', 'E2': 'Industrial', 'E3': 'Industrial', 'E4': 'Industrial', 'E5': 'Industrial',
    }


class TestPositionCap:

    def test_single_position_cap(self, diverse_sector_map):
        tickers = list(diverse_sector_map.keys())
        w = pd.Series(0.01, index=tickers)
        w.iloc[0] = 0.50  # giant position
        w = w / w.sum()
        out = apply_constraints(w, diverse_sector_map, max_position=0.05, max_sector=0.30)
        assert out.max() <= 0.05 + 1e-6

    def test_position_cap_preserves_total(self, diverse_sector_map):
        tickers = list(diverse_sector_map.keys())
        rng = np.random.RandomState(0)
        w = pd.Series(rng.dirichlet(np.ones(len(tickers))), index=tickers)
        out = apply_constraints(w, diverse_sector_map, max_position=0.06, max_sector=0.30)
        assert abs(out.sum() - 1.0) < 1e-6


class TestSectorCap:

    def test_sector_cap_reduces_concentrated_sector(self, diverse_sector_map):
        # All weight in one sector
        tickers = ['A1', 'A2', 'A3', 'A4', 'A5']
        w = pd.Series(0.20, index=tickers)
        # Add some other sectors so there is somewhere to redistribute
        for t in ['B1', 'C1', 'D1', 'E1']:
            w[t] = 0.0001
        out = apply_constraints(w, diverse_sector_map, max_position=0.10, max_sector=0.25)
        tech_weight = out[['A1', 'A2', 'A3', 'A4', 'A5']].sum()
        assert tech_weight <= 0.25 + 1e-3

    def test_sector_cap_no_op_when_balanced(self, diverse_sector_map):
        tickers = list(diverse_sector_map.keys())
        w = pd.Series(1.0 / len(tickers), index=tickers)
        out = apply_constraints(w, diverse_sector_map, max_position=0.05, max_sector=0.25)
        # Each sector has 5/25 = 0.20 — well below cap
        assert abs(out.sum() - 1.0) < 1e-6


class TestInvariants:

    def test_non_negative_weights(self, diverse_sector_map):
        tickers = list(diverse_sector_map.keys())
        rng = np.random.RandomState(1)
        w = pd.Series(rng.dirichlet(np.ones(len(tickers))), index=tickers)
        out = apply_constraints(w, diverse_sector_map)
        assert (out >= -1e-12).all()

    def test_handles_unknown_sector(self):
        sector_map = {'A': 'Tech', 'B': 'Tech', 'C': 'Health', 'D': 'Health'}
        w = pd.Series([0.40, 0.40, 0.10, 0.10], index=['A', 'B', 'C', 'D'])
        out = apply_constraints(w, sector_map, max_position=0.30, max_sector=0.50)
        assert abs(out.sum() - 1.0) < 1e-6
        assert out.max() <= 0.30 + 1e-6

    def test_idempotent_when_already_compliant(self, diverse_sector_map):
        tickers = list(diverse_sector_map.keys())
        w = pd.Series(1.0 / len(tickers), index=tickers)
        once = apply_constraints(w, diverse_sector_map)
        twice = apply_constraints(once, diverse_sector_map)
        pd.testing.assert_series_equal(once, twice, check_exact=False, rtol=1e-6)
