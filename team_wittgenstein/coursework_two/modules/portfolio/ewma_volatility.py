"""Step 2: EWMA volatility calculation.

Computes annualised Exponentially Weighted Moving Average volatility for
each selected stock using the RiskMetrics approach (lambda = 0.94).

Formula:
    sigma2_t = lambda * sigma2_{t-1} + (1 - lambda) * r2_{t-1}
    ewma_vol = sqrt(sigma2_t * 252)
"""

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from modules.db.db_connection import PostgresConnection

logger = logging.getLogger(__name__)
SCHEMA = "team_wittgenstein"


@dataclass(frozen=True)
class EWMAConfig:
    """Parameters for EWMA volatility calculation."""

    ewma_lambda: float = 0.94
    lookback_days: int = 252
    seed_days: int = 20


def fetch_daily_prices(
    db: PostgresConnection,
    symbols: list,
    rebalance_date: date,
    lookback_days: int,
) -> pd.DataFrame:
    """Fetch daily adjusted close prices for the given symbols."""
    start_date = rebalance_date - relativedelta(days=lookback_days + 60)
    query = """
        SELECT symbol, trade_date, adjusted_close
        FROM team_wittgenstein.price_data
        WHERE symbol IN :symbols
          AND trade_date < :rebalance_date
          AND trade_date >= :start_date
          AND adjusted_close IS NOT NULL
        ORDER BY symbol, trade_date
    """
    return db.read_query(
        query,
        {
            "symbols": tuple(symbols),
            "rebalance_date": rebalance_date,
            "start_date": start_date,
        },
    )


def compute_ewma_vol(
    prices: pd.DataFrame,
    ewma_lambda: float = 0.94,
    seed_days: int = 20,
) -> pd.DataFrame:
    """Compute annualised EWMA volatility for each symbol.

    Args:
        prices: DataFrame with symbol, trade_date, adjusted_close.
        ewma_lambda: Decay factor (default 0.94 per RiskMetrics).
        seed_days: Number of initial returns to seed the variance estimate.

    Returns:
        DataFrame with symbol and ewma_vol columns.
    """
    results = []

    for symbol, group in prices.groupby("symbol"):
        group = group.sort_values("trade_date")
        closes = group["adjusted_close"].values

        if len(closes) < seed_days + 1:
            logger.debug(
                "%s: insufficient data (%d prices, need %d)",
                symbol,
                len(closes),
                seed_days + 1,
            )
            continue

        # Daily log returns
        log_returns = np.log(closes[1:] / closes[:-1])

        if len(log_returns) < seed_days:
            continue

        # Seed variance with sample variance of first seed_days returns
        variance = np.var(log_returns[:seed_days], ddof=1)

        # Recursive EWMA
        for r in log_returns[seed_days:]:
            variance = ewma_lambda * variance + (1 - ewma_lambda) * r * r

        # Annualise
        ewma_vol = np.sqrt(variance * 252)

        results.append({"symbol": symbol, "ewma_vol": ewma_vol})

    if not results:
        return pd.DataFrame(columns=["symbol", "ewma_vol"])

    return pd.DataFrame(results)


def run_ewma_volatility(
    db: PostgresConnection,
    symbols: list,
    rebalance_date: date,
    config: EWMAConfig,
) -> pd.DataFrame:
    """Compute EWMA volatility for a list of selected stocks.

    Returns DataFrame with symbol and ewma_vol.
    """
    if not symbols:
        return pd.DataFrame(columns=["symbol", "ewma_vol"])

    prices = fetch_daily_prices(db, symbols, rebalance_date, config.lookback_days)
    if prices.empty:
        logger.warning("No price data for EWMA computation (%s)", rebalance_date)
        return pd.DataFrame(columns=["symbol", "ewma_vol"])

    result = compute_ewma_vol(prices, config.ewma_lambda, config.seed_days)

    logger.info(
        "EWMA vol computed for %d/%d stocks (%s)",
        len(result),
        len(symbols),
        rebalance_date,
    )
    return result
