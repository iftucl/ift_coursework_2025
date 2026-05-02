#!/usr/bin/env python3
"""
Step 2: Sector-relative portfolio selection

Orchestrates:
- Load factor data from Step 1 output
- Group stocks by normalized_sector
- Compute z-scores within each sector
- Apply weighted scoring within each sector
- Select top 20% of stocks within each sector
- Output selected portfolio

Strategy:
- Sector-neutral: Each sector contributes top 20% of its stocks
- Score = 0.6 * z_momentum + 0.2 * z_liquidity - 0.2 * z_risk
- Final portfolio size = sum of top-20% selections across all sectors
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def load_factors():
    """Load factor data from Step 1 output (latest)."""
    factors_file = (
        Path(__file__).parent.parent / "analytics" / "portfolio" / "factors_latest.csv"
    )

    if not factors_file.exists():
        logger.error(f"Factors file not found: {factors_file}")
        return None

    try:
        df = pd.read_csv(factors_file)
        logger.info(f"✓ Loaded {len(df)} stocks from Step 1 factors")
        return df
    except Exception as e:
        logger.error(f"Failed to load factors: {e}")
        return None


def compute_sector_zscores(df: pd.DataFrame, sector_col: str) -> pd.DataFrame:
    """
    Compute z-scores within each sector for momentum, liquidity, and risk.

    Args:
        df: DataFrame with factor columns
        sector_col: Column name for sector grouping (normalized_sector)

    Returns:
        DataFrame with z-score columns added
    """
    required_factors = ["risk_adjusted_momentum_252", "volume_60d_avg", "var_95"]

    # Drop rows with missing required factors
    df_clean = df.dropna(subset=required_factors)
    logger.info(f"✓ After dropping missing factors: {len(df_clean)} stocks")

    if len(df_clean) == 0:
        logger.error("No stocks with complete factor data")
        return None

    # Compute z-scores within each sector
    df_scores = df_clean.copy()

    # Group by sector
    for sector in df_scores[sector_col].unique():
        sector_mask = df_scores[sector_col] == sector
        sector_data = df_scores[sector_mask]

        # Skip if sector has < 2 stocks (can't compute z-scores)
        if len(sector_data) < 2:
            logger.debug(
                f"Sector '{sector}': {len(sector_data)} stock(s), skipping z-scores"
            )
            continue

        # Z-score = (value - mean) / std
        # Momentum z-score
        momentum_mean = sector_data["risk_adjusted_momentum_252"].mean()
        momentum_std = sector_data["risk_adjusted_momentum_252"].std()
        if momentum_std > 0:
            df_scores.loc[sector_mask, "z_momentum"] = (
                sector_data["risk_adjusted_momentum_252"] - momentum_mean
            ) / momentum_std
        else:
            df_scores.loc[sector_mask, "z_momentum"] = 0

        # Liquidity z-score
        liquidity_mean = sector_data["volume_60d_avg"].mean()
        liquidity_std = sector_data["volume_60d_avg"].std()
        if liquidity_std > 0:
            df_scores.loc[sector_mask, "z_liquidity"] = (
                sector_data["volume_60d_avg"] - liquidity_mean
            ) / liquidity_std
        else:
            df_scores.loc[sector_mask, "z_liquidity"] = 0

        # Risk z-score (VAR_95)
        # NOTE: var_95 is negative (e.g., -0.035 = 3.5% loss at 95% confidence)
        # More negative var_95 = higher risk
        # We negate var_95 so that higher risk values are positive (then penalized correctly)
        neg_var_95 = -sector_data["var_95"]
        risk_mean = neg_var_95.mean()
        risk_std = neg_var_95.std()
        if risk_std > 0:
            df_scores.loc[sector_mask, "z_risk"] = (neg_var_95 - risk_mean) / risk_std
        else:
            df_scores.loc[sector_mask, "z_risk"] = 0

    logger.info("✓ Computed sector-relative z-scores")
    return df_scores


def compute_composite_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute weighted composite score.

    Formula: score = 0.6 * z_momentum + 0.2 * z_liquidity - 0.2 * z_risk

    Args:
        df: DataFrame with z-score columns

    Returns:
        DataFrame with score column added
    """
    df["score"] = 0.6 * df["z_momentum"] + 0.2 * df["z_liquidity"] - 0.2 * df["z_risk"]

    logger.info(f"✓ Computed composite scores for {len(df)} stocks")
    return df


