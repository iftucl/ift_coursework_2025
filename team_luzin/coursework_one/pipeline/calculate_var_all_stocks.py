#!/usr/bin/env python3
"""
Step 1: Calculate risk metrics and factor data for the portfolio universe

Orchestrates:
- Load configuration from config/conf.yaml
- Connect to PostgreSQL database
- Retrieve the investable universe from systematic_equity.company_static
- Fetch 5 years of historical price data for each stock
- Calculate risk, momentum, and liquidity factors
- Normalize sector names
- Output timestamped factor data to analytics/portfolio/

Output:
- Timestamped file: analytics/portfolio/<YYYYMMDD_HHMMSS>/factors_<YYYYMMDD_HHMMSS>.csv
- Latest file: analytics/portfolio/factors_latest.csv
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import yaml

from modules.db.postgres_connector import PostgresConnector
from modules.extraction.price_extractor import PriceDataExtractor
from modules.processing.liquidity import LiquidityCalculator
from modules.processing.momentum import MomentumCalculator
from modules.processing.risk import RiskCalculator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def load_config():
    """Load configuration from config/conf.yaml"""
    config_path = Path(__file__).parent.parent / "config" / "conf.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def _normalize_ohlcv(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Normalize OHLCV columns to Open/High/Low/Close/Volume for downstream usage."""
    if df is None or df.empty:
        return None

    required = ["open", "high", "low", "close", "volume"]
    selected = {}

    for col in required:
        # Try exact match first, then case-insensitive
        if col in df.columns:
            selected[col] = df[col]
        else:
            col_lower = [c for c in df.columns if c.lower() == col]
            if col_lower:
                selected[col] = df[col_lower[0]]
            else:
                selected[col] = None

    if any(v is None for v in selected.values()):
        return None

    result = pd.DataFrame(selected)
    result.columns = ["Open", "High", "Low", "Close", "Volume"]
    return result


def normalize_sector_name(sector: Optional[str]) -> Optional[str]:
    """
    Normalize GICS sector names.

    Mapping:
        Technology → Information Technology
        Other → (keep as-is)
    """
    if not sector or sector.strip() == "":
        return None

    sector = sector.strip()

    # Map Technology to Information Technology
    if sector.lower() == "technology":
        return "Information Technology"

    # Keep everything else as-is
    return sector


def calculate_factors_for_stock(
    symbol: str,
    company_data: Dict[str, Any],
    df_prices: pd.DataFrame,
) -> Optional[Dict[str, Any]]:
    """
    Calculate all factors for a single stock.

    Args:
        symbol: Stock ticker symbol
        company_data: Company metadata (sector, etc.)
        df_prices: OHLCV price data (normalized)

    Returns:
        Dictionary of calculated factors, or None if calculation fails
    """
    try:
        if df_prices is None or len(df_prices) < 252:
            logger.debug(
                f"Insufficient price data for {symbol}: {len(df_prices) if df_prices is not None else 0} < 252"
            )
            return None

        # Extract basic info
        gics_sector = company_data.get("gics_sector") or company_data.get("sector")
        normalized_sector = normalize_sector_name(gics_sector)

        # Calculate momentum factors
        momentum_252 = MomentumCalculator.calculate_momentum_12m(df_prices)
        volatility_252 = RiskCalculator.calculate_volatility_12m(df_prices)

        # Risk-adjusted momentum
        ram_252 = None
        if momentum_252 is not None and volatility_252 is not None:
            ram_252 = MomentumCalculator.calculate_risk_adjusted_momentum(
                momentum_252, volatility_252
            )

        # Liquidity
        volume_60d_avg = LiquidityCalculator.calculate_avg_dollar_volume_60d(df_prices)

        # Risk metrics
        var_95 = RiskCalculator.calculate_var_95(df_prices, window=252)
        atr_pct = RiskCalculator.calculate_atr_pct(df_prices, period=14)

        # Calculate simple ATR_14 (average true range in dollars, not percentage)
        atr_14 = None
        if len(df_prices) >= 14:
            try:
                high = df_prices["High"].values
                low = df_prices["Low"].values
                close = df_prices["Close"].values

                # True Range
                high_low = high - low
                high_close = np.abs(high - np.roll(close, 1))
                low_close = np.abs(low - np.roll(close, 1))
                tr = np.maximum(np.maximum(high_low, high_close), low_close)

                # ATR_14 (EMA)
                atr_series = pd.Series(tr).ewm(span=14, adjust=False).mean()
                atr_14 = float(atr_series.iloc[-1])
            except Exception as e:
                logger.debug(f"Failed to calculate ATR_14 for {symbol}: {e}")
                atr_14 = None

        return {
            "symbol": symbol,
            "gics_sector": gics_sector,
            "normalized_sector": normalized_sector,
            "momentum_252": momentum_252,
            "volatility_252": volatility_252,
            "risk_adjusted_momentum_252": ram_252,
            "volume_60d_avg": volume_60d_avg,
            "var_95": var_95,
            "atr_pct": atr_pct,
            "atr_14": atr_14,
        }

    except Exception as e:
        logger.debug(f"Error calculating factors for {symbol}: {e}")
        return None


