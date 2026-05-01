"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Transaction cost model
Project : CW2 - Value-Sentiment Investment Strategy

Calculates transaction costs from portfolio turnover using
a flat per-trade cost model.  Default: 25 bps one-way baseline,
50 bps stress test.

Ref: Part A §A6
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TransactionCostModel:
    """Model transaction costs from portfolio turnover.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, config: dict):
        self._baseline_bps = config['costs']['transaction_cost_bps']
        self._stress_bps = config['costs']['stress_test_bps']

    def calculate(
        self,
        old_weights: pd.Series,
        new_weights: pd.Series,
        use_stress: bool = False,
    ) -> float:
        """Compute transaction cost for a single rebalance.

        Cost = sum(|w_new - w_old|) × cost_bps / 10000

        The full round-trip turnover is halved because the cost
        rate is applied to one-way trades.

        :param old_weights: Pre-rebalance portfolio weights
        :type old_weights: pd.Series
        :param new_weights: Post-rebalance target weights
        :type new_weights: pd.Series
        :param use_stress: If True, use stress-test cost rate
        :type use_stress: bool
        :returns: Total transaction cost as a fraction of portfolio value
        :rtype: float
        """
        bps = self._stress_bps if use_stress else self._baseline_bps
        cost_rate = bps / 10000.0

        # Align indices
        all_tickers = old_weights.index.union(new_weights.index)
        old_aligned = old_weights.reindex(all_tickers, fill_value=0.0)
        new_aligned = new_weights.reindex(all_tickers, fill_value=0.0)

        # One-way turnover
        turnover = (new_aligned - old_aligned).abs().sum() / 2.0
        cost = turnover * cost_rate

        logger.debug(
            "Transaction cost: turnover=%.4f, rate=%d bps, cost=%.6f",
            turnover, bps, cost,
        )
        return cost
