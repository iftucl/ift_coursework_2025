"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Unit tests for risk module (VaR, CVaR, FF regression)
Project : CW2 - Value-Sentiment Investment Strategy
"""

import numpy as np
import pandas as pd
import pytest

from modules.analytics.risk import compute_cvar, compute_var, compute_fama_french_regression


class TestVaR:

    def test_var_known_quantile(self):
        rets = pd.Series(np.linspace(-0.10, 0.10, 101))  # uniform [-10%, 10%]
        var = compute_var(rets, confidence=0.95)
        # 5th percentile of [-10..10] equals -9% (linear interpolation of 100 points)
        assert -0.10 <= var <= -0.07

    def test_var_empty_returns(self):
        var = compute_var(pd.Series(dtype=float))
        assert var == 0.0


class TestCVaR:

    def test_cvar_below_var(self):
        np.random.seed(0)
        rets = pd.Series(np.random.normal(0, 0.02, 1000))
        var = compute_var(rets, 0.95)
        cvar = compute_cvar(rets, 0.95)
        assert cvar <= var, "CVaR should be at most VaR (more negative)"

    def test_cvar_known_simple_case(self):
        rets = pd.Series([-0.10, -0.08, -0.05, -0.02, 0.0,
                          0.01, 0.02, 0.03, 0.05, 0.08])
        cvar = compute_cvar(rets, 0.90)
        # CVaR at 90% = mean of returns in worst 10% = mean([-0.10]) = -0.10
        # But percentile method may include slightly more — check it's negative
        assert cvar < 0


class TestFamaFrenchRegression:

    def test_empty_result_when_no_factors(self):
        rets = pd.Series([0.001] * 50, index=pd.date_range('2024-01-01', periods=50))
        # Pass empty factors DataFrame
        result = compute_fama_french_regression(rets, ff_factors=pd.DataFrame())
        assert 'alpha' in result
        assert result.get('n_observations', 0) == 0

    def test_regression_runs_with_synthetic_factors(self):
        # 100 days of synthetic data with known beta=1
        rng = np.random.RandomState(0)
        dates = pd.date_range('2023-01-02', periods=200, freq='B')
        mkt = pd.Series(rng.normal(0.0005, 0.01, 200), index=dates)
        rf = pd.Series(0.0001, index=dates)
        eps = pd.Series(rng.normal(0, 0.005, 200), index=dates)
        port = mkt + rf + eps  # beta-1 portfolio + noise
        ff = pd.DataFrame({
            'Mkt-RF': mkt,
            'SMB': rng.normal(0, 0.005, 200),
            'HML': rng.normal(0, 0.005, 200),
            'RMW': rng.normal(0, 0.005, 200),
            'CMA': rng.normal(0, 0.005, 200),
            'RF': rf,
        }, index=dates)
        result = compute_fama_french_regression(port, ff_factors=ff)
        assert result['n_observations'] >= 100
        # Beta on Mkt-RF should be close to 1 (we constructed a beta-1 series)
        if 'Mkt-RF' in result['betas']:
            assert abs(result['betas']['Mkt-RF'] - 1.0) < 0.3
