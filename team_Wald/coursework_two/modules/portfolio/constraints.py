"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Portfolio constraints (position caps, sector limits)
Project : CW2 - Value-Sentiment Investment Strategy

Applies portfolio construction constraints:
  - Max 5% per stock (position limit)
  - Max 25% per GICS sector (sector concentration limit)
  - Min 20 holdings (diversification floor)

Uses iterative redistribution: excess weight from capped positions
is spread proportionally among uncapped positions until all
constraints are satisfied.

Ref: Part A §A5
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def apply_constraints(
    weights: pd.Series,
    sector_map: dict,
    max_position: float = 0.05,
    max_sector: float = 0.25,
    min_holdings: int = 20,
    max_iterations: int = 50,
) -> pd.Series:
    """Apply position and sector constraints to raw portfolio weights.

    Iteratively caps individual positions and sector exposures,
    redistributing excess weight proportionally among uncapped
    holdings until convergence or max iterations.

    :param weights: Raw unconstrained weights indexed by ticker
    :type weights: pd.Series
    :param sector_map: Dict mapping ticker → GICS sector
    :type sector_map: dict
    :param max_position: Maximum weight per individual stock
    :type max_position: float
    :param max_sector: Maximum aggregate weight per GICS sector
    :type max_sector: float
    :param min_holdings: Minimum number of holdings
    :type min_holdings: int
    :param max_iterations: Safety limit for convergence loop
    :type max_iterations: int
    :returns: Constrained weights summing to 1.0
    :rtype: pd.Series
    :raises ValueError: If fewer than min_holdings stocks have positive weight
    """
    w = weights.copy()

    # Remove zero or negative weights
    w = w[w > 0]

    if len(w) < min_holdings:
        logger.warning(
            "Only %d stocks with positive weight (min=%d) — keeping all",
            len(w), min_holdings,
        )

    # Normalise to sum to 1
    if w.sum() > 0:
        w = w / w.sum()

    # Iterative constraint enforcement
    for iteration in range(max_iterations):
        violated = False

        # --- Position cap ---
        capped = w > max_position
        if capped.any():
            excess = (w[capped] - max_position).sum()
            w[capped] = max_position
            uncapped = ~capped & (w > 0)
            if uncapped.sum() > 0:
                w[uncapped] += excess * w[uncapped] / w[uncapped].sum()
            violated = True

        # --- Sector cap ---
        sectors = pd.Series({t: sector_map.get(t, 'Unknown') for t in w.index})
        sector_weights = w.groupby(sectors).sum()
        for sector, sector_wt in sector_weights.items():
            if sector_wt > max_sector:
                sector_tickers = sectors[sectors == sector].index
                in_sector = w[sector_tickers]

                # Scale down proportionally within sector
                scale_factor = max_sector / sector_wt
                excess = (in_sector * (1 - scale_factor)).sum()
                w[sector_tickers] = in_sector * scale_factor

                # Redistribute excess to other sectors
                other_tickers = sectors[sectors != sector].index
                other = w[other_tickers]
                if other.sum() > 0:
                    w[other_tickers] += excess * other / other.sum()
                violated = True

        if not violated:
            break

    # Final normalisation to exactly 1.0
    if w.sum() > 0:
        w = w / w.sum()

    n_holdings = (w > 1e-8).sum()
    sectors_used = pd.Series({t: sector_map.get(t, 'Unknown') for t in w.index})
    max_sector_actual = w.groupby(sectors_used).sum().max()

    logger.info(
        "Constraints applied: %d holdings, max position=%.4f, max sector=%.4f "
        "(converged in %d iterations)",
        n_holdings, w.max(), max_sector_actual, iteration + 1,
    )
    return w
