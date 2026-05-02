"""Robustness-testing layer for CW2.

Implements all six robustness tests required by Part A §A8 of the
master guide:

    * :func:`modules.robustness.sensitivity.weight_sensitivity_analysis`
      — sweep the value/sentiment composite weight from 0/100 to 100/0
      in 5% steps (Test 1, Table 4).
    * :func:`modules.robustness.sensitivity.threshold_sensitivity_analysis`
      — grid over selection percentile {10, 15, 20, 25, 30}% × D/E
      cutoff {1.5, 2.0, 2.5, 3.0} (Test 2, Table 5).
    * :func:`modules.robustness.sensitivity.sub_period_analysis` —
      year-by-year, regime split (2021-23 vs 2023-25), and full-period
      decomposition (Test 3, Table 3).
    * :func:`modules.robustness.bootstrap.stationary_bootstrap_sharpe` —
      Politis & Romano (1994) stationary block bootstrap with 2,500 reps;
      reports CIs for Sharpe, return, volatility, and max drawdown
      (Test 4, Table 8).
    * :func:`modules.robustness.random_portfolios.random_portfolio_test`
      — 10,000 random equal-weight portfolios of the same size as the
      strategy to assess skill vs luck (Test 5).
    * :func:`modules.robustness.sensitivity.sector_attribution_analysis`
      — leave-one-sector-out re-runs of the backtest (Test 6).
"""

from modules.robustness.bootstrap import stationary_bootstrap_sharpe
from modules.robustness.random_portfolios import random_portfolio_test
from modules.robustness.sensitivity import (
    sector_attribution_analysis,
    sub_period_analysis,
    threshold_sensitivity_analysis,
    weight_sensitivity_analysis,
)

__all__ = [
    'weight_sensitivity_analysis',
    'threshold_sensitivity_analysis',
    'sub_period_analysis',
    'sector_attribution_analysis',
    'stationary_bootstrap_sharpe',
    'random_portfolio_test',
]
