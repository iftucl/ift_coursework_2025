"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Turnover calculation and analysis
Project : CW2 - Value-Sentiment Investment Strategy

Calculates portfolio turnover metrics:
  - Per-rebalance one-way turnover
  - Average quarterly and annual turnover
  - Cumulative cost impact

Turnover = Sum(|w_new,i - w_old,i|) / 2 (one-way, per rebalance)

Ref: Part A §A7.4
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_turnover_summary(
    turnover_history: dict,
    cost_history: dict,
) -> dict:
    """Compute turnover summary statistics.

    :param turnover_history: Dict mapping rebalance_date → one-way turnover
    :type turnover_history: dict
    :param cost_history: Dict mapping rebalance_date → transaction cost
    :type cost_history: dict
    :returns: Dict with avg quarterly, annual turnover, cumulative costs
    :rtype: dict
    """
    if not turnover_history:
        return {
            'avg_quarterly_turnover': 0.0,
            'annual_turnover': 0.0,
            'cumulative_cost': 0.0,
            'n_rebalances': 0,
        }

    turnovers = pd.Series(turnover_history)
    costs = pd.Series(cost_history)

    avg_quarterly = turnovers.mean()
    # Approximately 4 rebalances per year
    annual_turnover = avg_quarterly * 4.0
    cumulative_cost = costs.sum()

    summary = {
        'avg_quarterly_turnover': avg_quarterly,
        'annual_turnover': annual_turnover,
        'cumulative_cost': cumulative_cost,
        'max_turnover': turnovers.max(),
        'min_turnover': turnovers.min(),
        'n_rebalances': len(turnovers),
    }

    logger.info(
        "Turnover: avg quarterly=%.4f, annual=%.4f, cum cost=%.6f over %d rebalances",
        avg_quarterly, annual_turnover, cumulative_cost, len(turnovers),
    )
    return summary


def compute_turnover_per_rebalance(
    weights_history: dict,
) -> pd.Series:
    """Compute one-way turnover at each rebalance date.

    :param weights_history: Dict mapping rebalance_date → weight Series
    :type weights_history: dict
    :returns: Series of turnover values indexed by date
    :rtype: pd.Series
    """
    dates = sorted(weights_history.keys())
    turnovers = {}

    for i in range(1, len(dates)):
        old_w = weights_history[dates[i - 1]]
        new_w = weights_history[dates[i]]

        all_tickers = old_w.index.union(new_w.index)
        old_aligned = old_w.reindex(all_tickers, fill_value=0.0)
        new_aligned = new_w.reindex(all_tickers, fill_value=0.0)

        turnover = (new_aligned - old_aligned).abs().sum() / 2.0
        turnovers[dates[i]] = turnover

    return pd.Series(turnovers, name='turnover')
