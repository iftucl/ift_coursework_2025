"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Portfolio weighting schemes
Project : CW2 - Value-Sentiment Investment Strategy

Implements three weighting schemes required by the task:
  1. Equal-weight: w = 1/N — DeMiguel et al. (2009) beats 14 optimisation models
  2. Score-weight: w = CompositeScore / Sum(CompositeScore)
  3. Inverse-volatility: w = (1/sigma) / Sum(1/sigma), 60-day trailing vol

Ref: Part A §A5
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_equal_weight(tickers: list) -> pd.Series:
    """Compute equal-weight portfolio allocation.

    w_i = 1/N for all N selected stocks.

    DeMiguel et al. (2009): 'Optimal versus naive diversification:
    How inefficient is the 1/N portfolio strategy?' — RFS.
    Outperforms 14 optimisation models out-of-sample.

    :param tickers: List of selected ticker symbols
    :type tickers: list
    :returns: Series of equal weights indexed by ticker
    :rtype: pd.Series
    """
    n = len(tickers)
    if n == 0:
        return pd.Series(dtype=float)
    weights = pd.Series(1.0 / n, index=tickers, name='weight')
    logger.info("Equal-weight: %d stocks at %.4f each", n, 1.0 / n)
    return weights


def compute_score_weight(tickers: list, scores: pd.Series) -> pd.Series:
    """Compute score-weighted portfolio allocation.

    w_i = CompositeScore_i / Sum(CompositeScore_j) for selected stocks.
    Tests whether the composite signal has proportional predictive power.

    :param tickers: List of selected ticker symbols
    :type tickers: list
    :param scores: Series of composite scores indexed by ticker
    :type scores: pd.Series
    :returns: Series of score-proportional weights
    :rtype: pd.Series
    """
    if len(tickers) == 0:
        return pd.Series(dtype=float)

    selected_scores = scores.reindex(tickers).fillna(0)

    # Shift scores to positive range for valid weighting
    min_score = selected_scores.min()
    if min_score <= 0:
        selected_scores = selected_scores - min_score + 1e-6

    total = selected_scores.sum()
    if total <= 0:
        return compute_equal_weight(tickers)

    weights = selected_scores / total
    weights.name = 'weight'
    logger.info(
        "Score-weight: %d stocks, max=%.4f, min=%.4f",
        len(weights), weights.max(), weights.min(),
    )
    return weights


def compute_inverse_volatility_weight(
    tickers: list,
    prices: pd.DataFrame,
    lookback_days: int = 60,
) -> pd.Series:
    """Compute inverse-volatility portfolio allocation.

    w_i = (1/sigma_i) / Sum(1/sigma_j)
    where sigma_i is the trailing 60-day annualised volatility.

    Maillard et al. (2010): 'The properties of equally weighted risk
    contribution portfolios' — JPM.

    :param tickers: List of selected ticker symbols
    :type tickers: list
    :param prices: Full price DataFrame (dates × tickers)
    :type prices: pd.DataFrame
    :param lookback_days: Trailing window for volatility estimation
    :type lookback_days: int
    :returns: Series of inverse-volatility weights
    :rtype: pd.Series
    """
    if len(tickers) == 0:
        return pd.Series(dtype=float)

    available = [t for t in tickers if t in prices.columns]
    if len(available) == 0:
        return compute_equal_weight(tickers)

    # Compute trailing daily returns (fill_method=None suppresses the
    # FutureWarning about the legacy 'pad' default)
    recent_prices = prices[available].tail(lookback_days + 1)
    returns = recent_prices.pct_change(fill_method=None).dropna(how='all')

    # Annualised volatility per stock
    vol = returns.std() * np.sqrt(252)

    # Replace zero/NaN vol with median to avoid division by zero
    median_vol = vol[vol > 0].median()
    if pd.isna(median_vol) or median_vol <= 0:
        return compute_equal_weight(tickers)
    vol = vol.replace(0, median_vol).fillna(median_vol)

    # Inverse volatility
    inv_vol = 1.0 / vol
    weights = inv_vol / inv_vol.sum()

    # Reindex to include any tickers without price data (assign zero)
    weights = weights.reindex(tickers, fill_value=0)
    if weights.sum() > 0:
        weights = weights / weights.sum()

    weights.name = 'weight'
    logger.info(
        "Inv-vol weight: %d stocks, max=%.4f, min=%.4f",
        len(weights), weights.max(), weights.min(),
    )
    return weights
