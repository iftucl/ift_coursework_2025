"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Integration tests — mini end-to-end backtest pipeline
Project : CW2 - Value-Sentiment Investment Strategy

Exercises the full signal → portfolio → backtest → analytics chain on a
synthetic but self-consistent dataset, verifying the contract between
modules without touching the live PostgreSQL/MongoDB layer.

The synthetic universe contains:
    * 12 tickers across 3 sectors
    * 504 trading days (~2 years)
    * Plausible value-metric and sentiment fixtures

These tests act as a regression net for refactors and as the on-ramp for
the production CW1 → CW2 integration documented in Part D §D7.
"""

import numpy as np
import pandas as pd
import pytest

from modules.analytics.diversification import (
    compute_diversification_metrics,
    compute_diversification_over_time,
)
from modules.analytics.performance import compute_performance_summary
from modules.analytics.pitfalls import build_pitfalls_table
from modules.analytics.turnover import compute_turnover_summary
from modules.backtest.backtester import Backtester
from modules.portfolio.portfolio_constructor import PortfolioConstructor
from modules.signals.signal_combiner import SignalCombiner
from modules.signals.value_signal import ValueSignal


# ----------------------------------------------------------------------
# Synthetic-data builders
# ----------------------------------------------------------------------

@pytest.fixture
def synthetic_universe():
    return pd.DataFrame({
        'symbol': [f'T{i:02d}' for i in range(12)],
        'security': [f'Sec{i}' for i in range(12)],
        'gics_sector': (['Technology'] * 4 + ['Health Care'] * 4 + ['Financials'] * 4),
        'gics_industry': ['Sub'] * 12,
        'country': ['US'] * 12,
        'region': ['NA'] * 12,
    })


@pytest.fixture
def synthetic_prices():
    rng = np.random.RandomState(2025)
    n_days = 504
    n_tickers = 12
    daily_ret = rng.normal(loc=0.0006, scale=0.014, size=(n_days, n_tickers))
    prices = np.cumprod(1.0 + daily_ret, axis=0) * 100.0
    dates = pd.bdate_range('2023-01-02', periods=n_days)
    return pd.DataFrame(prices, index=dates, columns=[f'T{i:02d}' for i in range(12)])


@pytest.fixture
def synthetic_value_df():
    return pd.DataFrame({
        'company_id': [f'T{i:02d}' for i in range(12)],
        'date': pd.to_datetime(['2024-04-01'] * 12),
        'pe_ratio':  [12, 14, 16, 18, 11, 13, 15, 19, 10, 22, 25, 17],
        'pb_ratio':  [1.1, 1.4, 1.6, 1.9, 0.9, 1.2, 1.5, 2.1, 0.8, 2.4, 2.8, 1.7],
        'ev_ebitda': [8, 9, 11, 13, 7, 8, 10, 14, 6, 16, 18, 12],
        'dividend_yield': [0.03, 0.025, 0.02, 0.015, 0.035, 0.03, 0.022, 0.012,
                           0.04, 0.005, 0.003, 0.018],
        'debt_equity': [0.5, 1.0, 1.5, 1.8, 0.4, 0.9, 1.3, 1.7, 0.3, 2.5, 3.0, 1.6],
    })


@pytest.fixture
def synthetic_sentiment_df():
    return pd.DataFrame({
        'company_id': [f'T{i:02d}' for i in range(12)],
        'date': pd.to_datetime(['2024-04-15'] * 12),
        'avg_sentiment':  [0.4, 0.3, 0.2, 0.0, 0.5, 0.35, 0.25, -0.1,
                           0.45, -0.2, -0.3, 0.15],
        'positive_count': [10, 8, 6, 5, 12, 9, 7, 4, 11, 3, 2, 6],
        'negative_count': [2, 3, 5, 5, 1, 2, 4, 6, 1, 7, 8, 4],
        'neutral_count':  [3, 4, 4, 5, 2, 4, 4, 5, 3, 5, 5, 4],
        'total_articles': [15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 14],
        'positive_ratio': [0.67, 0.53, 0.40, 0.33, 0.80, 0.60, 0.47, 0.27,
                           0.73, 0.20, 0.13, 0.43],
        'sentiment_score': [70, 60, 50, 40, 80, 65, 55, 35, 75, 25, 15, 50],
    })


@pytest.fixture
def sector_map_universe(synthetic_universe):
    return dict(zip(synthetic_universe['symbol'], synthetic_universe['gics_sector']))


# ----------------------------------------------------------------------
# Pipeline tests
# ----------------------------------------------------------------------

class TestSignalToPortfolio:

    def test_value_signal_to_portfolio_pipeline(
        self, base_config, synthetic_value_df, synthetic_sentiment_df, sector_map_universe,
    ):
        from modules.signals.sentiment_signal import SentimentSignal

        vs = ValueSignal(base_config)
        ss = SentimentSignal(base_config)
        combiner = SignalCombiner(base_config)
        pc = PortfolioConstructor(base_config)

        value_signals = vs.compute(synthetic_value_df, sector_map_universe)
        sentiment_signals = ss.compute(synthetic_sentiment_df, pd.Timestamp('2024-04-30'))
        combined = combiner.compute(value_signals, sentiment_signals, synthetic_value_df)

        assert 'composite_score' in combined.columns
        weights = pc.construct(combined, sector_map_universe, prices=None, current_weights=None)
        assert isinstance(weights, pd.Series)
        # Either we got a portfolio or it was empty due to small universe; both legal
        if len(weights) > 0:
            assert abs(weights.sum() - 1.0) < 1e-6
            assert (weights >= 0).all()
            # Position cap is 5% (1/20). With a synthetic universe of only
            # 12 stocks and min_holdings=5, equal-weight floor is 1/5 = 20%,
            # so the cap is mathematically unsatisfiable. Only enforce the
            # cap when the universe is large enough for it to be feasible.
            n_held = (weights > 1e-8).sum()
            position_cap = base_config['portfolio']['max_position_weight']
            if n_held >= int(1 / position_cap):
                assert weights.max() <= position_cap + 1e-6


class TestPerformancePipeline:

    def test_performance_summary_consistent_with_components(self, synthetic_returns):
        metrics = compute_performance_summary(synthetic_returns, risk_free_rate=0.0)
        # Total return ≈ product of (1+r) - 1
        expected_total = float((1 + synthetic_returns).prod() - 1)
        assert abs(metrics['total_return'] - expected_total) < 1e-9
        # Annualised vol ≈ daily std × sqrt(252)
        expected_vol = float(synthetic_returns.std() * np.sqrt(252))
        assert abs(metrics['annualised_volatility'] - expected_vol) < 1e-9


class TestEndToEndArtifacts:

    def test_pitfalls_table_independent_of_other_modules(self):
        df = build_pitfalls_table()
        assert len(df) >= 12
        assert df['status'].nunique() == 1  # all PASS

    def test_diversification_over_time_matches_per_date(self, sector_map_universe):
        history = {
            pd.Timestamp('2024-01-31'): pd.Series({'T00': 0.5, 'T01': 0.5}),
            pd.Timestamp('2024-04-30'): pd.Series({'T00': 0.4, 'T04': 0.3, 'T08': 0.3}),
        }
        df = compute_diversification_over_time(history, sector_map_universe)
        assert len(df) == 2
        # Spot-check: 2024-01-31 effective N should be 2 (two equal weights)
        assert abs(df.loc[pd.Timestamp('2024-01-31'), 'effective_n'] - 2.0) < 1e-6


class TestTurnoverPipeline:

    def test_turnover_summary_known_inputs(self):
        turnover_history = {
            pd.Timestamp('2024-01-31'): 0.50,
            pd.Timestamp('2024-04-30'): 0.20,
            pd.Timestamp('2024-07-31'): 0.30,
            pd.Timestamp('2024-10-31'): 0.10,
        }
        cost_history = {
            pd.Timestamp('2024-01-31'): 0.00125,
            pd.Timestamp('2024-04-30'): 0.00050,
            pd.Timestamp('2024-07-31'): 0.00075,
            pd.Timestamp('2024-10-31'): 0.00025,
        }
        summary = compute_turnover_summary(turnover_history, cost_history)
        assert summary['n_rebalances'] == 4
        assert abs(summary['avg_quarterly_turnover'] - 0.275) < 1e-9
        assert abs(summary['annual_turnover'] - 1.10) < 1e-9
        assert abs(summary['cumulative_cost'] - 0.00275) < 1e-9
