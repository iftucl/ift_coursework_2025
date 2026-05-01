"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Point-in-time investable universe construction
Project : CW2 - Value-Sentiment Investment Strategy

Constructs the investable universe at each rebalance date, accounting
for survivorship bias by including delisted tickers that were active
at the rebalance date.

Ref: Elton et al. (1996) — survivorship bias of 0.9–2.1% annually.
Ref: Part A §A6 — point-in-time discipline.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class UniverseConstructor:
    """Build point-in-time investable universe for each rebalance.

    Identifies which stocks were actively trading at a given date by
    checking for recent price data in the daily_prices table.  Stocks
    with no price data in the 10 trading days before rebalance are
    excluded (likely delisted or suspended).

    :param company_df: Full company_static DataFrame
    :type company_df: pd.DataFrame
    :param prices_df: Full pivoted price history (dates × tickers)
    :type prices_df: pd.DataFrame
    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, company_df: pd.DataFrame, prices_df: pd.DataFrame, config: dict):
        # Normalise tickers (strip + upper) so joins with CW1 are exact.
        cdf = company_df.copy()
        cdf['symbol'] = cdf['symbol'].astype(str).str.strip().str.upper()
        self._companies = cdf.set_index('symbol')
        # Likewise normalise the price-panel columns
        prices_norm = prices_df.copy()
        prices_norm.columns = [str(c).strip().upper() for c in prices_norm.columns]
        self._prices = prices_norm
        self._config = config
        self._activity_window = 10  # Business days to check for activity

    def get_universe(self, rebalance_date: pd.Timestamp) -> pd.DataFrame:
        """Return the investable universe at a specific rebalance date.

        A stock is considered active if it has at least one non-null
        price in the 10 trading days up to and including the rebalance
        date.  This point-in-time approach avoids survivorship bias.

        :param rebalance_date: The rebalance date to construct universe for
        :type rebalance_date: pd.Timestamp
        :returns: DataFrame with symbol, gics_sector, and is_active columns
        :rtype: pd.DataFrame
        """
        # Find price data up to rebalance date
        mask = self._prices.index <= rebalance_date
        available_prices = self._prices.loc[mask]

        if len(available_prices) == 0:
            logger.warning("No price data available before %s", rebalance_date)
            return pd.DataFrame()

        # Check last N trading days for activity
        recent_prices = available_prices.tail(self._activity_window)
        active_tickers = recent_prices.columns[recent_prices.notna().any()].tolist()

        # Build universe DataFrame with GICS sector information
        universe = self._companies.loc[
            self._companies.index.isin(active_tickers)
        ].copy()
        universe = universe.reset_index()
        universe.rename(columns={'index': 'symbol'}, inplace=True)

        # Ensure symbol column exists properly
        if 'symbol' not in universe.columns and universe.index.name == 'symbol':
            universe = universe.reset_index()

        total = len(self._companies)
        active = len(universe)
        inactive = total - active
        logger.info(
            "Universe at %s: %d active / %d inactive / %d total "
            "(%.1f%% survivorship, %.1f%% attrition)",
            rebalance_date.strftime('%Y-%m-%d'),
            active, inactive, total,
            active / total * 100 if total > 0 else 0,
            inactive / total * 100 if total > 0 else 0,
        )
        return universe

    def get_sector_map(self) -> dict:
        """Return a mapping from ticker to GICS sector.

        :returns: Dict mapping symbol → gics_sector
        :rtype: dict
        """
        return self._companies['gics_sector'].to_dict()

    def get_all_sectors(self) -> list:
        """Return sorted list of unique GICS sectors.

        :returns: List of unique GICS sector names
        :rtype: list
        """
        return sorted(self._companies['gics_sector'].dropna().unique().tolist())
