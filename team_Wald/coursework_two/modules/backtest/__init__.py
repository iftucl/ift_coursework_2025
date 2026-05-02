"""Backtest layer for CW2.

Implements Part A §A6 of the master guide:

    * :class:`modules.backtest.backtester.Backtester` — quarterly
      rebalance loop with point-in-time data, T+1 close execution,
      90-day reporting lag, vectorised intra-period weight drift, and
      end-of-period drifted weights flowing into the next rebalance.
    * :class:`modules.backtest.transaction_costs.TransactionCostModel` —
      flat 25 bps one-way baseline / 50 bps stress cost.
    * :func:`modules.backtest.rebalance_schedule.get_rebalance_dates` —
      quarterly date generator (last business day of Jan/Apr/Jul/Oct)
      snapped to the available trading calendar.
"""

from modules.backtest.backtester import Backtester
from modules.backtest.rebalance_schedule import get_rebalance_dates
from modules.backtest.transaction_costs import TransactionCostModel

__all__ = ['Backtester', 'TransactionCostModel', 'get_rebalance_dates']
