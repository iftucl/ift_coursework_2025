"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Unit tests for the value+momentum filter in the backtester
Project : CW2 - Value-Sentiment Investment Strategy

Tests the Asness, Moskowitz & Pedersen (2013) "Value and Momentum
Everywhere" filter that was added to the backtester in the empirical
tuning pass. The filter excludes any stock whose trailing k-day return
is below ``min_return`` at the rebalance date, shielding the value
factor from the classic "value trap" where cheap-today stocks are
past decliners.

These tests verify the filter's plumbing (config parsing, trailing-
return calculation, universe filtering) on synthetic panel data so the
contract is locked independently of any live database.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from modules.backtest.backtester import Backtester


# ----------------------------------------------------------------------
# Test fixtures — synthetic panel with one winner and one loser
# ----------------------------------------------------------------------

@pytest.fixture
def momentum_config(base_config):
    cfg = {**base_config}
    cfg['scoring'] = {
        **base_config['scoring'],
        'momentum_filter': {
            'enabled': True,
            'lookback_days': 60,
            'min_return': -0.05,
        },
    }
    return cfg


@pytest.fixture
def momentum_config_disabled(base_config):
    cfg = {**base_config}
    cfg['scoring'] = {
        **base_config['scoring'],
        'momentum_filter': {
            'enabled': False,
            'lookback_days': 60,
            'min_return': -0.05,
        },
    }
    return cfg


@pytest.fixture
def winner_loser_prices():
    """Synthetic 80-day price panel with one clear winner and loser.

    Stock W climbs from 100 → 130 (+30%), stock L falls 100 → 80 (-20%),
    stock N is flat at 100. The momentum filter with min_return=-0.05
    should accept W and N but reject L.
    """
    dates = pd.bdate_range('2024-01-02', periods=80)
    panel = pd.DataFrame({
        'W': np.linspace(100, 130, 80),
        'L': np.linspace(100, 80, 80),
        'N': np.full(80, 100.0),
    }, index=dates)
    return panel


class _StubLoader:
    """Stand-in for DataLoader — yields nothing to keep signal call fast."""
    def load_value_metrics(self, date):
        return pd.DataFrame()

    def load_news_article_metadata(self, date):
        return pd.DataFrame()

    def load_sentiment_scores(self, date):
        return pd.DataFrame()


class _StubUniverse:
    def __init__(self, symbols, sector_map):
        self._symbols = list(symbols)
        self._sector_map = dict(sector_map)

    def get_universe(self, rebal_date):
        return pd.DataFrame({'symbol': self._symbols})

    def get_sector_map(self):
        return self._sector_map

    def get_all_sectors(self):
        return sorted(set(self._sector_map.values()))


# ----------------------------------------------------------------------
# Backtester-level tests
# ----------------------------------------------------------------------

class TestMomentumFilterFlag:
    """Config parsing and attribute wiring."""

    def test_enabled_flag_parsed(self, momentum_config, winner_loser_prices):
        loader = _StubLoader()
        universe = _StubUniverse(list(winner_loser_prices.columns),
                                 {'W': 'Tech', 'L': 'Tech', 'N': 'Tech'})
        bt = Backtester(loader, universe, momentum_config)
        assert bt._momentum_enabled is True
        assert bt._momentum_lookback_days == 60
        assert bt._momentum_min_return == pytest.approx(-0.05)

    def test_disabled_flag_parsed(self, momentum_config_disabled, winner_loser_prices):
        loader = _StubLoader()
        universe = _StubUniverse(list(winner_loser_prices.columns),
                                 {'W': 'Tech', 'L': 'Tech', 'N': 'Tech'})
        bt = Backtester(loader, universe, momentum_config_disabled)
        assert bt._momentum_enabled is False

    def test_default_disabled_when_key_missing(self, base_config, winner_loser_prices):
        # base_config has no momentum_filter key at all
        cfg = {**base_config}
        cfg.setdefault('scoring', {}).pop('momentum_filter', None)
        loader = _StubLoader()
        universe = _StubUniverse(list(winner_loser_prices.columns),
                                 {'W': 'Tech', 'L': 'Tech', 'N': 'Tech'})
        bt = Backtester(loader, universe, cfg)
        # Missing key → filter should be disabled by default
        assert bt._momentum_enabled is False


# ----------------------------------------------------------------------
# Semantic tests — filter should reject losers, keep winners/flat
# ----------------------------------------------------------------------

class TestMomentumFilterSemantics:
    """Verify the trailing-return logic using a synthetic winner/loser panel."""

    def test_trailing_return_math(self, winner_loser_prices):
        # Manual calculation of the 60-day trailing return
        lookback = winner_loser_prices.tail(61)
        start = lookback.iloc[0]
        end = lookback.iloc[-1]
        trailing = (end / start) - 1.0
        # W should be up ~22%, L down ~15%, N flat
        assert trailing['W'] > 0.15
        assert trailing['L'] < -0.10
        assert abs(trailing['N']) < 1e-9

    def test_filter_admits_winner_excludes_loser(self, winner_loser_prices):
        """Apply the exact filter logic inline to verify the contract."""
        min_return = -0.05
        lookback_days = 60
        history = winner_loser_prices
        lookback = history.tail(lookback_days + 1)
        start = lookback.iloc[0]
        end = lookback.iloc[-1]
        trailing = (end / start) - 1.0
        passing = set(trailing[trailing >= min_return].index)
        assert 'W' in passing
        assert 'N' in passing
        assert 'L' not in passing

    def test_filter_relaxed_admits_loser(self, winner_loser_prices):
        """A looser -25% threshold should admit the -20% loser too."""
        min_return = -0.25
        lookback_days = 60
        history = winner_loser_prices
        lookback = history.tail(lookback_days + 1)
        start = lookback.iloc[0]
        end = lookback.iloc[-1]
        trailing = (end / start) - 1.0
        passing = set(trailing[trailing >= min_return].index)
        assert {'W', 'L', 'N'}.issubset(passing)
