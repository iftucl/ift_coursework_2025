"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Diversification metrics
Project : CW2 - Value-Sentiment Investment Strategy

Computes diversification quality metrics:
  - HHI (Herfindahl-Hirschman Index): Sum(w_i²)
  - Effective N: 1/HHI
  - Sector concentration: max sector weight, sector count
  - VaR (95%) and CVaR (95%)

Ref: Part A §A7.5
"""

import logging

import numpy as np
import pandas as pd

from modules.analytics.risk import compute_cvar, compute_var

logger = logging.getLogger(__name__)


def compute_diversification_metrics(
    weights: pd.Series,
    sector_map: dict,
    returns: pd.Series = None,
) -> dict:
    """Compute diversification quality metrics for a portfolio.

    :param weights: Portfolio weights indexed by ticker
    :type weights: pd.Series
    :param sector_map: Dict mapping ticker → GICS sector
    :type sector_map: dict
    :param returns: Daily portfolio returns (for VaR/CVaR)
    :type returns: pd.Series or None
    :returns: Dict of diversification metrics
    :rtype: dict
    """
    if len(weights) == 0:
        return _empty_div_metrics()

    # HHI and Effective N
    hhi = (weights ** 2).sum()
    effective_n = 1.0 / hhi if hhi > 0 else 0

    # Sector analysis
    sectors = pd.Series({t: sector_map.get(t, 'Unknown') for t in weights.index})
    sector_weights = weights.groupby(sectors).sum()
    max_sector_weight = sector_weights.max()
    max_sector_name = sector_weights.idxmax()
    n_sectors = (sector_weights > 0.01).sum()

    metrics = {
        'n_holdings': (weights > 1e-8).sum(),
        'hhi': hhi,
        'effective_n': effective_n,
        'max_position_weight': weights.max(),
        'max_sector_weight': max_sector_weight,
        'max_sector_name': max_sector_name,
        'n_sectors': n_sectors,
    }

    # Risk metrics if returns provided
    if returns is not None and len(returns) > 20:
        metrics['var_95'] = compute_var(returns, 0.95)
        metrics['cvar_95'] = compute_cvar(returns, 0.95)
        metrics['var_99'] = compute_var(returns, 0.99)
        metrics['cvar_99'] = compute_cvar(returns, 0.99)

    return metrics


def compute_diversification_over_time(
    weights_history: dict,
    sector_map: dict,
) -> pd.DataFrame:
    """Compute diversification metrics at each rebalance date.

    :param weights_history: Dict mapping date → weight Series
    :type weights_history: dict
    :param sector_map: Sector mapping
    :type sector_map: dict
    :returns: DataFrame with diversification metrics over time
    :rtype: pd.DataFrame
    """
    records = []
    for date, weights in sorted(weights_history.items()):
        metrics = compute_diversification_metrics(weights, sector_map)
        metrics['date'] = date
        records.append(metrics)

    return pd.DataFrame(records).set_index('date') if records else pd.DataFrame()


def compute_sector_allocation(
    weights: pd.Series,
    sector_map: dict,
) -> pd.Series:
    """Compute portfolio weight allocated to each GICS sector.

    :param weights: Portfolio weights
    :type weights: pd.Series
    :param sector_map: Sector mapping
    :type sector_map: dict
    :returns: Series of sector weights, sorted descending
    :rtype: pd.Series
    """
    sectors = pd.Series({t: sector_map.get(t, 'Unknown') for t in weights.index})
    sector_alloc = weights.groupby(sectors).sum().sort_values(ascending=False)
    return sector_alloc


def _empty_div_metrics() -> dict:
    """Return empty diversification metrics."""
    return {
        'n_holdings': 0,
        'hhi': 0.0,
        'effective_n': 0.0,
        'max_position_weight': 0.0,
        'max_sector_weight': 0.0,
        'max_sector_name': 'N/A',
        'n_sectors': 0,
    }
