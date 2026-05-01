"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Sensitivity and robustness testing
Project : CW2 - Value-Sentiment Investment Strategy

Implements 4 of the 6 robustness tests:
  1. Weight sensitivity: vary value/sentiment weights from 0/100 to 100/0
  2. Threshold sensitivity: vary top %, D/E limit
  3. Sub-period analysis: year-by-year + regime splits
  6. Sector attribution: leave-one-sector-out

Tests 4 (Bootstrap CIs) and 5 (Random portfolios) are in
separate modules.

Ref: Part A §A8
"""

import logging
from copy import deepcopy

import numpy as np
import pandas as pd

from modules.analytics.performance import compute_performance_summary

logger = logging.getLogger(__name__)


def weight_sensitivity_analysis(
    run_backtest_fn,
    base_config: dict,
    steps: int = 21,
) -> pd.DataFrame:
    """Test sensitivity of Sharpe ratio to value/sentiment weight mix.

    Varies value_weight from 0.0 to 1.0 in equal steps, with
    sentiment_weight = 1 - value_weight.

    :param run_backtest_fn: Callable that takes config and returns
                            portfolio returns Series
    :type run_backtest_fn: callable
    :param base_config: Base backtest configuration
    :type base_config: dict
    :param steps: Number of weight combinations to test
    :type steps: int
    :returns: DataFrame with value_weight, sentiment_weight, sharpe, return
    :rtype: pd.DataFrame
    """
    results = []
    weights = np.linspace(0, 1, steps)

    for vw in weights:
        sw = 1.0 - vw
        config = deepcopy(base_config)
        config['scoring']['value_weight'] = round(vw, 2)
        config['scoring']['sentiment_weight'] = round(sw, 2)

        try:
            returns = run_backtest_fn(config)
            metrics = compute_performance_summary(returns)
            results.append({
                'value_weight': round(vw, 2),
                'sentiment_weight': round(sw, 2),
                'sharpe_ratio': metrics['sharpe_ratio'],
                'annualised_return': metrics['annualised_return'],
                'max_drawdown': metrics['max_drawdown'],
                'annualised_volatility': metrics['annualised_volatility'],
            })
        except Exception as e:
            logger.warning("Weight sensitivity failed at vw=%.2f: %s", vw, e)
            results.append({
                'value_weight': round(vw, 2),
                'sentiment_weight': round(sw, 2),
                'sharpe_ratio': np.nan,
                'annualised_return': np.nan,
                'max_drawdown': np.nan,
                'annualised_volatility': np.nan,
            })

    df = pd.DataFrame(results)
    logger.info("Weight sensitivity: tested %d combinations", len(df))
    return df


def threshold_sensitivity_analysis(
    run_backtest_fn,
    base_config: dict,
    percentiles: list = None,
    de_limits: list = None,
) -> pd.DataFrame:
    """Test sensitivity to screening thresholds.

    Varies the top percentile (10–30%) and D/E limit (1.5–3.0).

    :param run_backtest_fn: Callable returning portfolio returns
    :type run_backtest_fn: callable
    :param base_config: Base backtest configuration
    :type base_config: dict
    :param percentiles: List of selection percentiles to test
    :type percentiles: list or None
    :param de_limits: List of max D/E ratios to test
    :type de_limits: list or None
    :returns: DataFrame with threshold combos and performance
    :rtype: pd.DataFrame
    """
    if percentiles is None:
        percentiles = [0.10, 0.15, 0.20, 0.25, 0.30]
    if de_limits is None:
        de_limits = [1.5, 2.0, 2.5, 3.0]

    results = []
    for pctl in percentiles:
        for de in de_limits:
            config = deepcopy(base_config)
            config['scoring']['selection_percentile'] = pctl
            config['scoring']['max_debt_equity'] = de

            try:
                returns = run_backtest_fn(config)
                metrics = compute_performance_summary(returns)
                results.append({
                    'selection_percentile': pctl,
                    'max_debt_equity': de,
                    'sharpe_ratio': metrics['sharpe_ratio'],
                    'annualised_return': metrics['annualised_return'],
                    'max_drawdown': metrics['max_drawdown'],
                    'n_holdings_approx': int(1.0 / pctl * 50),  # Approximate
                })
            except Exception as e:
                logger.warning("Threshold test failed pctl=%.2f, de=%.1f: %s", pctl, de, e)

    df = pd.DataFrame(results)
    logger.info("Threshold sensitivity: tested %d combinations", len(df))
    return df


def sub_period_analysis(
    returns: pd.Series,
    benchmark_returns: pd.Series = None,
    regime_splits: list = None,
) -> pd.DataFrame:
    """Compute year-by-year, regime-split, and full-period performance.

    Per Part A §A8 Test 3 of the master guide, this analysis decomposes
    portfolio performance into:

        1. **Year-by-year** rows (one per calendar year with ≥20 trading days).
        2. **Regime splits** (default: ``2021-2023`` early vs ``2023-2025``
           late, i.e. value-resurgence vs rates-normalisation regimes).
        3. **Full period** row.

    :param returns: Full daily portfolio returns
    :type returns: pd.Series
    :param benchmark_returns: Benchmark returns for relative metrics
    :type benchmark_returns: pd.Series or None
    :param regime_splits: Optional list of ``(label, start, end)`` tuples
                          (dates as YYYY-MM-DD strings)
    :type regime_splits: list or None
    :returns: DataFrame with one row per period
    :rtype: pd.DataFrame
    """
    results = []
    if len(returns) == 0:
        return pd.DataFrame()

    # Year-by-year
    for year in sorted(returns.index.year.unique()):
        year_ret = returns[returns.index.year == year]
        if len(year_ret) < 20:
            continue
        bm_ret = None
        if benchmark_returns is not None:
            bm_ret = benchmark_returns[benchmark_returns.index.year == year]
        metrics = compute_performance_summary(year_ret, bm_ret, portfolio_name=str(year))
        metrics['period'] = str(year)
        metrics['period_type'] = 'year'
        results.append(metrics)

    # Regime splits — defaults aligned with PDF "2021-23 vs 2023-25"
    if regime_splits is None:
        regime_splits = [
            ('2021-2023 (Value Resurgence)', '2021-01-01', '2023-06-30'),
            ('2023-2025 (Rates Normalisation)', '2023-07-01', '2025-12-31'),
        ]

    for label, start, end in regime_splits:
        sub = returns.loc[(returns.index >= start) & (returns.index <= end)]
        if len(sub) < 20:
            continue
        bm_sub = None
        if benchmark_returns is not None:
            bm_sub = benchmark_returns.loc[
                (benchmark_returns.index >= start) & (benchmark_returns.index <= end)
            ]
        metrics = compute_performance_summary(sub, bm_sub, portfolio_name=label)
        metrics['period'] = label
        metrics['period_type'] = 'regime'
        results.append(metrics)

    # Full period
    full_metrics = compute_performance_summary(returns, benchmark_returns, portfolio_name='Full Period')
    full_metrics['period'] = 'Full'
    full_metrics['period_type'] = 'full'
    results.append(full_metrics)

    return pd.DataFrame(results)


def sector_attribution_analysis(
    run_backtest_fn,
    base_config: dict,
    sectors: list,
) -> pd.DataFrame:
    """Leave-one-sector-out analysis to identify sector dependence.

    Re-runs the backtest excluding each sector one at a time to
    determine if performance is driven by a single sector.

    :param run_backtest_fn: Callable returning portfolio returns
    :type run_backtest_fn: callable
    :param base_config: Base backtest configuration
    :type base_config: dict
    :param sectors: List of GICS sector names
    :type sectors: list
    :returns: DataFrame showing impact of excluding each sector
    :rtype: pd.DataFrame
    """
    results = []

    # Baseline (all sectors)
    try:
        base_returns = run_backtest_fn(base_config)
        base_metrics = compute_performance_summary(base_returns)
        results.append({
            'excluded_sector': 'None (Baseline)',
            'sharpe_ratio': base_metrics['sharpe_ratio'],
            'annualised_return': base_metrics['annualised_return'],
            'sharpe_change': 0.0,
        })
    except Exception:
        base_metrics = {'sharpe_ratio': 0, 'annualised_return': 0}

    for sector in sectors:
        config = deepcopy(base_config)
        config['_exclude_sector'] = sector  # Custom flag for backtest

        try:
            returns = run_backtest_fn(config)
            metrics = compute_performance_summary(returns)
            results.append({
                'excluded_sector': sector,
                'sharpe_ratio': metrics['sharpe_ratio'],
                'annualised_return': metrics['annualised_return'],
                'sharpe_change': metrics['sharpe_ratio'] - base_metrics['sharpe_ratio'],
            })
        except Exception as e:
            logger.warning("Sector attribution failed for %s: %s", sector, e)

    df = pd.DataFrame(results)
    logger.info("Sector attribution: tested %d sectors", len(df))
    return df
