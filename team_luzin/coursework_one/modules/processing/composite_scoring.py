"""
Composite Portfolio Scoring System

Implements Z-score normalization and composite scoring that combines:
- Risk-Adjusted Momentum (RAM)
- Liquidity metrics
- Value-at-Risk (VaR)

Final Score = Z(momentum) + Z(liquidity) - Z(VaR)

This creates a balanced scoring system that:
1. Rewards momentum-based returns (positive weight)
2. Rewards liquidity for tradability (positive weight)
3. Penalizes tail risk (negative weight on VaR)
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class CompositeScorer:
    """Calculate composite scores with Z-score normalization"""

    @staticmethod
    def calculate_z_score(series: pd.Series, handle_std_zero: bool = True) -> pd.Series:
        """
        Calculate Z-scores for a pandas Series.

        Formula: Z(x) = (x - mean(x)) / std(x)

        Args:
            series: pd.Series of values to standardize
            handle_std_zero: If True, return zeros when std=0 (perfect uniformity)

        Returns:
            pd.Series with Z-scores

        Example:
            series = [100, 110, 120, 130]  # mean=115, std=12.5
            Z-scores = [-1.2, -0.4, 0.4, 1.2]

        Why Z-scores matter:
            - Converts different units to same scale
            - Allows combining momentum, liquidity, and VaR
            - Negative Z: below average
            - Positive Z: above average
            - |Z| = 1: one standard deviation from mean
        """
        try:
            mean = series.mean()
            std = series.std()

            # Handle case where all values are identical
            if std == 0:
                if handle_std_zero:
                    logger.warning(
                        "Zero standard deviation - all values identical. Returning zeros."
                    )
                    return pd.Series(0.0, index=series.index)
                else:
                    return pd.Series(np.inf, index=series.index)

            z_scores = (series - mean) / std
            return z_scores

        except Exception as e:
            logger.error(f"Error calculating Z-scores: {e}")
            return pd.Series(np.nan, index=series.index)

    @staticmethod
    def normalize_to_range(
        series: pd.Series, min_val: float = 0, max_val: float = 1
    ) -> pd.Series:
        """
        Min-Max normalization to a specific range.

        Formula: x_norm = (x - min(x)) / (max(x) - min(x)) × (max_val - min_val) + min_val

        Args:
            series: pd.Series to normalize
            min_val: Desired minimum value (default 0)
            max_val: Desired maximum value (default 1)

        Returns:
            Normalized pd.Series

        Use case:
            - Convert VaR to positive range [0, 1]
            - Compare with other metrics on same scale
        """
        try:
            series_min = series.min()
            series_max = series.max()

            if series_min == series_max:
                logger.warning(f"Min and max are identical - returning {min_val}")
                return pd.Series(min_val, index=series.index)

            normalized = (series - series_min) / (series_max - series_min) * (
                max_val - min_val
            ) + min_val
            return normalized

        except Exception as e:
            logger.error(f"Error in normalization: {e}")
            return pd.Series(np.nan, index=series.index)

    @staticmethod
    def calculate_composite_score(
        df: pd.DataFrame,
        momentum_col: str = "risk_adjusted_momentum_252",
        liquidity_col: str = "volume_60d_avg",
        var_col: str = "var_95",
        momentum_weight: float = 1.0,
        liquidity_weight: float = 1.0,
        var_weight: float = 1.0,
    ) -> pd.DataFrame:
        """
        Calculate composite portfolio score using Z-score normalization.

        Formula: score = w_m × Z(momentum) + w_l × Z(liquidity) - w_v × Z(|VaR|)

        Args:
            df: DataFrame with momentum, liquidity, and VaR columns
            momentum_col: Name of momentum column
            liquidity_col: Name of liquidity (volume) column
            var_col: Name of VaR column
            momentum_weight: Weight for momentum in final score (default 1.0)
            liquidity_weight: Weight for liquidity in final score (default 1.0)
            var_weight: Weight for VaR penalty in final score (default 1.0)

        Returns:
            DataFrame with added columns:
            - z_momentum: Z-scores for momentum
            - z_liquidity: Z-scores for liquidity
            - z_var: Z-scores for VaR
            - composite_score: Final weighted score
            - composite_rank: Portfolio rank (1 = best)

        Example:
            Input df with 130 stocks:
            - risk_adjusted_momentum_252: 0.2 to 1.5
            - volume_60d_avg: 1M to 100M
            - var_95: -0.02 to -0.10

            Output:
            - composite_score: -5 to +8 (higher is better)
            - composite_rank: 1 to 130 (1 is best)

        Interpretation:
            - Score > 2: Excellent (high momentum, high liquidity, low risk)
            - Score 0 to 2: Good (above average on most metrics)
            - Score -2 to 0: Fair (mixed performance)
            - Score < -2: Poor (low momentum or high risk)
        """
        try:
            result_df = df.copy()

            # Validate required columns exist
            required_cols = [momentum_col, liquidity_col, var_col]
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.error(f"Missing columns: {missing_cols}")
                return None

            # Remove rows with NaN in key columns
            valid_rows = result_df[required_cols].notna().all(axis=1)
            if (~valid_rows).sum() > 0:
                logger.warning(
                    f"Removing {(~valid_rows).sum()} rows with NaN in key columns"
                )
                result_df = result_df[valid_rows].copy()

            # Calculate Z-scores for each component
            z_momentum = CompositeScorer.calculate_z_score(result_df[momentum_col])
            z_liquidity = CompositeScorer.calculate_z_score(result_df[liquidity_col])

            # VaR is negative (loss), so use absolute value for Z-score
            # Higher |VaR| is worse, so we subtract it
            z_var = CompositeScorer.calculate_z_score(result_df[var_col].abs())

            # Add component Z-scores to result
            result_df["z_momentum"] = z_momentum
            result_df["z_liquidity"] = z_liquidity
            result_df["z_var"] = z_var

            # Calculate composite score
            # score = Z(momentum) + Z(liquidity) - Z(|VaR|)
            result_df["composite_score"] = (
                momentum_weight * z_momentum
                + liquidity_weight * z_liquidity
                - var_weight * z_var
            )

            # Rank by composite score (1 = highest score = best)
            result_df["composite_rank"] = (
                result_df["composite_score"]
                .rank(ascending=False, method="min")
                .astype(int)
            )

            logger.info(f"Calculated composite scores for {len(result_df)} stocks")
            logger.info(
                f"Score range: {result_df['composite_score'].min():.2f} to {result_df['composite_score'].max():.2f}"
            )
            logger.info(
                f"Mean score: {result_df['composite_score'].mean():.2f}, Std: {result_df['composite_score'].std():.2f}"
            )

            return result_df

        except Exception as e:
            logger.error(f"Error calculating composite score: {e}")
            return None

    @staticmethod
    def get_score_percentiles(
        df: pd.DataFrame, score_col: str = "composite_score"
    ) -> Dict[str, float]:
        """
        Get percentile information for composite scores.

        Args:
            df: DataFrame with composite scores
            score_col: Name of score column

        Returns:
            Dictionary with percentiles and statistics
        """
        try:
            scores = df[score_col].dropna()

            return {
                "min": scores.min(),
                "p25": scores.quantile(0.25),
                "median": scores.quantile(0.50),
                "p75": scores.quantile(0.75),
                "max": scores.max(),
                "mean": scores.mean(),
                "std": scores.std(),
                "count": len(scores),
            }

        except Exception as e:
            logger.error(f"Error calculating percentiles: {e}")
            return None

    @staticmethod
    def filter_by_score(
        df: pd.DataFrame,
        score_col: str = "composite_score",
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        top_n: Optional[int] = None,
        bottom_n: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Filter DataFrame by composite score thresholds.

        Args:
            df: DataFrame with composite scores
            score_col: Name of score column
            min_score: Minimum score threshold
            max_score: Maximum score threshold
            top_n: Select top N stocks by score
            bottom_n: Select bottom N stocks by score

        Returns:
            Filtered DataFrame
        """
        try:
            result = df.copy()

            # Apply score thresholds
            if min_score is not None:
                result = result[result[score_col] >= min_score]

            if max_score is not None:
                result = result[result[score_col] <= max_score]

            # Select top/bottom N
            if top_n is not None:
                result = result.nlargest(top_n, score_col)

            if bottom_n is not None:
                result = result.nsmallest(bottom_n, score_col)

            logger.info(f"Filtered to {len(result)} stocks from {len(df)}")
            return result

        except Exception as e:
            logger.error(f"Error filtering by score: {e}")
            return None
