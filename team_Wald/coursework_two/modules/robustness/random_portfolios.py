"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Random portfolio comparison (skill vs luck)
Project : CW2 - Value-Sentiment Investment Strategy

Generates 10,000 random portfolios of the same size as the strategy
portfolio and computes their Sharpe ratios.  Compares the strategy's
Sharpe to the random distribution to assess whether the performance
is attributable to signal skill or random chance.

Ref: Part A §A8 — Test 5
"""

import logging

import numpy as np
import pandas as pd

from modules.analytics.performance import TRADING_DAYS_PER_YEAR

logger = logging.getLogger(__name__)


def random_portfolio_test(
    daily_returns: pd.DataFrame,
    strategy_sharpe: float,
    n_holdings: int = 40,
    n_simulations: int = 10000,
    risk_free_rate: float = 0.04,
    random_seed: int = 42,
) -> dict:
    """Compare strategy Sharpe to distribution of random portfolios.

    Randomly selects n_holdings stocks from the universe, equal-weights
    them, and computes the Sharpe ratio.  Repeats n_simulations times.

    The strategy's percentile rank in this distribution quantifies
    the probability that the observed Sharpe could be achieved by
    random selection alone.

    :param daily_returns: Full daily return matrix (dates × tickers)
    :type daily_returns: pd.DataFrame
    :param strategy_sharpe: Sharpe ratio of the actual strategy
    :type strategy_sharpe: float
    :param n_holdings: Number of stocks in each random portfolio
    :type n_holdings: int
    :param n_simulations: Number of random portfolios to generate
    :type n_simulations: int
    :param risk_free_rate: Annual risk-free rate
    :type risk_free_rate: float
    :param random_seed: Random seed for reproducibility
    :type random_seed: int
    :returns: Dict with random Sharpe distribution, percentile rank
    :rtype: dict
    """
    rng = np.random.RandomState(random_seed)
    rf_daily = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1

    # Filter to tickers with sufficient data (>80% non-null)
    valid_tickers = daily_returns.columns[
        daily_returns.notna().mean() > 0.8
    ].tolist()

    if len(valid_tickers) < n_holdings:
        logger.warning(
            "Only %d valid tickers (need %d) — reducing n_holdings",
            len(valid_tickers), n_holdings,
        )
        n_holdings = max(5, len(valid_tickers) // 2)

    random_sharpes = np.zeros(n_simulations)

    for i in range(n_simulations):
        # Randomly select n_holdings stocks
        selected = rng.choice(valid_tickers, size=n_holdings, replace=False)

        # Equal-weight portfolio return
        port_ret = daily_returns[selected].mean(axis=1).dropna()

        if len(port_ret) < 60:
            random_sharpes[i] = np.nan
            continue

        excess = port_ret - rf_daily
        mean_ex = excess.mean()
        std_ret = port_ret.std()

        if std_ret > 0:
            random_sharpes[i] = mean_ex / std_ret * np.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            random_sharpes[i] = 0.0

    # Remove NaN
    random_sharpes = random_sharpes[~np.isnan(random_sharpes)]

    # Percentile rank of strategy Sharpe in random distribution
    percentile_rank = (random_sharpes < strategy_sharpe).mean() * 100

    result = {
        'strategy_sharpe': strategy_sharpe,
        'random_mean': random_sharpes.mean(),
        'random_std': random_sharpes.std(),
        'random_median': np.median(random_sharpes),
        'percentile_rank': percentile_rank,
        'prob_random_beats': (random_sharpes >= strategy_sharpe).mean(),
        'n_simulations': len(random_sharpes),
        'n_holdings': n_holdings,
        'random_sharpes': random_sharpes,
    }

    logger.info(
        "Random portfolio test: strategy Sharpe=%.3f at %.1f%% percentile "
        "(random mean=%.3f, std=%.3f, P(random beats)=%.1f%%)",
        strategy_sharpe, percentile_rank,
        random_sharpes.mean(), random_sharpes.std(),
        result['prob_random_beats'] * 100,
    )
    return result
