#!/usr/bin/env python3
"""
Utilities for reading actual pipeline output data and computing real statistics.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def read_factor_count() -> int:
    """Read actual factor count from latest Step 1 output."""
    analytics_dir = Path(__file__).parent.parent / "analytics"

    # Try processed location first, then portfolio location
    candidates = [
        analytics_dir / "processed" / "step1" / "factors_latest.csv",
        analytics_dir / "processed" / "step1" / "factors_latest.parquet",
        analytics_dir / "portfolio" / "factors_latest.csv",
        analytics_dir / "portfolio" / "factors_latest.parquet",
    ]

    for path in candidates:
        if path.exists():
            try:
                if path.suffix == ".parquet":
                    df = pd.read_parquet(path)
                else:
                    df = pd.read_csv(path)
                count = len(df)
                logger.debug(f"Read {count} factors from {path.name}")
                return count
            except Exception as e:
                logger.warning(f"Failed to read {path}: {e}")

    logger.warning("No Step 1 factors file found")
    return 0


def read_step2_counts() -> tuple:
    """
    Read actual counts from latest Step 2 outputs.

    Returns:
        (portfolio_count, selections_count)
    """
    analytics_dir = Path(__file__).parent.parent / "analytics"

    portfolio_count = 0
    selections_count = 0

    # Read portfolio count
    portfolio_paths = [
        analytics_dir / "processed" / "step2" / "portfolio_latest.csv",
        analytics_dir / "processed" / "step2" / "portfolio_latest.parquet",
        analytics_dir / "portfolio" / "portfolio_latest.csv",
    ]
    for path in portfolio_paths:
        if path.exists():
            try:
                if path.suffix == ".parquet":
                    df = pd.read_parquet(path)
                else:
                    df = pd.read_csv(path)
                portfolio_count = len(df)
                logger.debug(f"Read {portfolio_count} portfolio rows from {path.name}")
                break
            except Exception as e:
                logger.warning(f"Failed to read portfolio {path}: {e}")

    # Read selections count
    selections_paths = [
        analytics_dir / "processed" / "step2" / "selections_latest.csv",
        analytics_dir / "processed" / "step2" / "selections_latest.parquet",
        analytics_dir / "selections" / "selections_latest.csv",
    ]
    for path in selections_paths:
        if path.exists():
            try:
                if path.suffix == ".parquet":
                    df = pd.read_parquet(path)
                else:
                    df = pd.read_csv(path)
                selections_count = len(df)
                logger.debug(f"Read {selections_count} selections from {path.name}")
                break
            except Exception as e:
                logger.warning(f"Failed to read selections {path}: {e}")

    return portfolio_count, selections_count


def read_step3_signal_counts() -> tuple:
    """
    Read actual signal counts from latest Step 3 output.

    Returns:
        (total_signals, buy_count, sell_count, hold_count)
    """
    analytics_dir = Path(__file__).parent.parent / "analytics"

    signal_paths = [
        analytics_dir / "processed" / "step3" / "signals_latest.csv",
        analytics_dir / "processed" / "step3" / "signals_latest.parquet",
        analytics_dir / "signals" / "signals_latest.csv",
        analytics_dir / "signals" / "signals_latest.parquet",
    ]

    for path in signal_paths:
        if path.exists():
            try:
                if path.suffix == ".parquet":
                    df = pd.read_parquet(path)
                else:
                    df = pd.read_csv(path)

                total = len(df)
                buy = (
                    len(df[df.get("final_trade_signal", 0) == 1])
                    if "final_trade_signal" in df.columns
                    else 0
                )
                sell = (
                    len(df[df.get("final_trade_signal", 0) == -1])
                    if "final_trade_signal" in df.columns
                    else 0
                )
                hold = (
                    len(df[df.get("final_trade_signal", 0) == 0])
                    if "final_trade_signal" in df.columns
                    else 0
                )

                logger.debug(
                    f"Read {total} signals ({buy} BUY, {sell} SELL, {hold} HOLD) from {path.name}"
                )
                return total, buy, sell, hold
            except Exception as e:
                logger.warning(f"Failed to read signals {path}: {e}")

    logger.warning("No Step 3 signals file found")
    return 0, 0, 0, 0
