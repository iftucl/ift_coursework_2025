"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for UniverseConstructor (point-in-time, survivorship)
Project : CW2 - Value-Sentiment Investment Strategy
"""

import numpy as np
import pandas as pd
import pytest

from modules.data.universe import UniverseConstructor


@pytest.fixture
def companies_df():
    return pd.DataFrame({
        'symbol': ['A', 'B', 'C', 'D', 'E'],
        'security': ['Alpha', 'Beta', 'Gamma', 'Delta', 'Eps'],
        'gics_sector': ['Tech', 'Tech', 'Health', 'Health', 'Energy'],
        'gics_industry': ['SW', 'HW', 'Pharma', 'Equip', 'Oil'],
        'country': ['US'] * 5,
        'region': ['NA'] * 5,
    })


@pytest.fixture
def prices_df():
    dates = pd.bdate_range('2024-01-01', periods=20)
    df = pd.DataFrame(
        np.random.RandomState(0).normal(100, 5, size=(20, 5)).cumsum(axis=0) + 100,
        index=dates, columns=['A', 'B', 'C', 'D', 'E'],
    )
    # Stock E goes inactive after day 10 — simulating delisting
    df.loc[df.index[10:], 'E'] = np.nan
    return df


class TestUniverseConstructor:

    def test_includes_active_stocks(self, companies_df, prices_df):
        cfg = {}
        u = UniverseConstructor(companies_df, prices_df, cfg)
        universe = u.get_universe(prices_df.index[5])
        assert 'A' in universe['symbol'].values
        assert 'E' in universe['symbol'].values  # Still active on day 5

    def test_excludes_inactive_after_delisting(self, companies_df, prices_df):
        cfg = {}
        u = UniverseConstructor(companies_df, prices_df, cfg)
        # Day 19 is well past the delisting (day 10); E has been NaN for 9 days
        # which is within the 10-day window, so it may still be considered active
        # Day 25 (beyond window) — but our data only has 20 days.
        # Use day index 19 which is 9 days past delisting → still in 10-day window
        # Use a synthetic later date to fully exclude.
        far_future = prices_df.index[-1] + pd.Timedelta(days=30)
        universe = u.get_universe(far_future)
        # E should be excluded (inactive for >10 days)
        assert 'E' not in universe['symbol'].values

    def test_sector_map(self, companies_df, prices_df):
        u = UniverseConstructor(companies_df, prices_df, {})
        sm = u.get_sector_map()
        assert sm['A'] == 'Tech'
        assert sm['C'] == 'Health'
        assert sm['E'] == 'Energy'

    def test_get_all_sectors(self, companies_df, prices_df):
        u = UniverseConstructor(companies_df, prices_df, {})
        sectors = u.get_all_sectors()
        assert 'Tech' in sectors
        assert 'Health' in sectors
        assert 'Energy' in sectors
        assert sectors == sorted(sectors)