def calculate_var_all_stocks():
    """
    Step 1: Calculate risk metrics and factor data for the universe.

    Output:
    - Timestamped: analytics/portfolio/<YYYYMMDD_HHMMSS>/factors_<YYYYMMDD_HHMMSS>.csv
    - Latest: analytics/portfolio/factors_latest.csv
    """
    logger.info("Step 1/4: Calculate VAR_95 and ATR_14 metrics")
    logger.info("=" * 70)

    try:
        # Load config
        config = load_config()
        db = PostgresConnector(config["postgres"])
        logger.info("✓ Connected to PostgreSQL")

        # Get universe
        companies = db.get_company_universe()
        if not companies:
            logger.error("No companies in database")
            db.disconnect()
            return False

        logger.info(f"✓ Loaded {len(companies)} companies from universe")

        # Initialize price extractor
        extractor = PriceDataExtractor(years=5)
        logger.info("✓ Price extractor initialized (5 years)")

        # Calculate factors for all stocks
        factor_results = []
        failed_stocks = []

        for idx, company in enumerate(companies, 1):
            symbol = company.get("symbol")
            if not symbol:
                continue

            symbol = symbol.strip().lstrip("$").upper()

            try:
                # Fetch price data
                df_prices = extractor.fetch_price_data(symbol)
                normalized = (
                    _normalize_ohlcv(df_prices) if df_prices is not None else None
                )

                if normalized is None or normalized.empty:
                    logger.debug(f"No price data for {symbol}")
                    failed_stocks.append(symbol)
                    continue

                # Calculate factors
                factors = calculate_factors_for_stock(symbol, company, normalized)
                if factors is None:
                    failed_stocks.append(symbol)
                    continue

                factor_results.append(factors)

                if idx % 50 == 0:
                    logger.info(f"  Processed {idx}/{len(companies)} stocks")

            except Exception as e:
                logger.debug(f"Error processing {symbol}: {e}")
                failed_stocks.append(symbol)

        db.disconnect()

        # Create output DataFrame
        if not factor_results:
            logger.error("No factors calculated")
            return False

        df_factors = pd.DataFrame(factor_results)
        logger.info(
            f"✓ Calculated factors for {len(df_factors)} stocks ({len(failed_stocks)} failed)"
        )

        # Create timestamped output directory
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base = Path(__file__).parent.parent / "analytics" / "portfolio"
        output_dir = output_base / run_timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save timestamped file (both CSV and Parquet)
        output_file_csv = output_dir / f"factors_{run_timestamp}.csv"
        output_file_parquet = output_dir / f"factors_{run_timestamp}.parquet"
        df_factors.to_csv(output_file_csv, index=False)
        df_factors.to_parquet(output_file_parquet, index=False)
        logger.info(f"✓ Saved factors to {output_file_csv}")

        # Save latest files (both CSV and Parquet)
        latest_file_csv = output_base / "factors_latest.csv"
        latest_file_parquet = output_base / "factors_latest.parquet"
        df_factors.to_csv(latest_file_csv, index=False)
        df_factors.to_parquet(latest_file_parquet, index=False)
        logger.info(f"✓ Updated latest factors file: {latest_file_csv}")

        # Summary
        logger.info(f"✓ Output: {len(df_factors)} rows")
        logger.info(f"✓ Columns: {', '.join(df_factors.columns.tolist())}")
        logger.info("✓ Step 1 complete")

        return True

    except Exception as e:
        logger.error(f"Step 1 failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = calculate_var_all_stocks()
    sys.exit(0 if success else 1)
