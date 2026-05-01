"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for robustness module
Project : CW2 - Value-Sentiment Investment Strategy

Covers:
    * stationary_bootstrap_sharpe — point estimate, CI ordering, monotone
      length, return / max-drawdown CIs added in the v2 sophistication pass
    * random_portfolio_test       — distribution + percentile rank
    * sub_period_analysis         — year + regime + full rows
    * weight_sensitivity_analysis — tests config plumbing via stub
"""

import numpy as np
import pandas as pd
import pytest

from modules.robustness.bootstrap import stationary_bootstrap_sharpe
from modules.robustness.random_portfolios import random_portfolio_test
from modules.robustness.sensitivity import (
    sub_period_analysis,
    weight_sensitivity_analysis,
)


class TestStationaryBootstrap:

    def test_point_estimate_close_to_naive(self, synthetic_returns):
        result = stationary_bootstrap_sharpe(
            synthetic_returns, n_reps=300, block_length=10, random_seed=1,
        )
        # Naive Sharpe on the raw series
        rf_daily = (1 + 0.04) ** (1 / 252) - 1
        naive_sharpe = (synthetic_returns - rf_daily).mean() / synthetic_returns.std() * np.sqrt(252)
        assert abs(result['point_estimate'] - naive_sharpe) < 1e-9

    def test_ci_ordering(self, synthetic_returns):
        result = stationary_bootstrap_sharpe(synthetic_returns, n_reps=300, random_seed=2)
        assert result['ci_lower'] <= result['point_estimate'] or \
               result['point_estimate'] <= result['ci_upper'] + 1e-9
        assert result['ci_lower'] <= result['ci_upper']

    def test_return_and_drawdown_cis_present(self, synthetic_returns):
        result = stationary_bootstrap_sharpe(synthetic_returns, n_reps=200, random_seed=3)
        for key in ['return_ci_lower', 'return_ci_upper',
                    'max_dd_ci_lower', 'max_dd_ci_upper',
                    'vol_ci_lower', 'vol_ci_upper']:
            assert key in result
        assert result['return_ci_lower'] <= result['return_ci_upper']
        assert result['max_dd_ci_lower'] <= result['max_dd_ci_upper']

    def test_too_short_series_returns_empty(self):
        short_rets = pd.Series([0.01, -0.01, 0.005],
                               index=pd.date_range('2024-01-01', periods=3))
        result = stationary_bootstrap_sharpe(short_rets, n_reps=100)
        assert result['n_reps'] == 0


class TestRandomPortfolios:

    def test_random_distribution_centred(self, synthetic_price_panel):
        daily_returns = synthetic_price_panel.pct_change().dropna()
        result = random_portfolio_test(
            daily_returns, strategy_sharpe=1.0,
            n_holdings=5, n_simulations=500, random_seed=4,
        )
        assert result['n_simulations'] > 0
        assert 'random_mean' in result
        # The mean of random Sharpes should not be wildly far from zero
        assert abs(result['random_mean']) < 5.0

    def test_strategy_above_distribution_high_percentile(self, synthetic_price_panel):
        daily_returns = synthetic_price_panel.pct_change().dropna()
        # Set strategy_sharpe absurdly high so percentile rank should be ~100
        result = random_portfolio_test(
            daily_returns, strategy_sharpe=99.0,
            n_holdings=5, n_simulations=500, random_seed=5,
        )
        assert result['percentile_rank'] >= 99

    def test_strategy_below_distribution_low_percentile(self, synthetic_price_panel):
        daily_returns = synthetic_price_panel.pct_change().dropna()
        result = random_portfolio_test(
            daily_returns, strategy_sharpe=-99.0,
            n_holdings=5, n_simulations=500, random_seed=6,
        )
        assert result['percentile_rank'] <= 1


class TestSubPeriodAnalysis:

    def test_includes_year_regime_and_full(self, synthetic_returns):
        df = sub_period_analysis(synthetic_returns)
        assert len(df) > 0
        assert 'period_type' in df.columns
        types = set(df['period_type'].unique())
        # At least one year + one full-period row
        assert 'year' in types
        assert 'full' in types

    def test_empty_returns_returns_empty(self):
        df = sub_period_analysis(pd.Series(dtype=float))
        assert len(df) == 0


class TestWeightSensitivity:

    def test_steps_count(self, base_config, synthetic_returns):
        def stub_run(_cfg):
            return synthetic_returns

        df = weight_sensitivity_analysis(stub_run, base_config, steps=5)
        assert len(df) == 5
        assert df['value_weight'].min() == pytest.approx(0.0)
        assert df['value_weight'].max() == pytest.approx(1.0)

    def test_metrics_present(self, base_config, synthetic_returns):
        def stub_run(_cfg):
            return synthetic_returns

        df = weight_sensitivity_analysis(stub_run, base_config, steps=3)
        for col in ['value_weight', 'sentiment_weight', 'sharpe_ratio',
                    'annualised_return', 'max_drawdown']:
            assert col in df.columns
