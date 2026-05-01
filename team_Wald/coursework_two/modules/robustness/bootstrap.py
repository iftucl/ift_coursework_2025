"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Stationary bootstrap confidence intervals
Project : CW2 - Value-Sentiment Investment Strategy

Uses Politis & Romano (1994) stationary bootstrap to compute
95% confidence intervals for the Sharpe ratio and other metrics.
2,500 replications.

This addresses serial dependence in return data that invalidates
naive i.i.d. bootstrap.

Ref: Part A §A8 — Test 4
Academic: Politis & Romano (1994) — Stationary bootstrap, JASA.
"""

import logging

import numpy as np
import pandas as pd

from modules.analytics.performance import TRADING_DAYS_PER_YEAR

logger = logging.getLogger(__name__)


def stationary_bootstrap_sharpe(
    returns: pd.Series,
    n_reps: int = 2500,
    block_length: float = 10.0,
    risk_free_rate: float = 0.04,
    confidence: float = 0.95,
    random_seed: int = 42,
) -> dict:
    """Compute bootstrap confidence intervals for the Sharpe ratio.

    Uses the stationary bootstrap of Politis & Romano (1994), which
    generates random block lengths from a geometric distribution,
    preserving time-series dependence structure.

    :param returns: Daily portfolio return series
    :type returns: pd.Series
    :param n_reps: Number of bootstrap replications
    :type n_reps: int
    :param block_length: Expected block length (geometric parameter)
    :type block_length: float
    :param risk_free_rate: Annual risk-free rate
    :type risk_free_rate: float
    :param confidence: Confidence level for intervals (e.g. 0.95)
    :type confidence: float
    :param random_seed: Random seed for reproducibility
    :type random_seed: int
    :returns: Dict with point estimate, lower/upper CIs, bootstrap Sharpes
    :rtype: dict
    """
    rng = np.random.RandomState(random_seed)
    returns_arr = returns.dropna().values
    n = len(returns_arr)

    if n < 30:
        logger.warning("Too few observations (%d) for bootstrap", n)
        return _empty_bootstrap_result()

    rf_daily = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    p = 1.0 / block_length  # Probability of starting new block

    bootstrap_sharpes = np.zeros(n_reps)
    bootstrap_returns = np.zeros(n_reps)
    bootstrap_max_dds = np.zeros(n_reps)
    bootstrap_vols = np.zeros(n_reps)

    sqrt_year = np.sqrt(TRADING_DAYS_PER_YEAR)
    # Use ddof=1 (sample std) everywhere to match pandas' default so
    # the bootstrap point estimate is exactly consistent with
    # ``compute_performance_summary`` which uses ``pd.Series.std()``.

    for rep in range(n_reps):
        # Generate stationary bootstrap sample
        sample = _stationary_bootstrap_sample(returns_arr, n, p, rng)

        excess = sample - rf_daily
        mean_excess = excess.mean()
        std_sample = sample.std(ddof=1)
        bootstrap_sharpes[rep] = (mean_excess / std_sample * sqrt_year) if std_sample > 0 else 0.0

        # Annualised return on bootstrap sample
        total_growth = float(np.prod(1.0 + sample))
        if total_growth > 0:
            bootstrap_returns[rep] = total_growth ** (TRADING_DAYS_PER_YEAR / n) - 1.0
        else:
            bootstrap_returns[rep] = -1.0
        bootstrap_vols[rep] = std_sample * sqrt_year

        # Maximum drawdown on bootstrap sample
        cum = np.cumprod(1.0 + sample)
        running_max = np.maximum.accumulate(cum)
        dd = (cum - running_max) / running_max
        bootstrap_max_dds[rep] = dd.min() if len(dd) > 0 else 0.0

    # Point estimates on the original series (ddof=1 to match pandas)
    excess_orig = returns_arr - rf_daily
    std_orig = returns_arr.std(ddof=1)
    point_sharpe = excess_orig.mean() / std_orig * sqrt_year if std_orig > 0 else 0.0
    total_orig = float(np.prod(1.0 + returns_arr))
    point_return = total_orig ** (TRADING_DAYS_PER_YEAR / n) - 1.0 if total_orig > 0 else -1.0
    point_vol = std_orig * sqrt_year
    cum_orig = np.cumprod(1.0 + returns_arr)
    running_max_orig = np.maximum.accumulate(cum_orig)
    point_max_dd = float(((cum_orig - running_max_orig) / running_max_orig).min())

    # Confidence intervals (percentile method)
    alpha = 1 - confidence
    lo_q, hi_q = alpha / 2 * 100, (1 - alpha / 2) * 100

    def _ci(arr):
        return float(np.percentile(arr, lo_q)), float(np.percentile(arr, hi_q))

    sharpe_lo, sharpe_hi = _ci(bootstrap_sharpes)
    return_lo, return_hi = _ci(bootstrap_returns)
    vol_lo, vol_hi = _ci(bootstrap_vols)
    dd_lo, dd_hi = _ci(bootstrap_max_dds)

    prob_positive = float((bootstrap_sharpes > 0).mean())

    result = {
        # Sharpe (primary)
        'point_estimate': point_sharpe,
        'ci_lower': sharpe_lo,
        'ci_upper': sharpe_hi,
        'confidence_level': confidence,
        'prob_sharpe_positive': prob_positive,
        'bootstrap_mean': float(bootstrap_sharpes.mean()),
        'bootstrap_std': float(bootstrap_sharpes.std()),
        'n_reps': n_reps,
        'block_length': block_length,
        'bootstrap_sharpes': bootstrap_sharpes,
        # Annualised return CI
        'return_point': point_return,
        'return_ci_lower': return_lo,
        'return_ci_upper': return_hi,
        # Annualised volatility CI
        'vol_point': point_vol,
        'vol_ci_lower': vol_lo,
        'vol_ci_upper': vol_hi,
        # Max drawdown CI
        'max_dd_point': point_max_dd,
        'max_dd_ci_lower': dd_lo,
        'max_dd_ci_upper': dd_hi,
    }

    logger.info(
        "Bootstrap (n=%d, block=%.0f): Sharpe %.3f [%.3f, %.3f], "
        "Return %.2f%% [%.2f%%, %.2f%%], MaxDD %.2f%% [%.2f%%, %.2f%%], "
        "P(Sharpe>0)=%.1f%%",
        n_reps, block_length,
        point_sharpe, sharpe_lo, sharpe_hi,
        point_return * 100, return_lo * 100, return_hi * 100,
        point_max_dd * 100, dd_lo * 100, dd_hi * 100,
        prob_positive * 100,
    )
    return result


def _stationary_bootstrap_sample(
    data: np.ndarray,
    n: int,
    p: float,
    rng: np.random.RandomState,
) -> np.ndarray:
    """Generate a single stationary bootstrap sample.

    Each observation either continues the current block (prob 1-p)
    or jumps to a random position (prob p), creating random-length
    blocks from a geometric distribution.

    :param data: Original data array
    :type data: np.ndarray
    :param n: Sample size
    :type n: int
    :param p: Block-break probability (1/expected_block_length)
    :type p: float
    :param rng: Random number generator
    :type rng: np.random.RandomState
    :returns: Bootstrap sample array
    :rtype: np.ndarray
    """
    sample = np.zeros(n)
    idx = rng.randint(0, n)

    for i in range(n):
        sample[i] = data[idx]
        # With probability p, jump to a new random position
        if rng.random() < p:
            idx = rng.randint(0, n)
        else:
            idx = (idx + 1) % n  # Wrap around

    return sample


def _empty_bootstrap_result() -> dict:
    """Return empty bootstrap result dict."""
    return {
        'point_estimate': 0.0,
        'ci_lower': 0.0,
        'ci_upper': 0.0,
        'confidence_level': 0.95,
        'prob_sharpe_positive': 0.0,
        'bootstrap_mean': 0.0,
        'bootstrap_std': 0.0,
        'n_reps': 0,
        'block_length': 0.0,
        'bootstrap_sharpes': np.array([]),
        'return_point': 0.0,
        'return_ci_lower': 0.0,
        'return_ci_upper': 0.0,
        'vol_point': 0.0,
        'vol_ci_lower': 0.0,
        'vol_ci_upper': 0.0,
        'max_dd_point': 0.0,
        'max_dd_ci_lower': 0.0,
        'max_dd_ci_upper': 0.0,
    }