def select_top_20_percent_per_sector(df: pd.DataFrame, sector_col: str) -> pd.DataFrame:
    """
    Select top 20% of stocks within each sector by score.

    Args:
        df: DataFrame with score column
        sector_col: Column name for sector

    Returns:
        DataFrame containing only selected stocks
    """
    selected = []

    for sector in df[sector_col].unique():
        sector_data = df[df[sector_col] == sector].copy()
        n_sector = len(sector_data)
        n_select = max(1, int(np.ceil(n_sector * 0.20)))  # Top 20%, min 1

        # Rank by score (descending)
        sector_data["sector_rank"] = sector_data["score"].rank(
            method="first", ascending=False
        )

        # Select top N
        top_n = sector_data[sector_data["sector_rank"] <= n_select]
        selected.append(top_n)

        logger.info(
            f"  Sector '{sector}': {n_sector} stocks → select {n_select} (top 20%)"
        )

    df_selected = pd.concat(selected, ignore_index=True)
    logger.info(f"✓ Selected {len(df_selected)} stocks total across all sectors")

    return df_selected


def calculate_composite_portfolio():
    """
    Step 2: Sector-relative portfolio selection.

    Selects top 20% of stocks within each sector based on composite scoring.
    """
    logger.info("Step 2/4: Select portfolio (sector-relative strategy)")
    logger.info("=" * 70)

    try:
        # Load factors from Step 1
        df_factors = load_factors()
        if df_factors is None or df_factors.empty:
            logger.error("No factor data available from Step 1")
            return False

        # Compute sector-relative z-scores
        df_scores = compute_sector_zscores(df_factors, sector_col="normalized_sector")
        if df_scores is None or df_scores.empty:
            logger.error("Failed to compute sector z-scores")
            return False

        # Compute composite score
        df_scores = compute_composite_score(df_scores)

        # Select top 20% per sector
        df_portfolio = select_top_20_percent_per_sector(
            df_scores, sector_col="normalized_sector"
        )

        if df_portfolio is None or df_portfolio.empty:
            logger.error("No stocks selected")
            return False

        # Preserve key columns and ordering
        output_columns = [
            "symbol",
            "gics_sector",
            "normalized_sector",
            "momentum_252",
            "volatility_252",
            "risk_adjusted_momentum_252",
            "volume_60d_avg",
            "var_95",
            "atr_pct",
            "atr_14",
            "z_momentum",
            "z_liquidity",
            "z_risk",
            "score",
            "sector_rank",
        ]

        # Include only columns that exist
        output_columns = [col for col in output_columns if col in df_portfolio.columns]
        df_output = df_portfolio[output_columns].copy()

        # Sort by score descending, then sector, then symbol
        df_output = df_output.sort_values(
            ["score", "normalized_sector", "symbol"], ascending=[False, True, True]
        ).reset_index(drop=True)

        # Create timestamped output directory
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base = Path(__file__).parent.parent / "analytics" / "portfolio"
        output_dir = output_base / run_timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save portfolio output (full detailed columns)
        output_file = output_dir / f"portfolio_{run_timestamp}.csv"
        df_output.to_csv(output_file, index=False)
        logger.info(f"✓ Saved portfolio to {output_file}")

        # Save latest portfolio file
        latest_file = output_base / "portfolio_latest.csv"
        df_output.to_csv(latest_file, index=False)
        logger.info(f"✓ Updated latest portfolio file: {latest_file}")

        # Create selections output (reduced compact columns for downstream)
        selections_columns = [
            "symbol",
            "gics_sector",
            "normalized_sector",
            "score",
            "sector_rank",
        ]
        selections_columns = [
            col for col in selections_columns if col in df_output.columns
        ]
        df_selections = df_output[selections_columns].copy()

        # Save selections output (same data, separate directory for downstream steps)
        selections_base = Path(__file__).parent.parent / "analytics" / "selections"
        selections_dir = selections_base / run_timestamp
        selections_dir.mkdir(parents=True, exist_ok=True)

        # Save timestamped selections file
        selections_file = selections_dir / f"selections_{run_timestamp}.csv"
        df_selections.to_csv(selections_file, index=False)
        logger.info(f"✓ Saved selections to {selections_file}")

        # Save latest selections file
        latest_selections_file = selections_base / "selections_latest.csv"
        df_selections.to_csv(latest_selections_file, index=False)
        logger.info(f"✓ Updated latest selections file: {latest_selections_file}")

        # Summary by sector
        logger.info("✓ Portfolio summary by sector:")
        for sector in sorted(df_output["normalized_sector"].unique()):
            count = len(df_output[df_output["normalized_sector"] == sector])
            logger.info(f"  {sector}: {count} stocks")

        logger.info("✓ Total portfolio size: {len(df_output)} stocks")
        logger.info("✓ Step 2 complete")

        return True

    except Exception as e:
        logger.error(f"Step 2 failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = calculate_composite_portfolio()
    sys.exit(0 if success else 1)
