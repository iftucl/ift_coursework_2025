"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Rebalance schedule generation
Project : CW2 - Value-Sentiment Investment Strategy

Generates quarterly rebalance dates (end of Jan, Apr, Jul, Oct)
aligned to business days.  Ensures the backtester trades on valid
market dates.

Ref: Part A §A5 — quarterly rebalancing
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def get_rebalance_dates(
    start_date: str,
    end_date: str,
    months: list = None,
    price_dates: pd.DatetimeIndex = None,
) -> list:
    """Generate quarterly rebalance dates within the backtest period.

    Each rebalance occurs on the last business day of the specified
    months.  If a price calendar is provided, dates are snapped to
    the nearest preceding trading day.

    :param start_date: Backtest start (YYYY-MM-DD)
    :type start_date: str
    :param end_date: Backtest end (YYYY-MM-DD)
    :type end_date: str
    :param months: List of rebalance months (default [1, 4, 7, 10])
    :type months: list or None
    :param price_dates: Available trading dates from price data
    :type price_dates: pd.DatetimeIndex or None
    :returns: Sorted list of pd.Timestamp rebalance dates
    :rtype: list
    """
    if months is None:
        months = [1, 4, 7, 10]

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    rebalance_dates = []
    current_year = start.year
    end_year = end.year

    for year in range(current_year, end_year + 1):
        for month in months:
            # Last business day of the month
            month_end = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
            # Roll to business day if weekend
            bday = pd.offsets.BDay(0)
            rebal_date = month_end - bday if month_end.weekday() >= 5 else month_end

            # Snap to nearest prior trading day if price calendar available
            if price_dates is not None:
                valid = price_dates[price_dates <= rebal_date]
                if len(valid) > 0:
                    rebal_date = valid[-1]

            if start <= rebal_date <= end:
                rebalance_dates.append(rebal_date)

    rebalance_dates = sorted(set(rebalance_dates))
    logger.info(
        "Generated %d rebalance dates from %s to %s",
        len(rebalance_dates),
        rebalance_dates[0].strftime('%Y-%m-%d') if rebalance_dates else 'N/A',
        rebalance_dates[-1].strftime('%Y-%m-%d') if rebalance_dates else 'N/A',
    )
    return rebalance_dates
