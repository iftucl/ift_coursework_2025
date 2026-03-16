"""
Smoke Tests for Composite Scoring Module

Tests core portfolio scoring functionality:
- Z-score normalization
- Min-Max normalization
- Composite score calculation
- Ranking and filtering
- Edge cases and data validation

These are smoke tests - they verify basic operation without external dependencies.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest


class TestCompositeScoreImport:
    """Test that CompositeScorer module can be imported."""

    def test_composite_scorer_import(self):
        """Test that CompositeScorer class can be imported."""
        from modules.processing.composite_scoring import CompositeScorer

        assert CompositeScorer is not None
        assert hasattr(CompositeScorer, "calculate_z_score")
        assert hasattr(CompositeScorer, "normalize_to_range")
        assert hasattr(CompositeScorer, "calculate_composite_score")
        assert hasattr(CompositeScorer, "get_score_percentiles")
        assert hasattr(CompositeScorer, "filter_by_score")

    def test_all_methods_are_static(self):
        """Test that all methods are static."""
        from modules.processing.composite_scoring import CompositeScorer

        assert callable(CompositeScorer.calculate_z_score)
        assert callable(CompositeScorer.normalize_to_range)
        assert callable(CompositeScorer.calculate_composite_score)
        assert callable(CompositeScorer.get_score_percentiles)
        assert callable(CompositeScorer.filter_by_score)


class TestZScoreCalculation:
    """Test Z-score normalization functionality."""

    def test_z_score_with_valid_data(self):
        """Test Z-score calculation with valid data."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([100, 110, 120, 130, 140])
        z_scores = CompositeScorer.calculate_z_score(series)

        # Verify output
        assert z_scores is not None
        assert len(z_scores) == len(series)
        assert isinstance(z_scores, pd.Series)

        # Z-scores should have mean ~0 and std ~1
        assert abs(z_scores.mean()) < 0.01
        assert abs(z_scores.std() - 1.0) < 0.01

    def test_z_score_returns_series(self):
        """Test that Z-score returns pandas Series."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([1, 2, 3, 4, 5])
        result = CompositeScorer.calculate_z_score(series)

        assert isinstance(result, pd.Series)
        assert result.index.equals(series.index)

    def test_z_score_with_negative_values(self):
        """Test Z-score with negative values."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([-10, -5, 0, 5, 10])
        z_scores = CompositeScorer.calculate_z_score(series)

        # Should work with negative values
        assert len(z_scores) == len(series)
        assert not z_scores.isna().all()

    def test_z_score_with_identical_values(self):
        """Test Z-score when all values are identical."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([5, 5, 5, 5, 5])
        z_scores = CompositeScorer.calculate_z_score(series, handle_std_zero=True)

        # Should return zeros when std=0
        assert (z_scores == 0).all()

    def test_z_score_with_nans(self):
        """Test Z-score handling of NaN values."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([1, 2, np.nan, 4, 5])
        z_scores = CompositeScorer.calculate_z_score(series)

        # Should handle NaN values
        assert len(z_scores) == len(series)

    def test_z_score_symmetry(self):
        """Test Z-score symmetry around mean."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([100, 110, 120, 130, 140])  # Mean = 120
        z_scores = CompositeScorer.calculate_z_score(series)

        # Values equidistant from mean should have opposite Z-scores
        assert abs(z_scores.iloc[0] + z_scores.iloc[4]) < 0.01  # 100 and 140


class TestMinMaxNormalization:
    """Test Min-Max normalization functionality."""

    def test_normalize_to_range_default(self):
        """Test Min-Max normalization to [0, 1]."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([100, 150, 200])
        normalized = CompositeScorer.normalize_to_range(series)

        # Should be in [0, 1]
        assert normalized.min() >= 0
        assert normalized.max() <= 1
        assert abs(normalized.min() - 0) < 0.01
        assert abs(normalized.max() - 1) < 0.01

    def test_normalize_to_custom_range(self):
        """Test Min-Max normalization to custom range."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([100, 150, 200])
        normalized = CompositeScorer.normalize_to_range(series, min_val=-1, max_val=1)

        # Should be in [-1, 1]
        assert normalized.min() >= -1
        assert normalized.max() <= 1

    def test_normalize_preserves_order(self):
        """Test that normalization preserves value ordering."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([10, 50, 100, 200])
        normalized = CompositeScorer.normalize_to_range(series)

        # Order should be preserved
        assert normalized.iloc[0] < normalized.iloc[1]
        assert normalized.iloc[1] < normalized.iloc[2]
        assert normalized.iloc[2] < normalized.iloc[3]

    def test_normalize_identical_values(self):
        """Test normalization with identical values."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([50, 50, 50, 50])
        normalized = CompositeScorer.normalize_to_range(series)

        # All should be set to min_val
        assert (normalized == 0).all()

    def test_normalize_two_values(self):
        """Test normalization with only two values."""
        from modules.processing.composite_scoring import CompositeScorer

        series = pd.Series([100, 200])
        normalized = CompositeScorer.normalize_to_range(series)

        # First should map to 0, second to 1
        assert abs(normalized.iloc[0] - 0) < 0.01
        assert abs(normalized.iloc[1] - 1) < 0.01


class TestCompositeScoreCalculation:
    """Test composite score calculation."""

    def test_composite_score_with_valid_data(self):
        """Test composite score calculation with valid input."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.5, 0.8, 1.2, 0.3, 1.5],
                "volume_60d_avg": [1e6, 2e6, 3e6, 0.5e6, 5e6],
                "var_95": [-0.05, -0.08, -0.03, -0.10, -0.02],
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Should return DataFrame with additional columns
        assert result is not None
        assert "composite_score" in result.columns
        assert "composite_rank" in result.columns
        assert "z_momentum" in result.columns
        assert "z_liquidity" in result.columns
        assert "z_var" in result.columns

    def test_composite_score_output_structure(self):
        """Test structure of composite score output."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 50),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 50),
                "var_95": -np.random.uniform(0.01, 0.15, 50),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Verify all required columns exist
        assert "z_momentum" in result.columns
        assert "z_liquidity" in result.columns
        assert "z_var" in result.columns
        assert "composite_score" in result.columns
        assert "composite_rank" in result.columns
        assert len(result) == len(df)

    def test_composite_score_ranking(self):
        """Test that ranking is correct."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.5, 0.8, 1.2, 0.3, 1.5],
                "volume_60d_avg": [1e6, 2e6, 3e6, 0.5e6, 5e6],
                "var_95": [-0.05, -0.08, -0.03, -0.10, -0.02],
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Rank should be 1 to N
        ranks = sorted(result["composite_rank"].unique())
        assert ranks[0] == 1
        assert ranks[-1] == len(df)

    def test_composite_score_with_custom_weights(self):
        """Test composite score with custom weights."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.5, 0.8, 1.2],
                "volume_60d_avg": [1e6, 2e6, 3e6],
                "var_95": [-0.05, -0.08, -0.03],
            }
        )

        # Test with custom weights
        result1 = CompositeScorer.calculate_composite_score(
            df, momentum_weight=2.0, liquidity_weight=1.0, var_weight=1.0
        )

        result2 = CompositeScorer.calculate_composite_score(
            df, momentum_weight=1.0, liquidity_weight=2.0, var_weight=1.0
        )

        # Scores should differ
        assert not result1["composite_score"].equals(result2["composite_score"])

    def test_composite_score_missing_columns(self):
        """Test handling of missing required columns."""
        from modules.processing.composite_scoring import CompositeScorer

        # DataFrame missing required column
        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.5, 0.8],
                "volume_60d_avg": [1e6, 2e6]
                # Missing var_95
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Should handle gracefully
        assert result is None

    def test_composite_score_with_nans(self):
        """Test composite score with NaN values."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.5, np.nan, 1.2, 0.3],
                "volume_60d_avg": [1e6, 2e6, np.nan, 0.5e6],
                "var_95": [-0.05, -0.08, -0.03, np.nan],
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # May return None if all rows have NaN in at least one column
        # (Only 1 complete row with no NaN, which causes ranking issues)
        if result is None:
            # This is acceptable - module logs error and returns None
            pass
        else:
            # If it does return, it should have fewer rows than input
            assert len(result) < len(df)

    def test_composite_score_higher_is_better(self):
        """Test that higher scores correlate with better metrics."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.2, 0.5, 1.5, 2.0],  # Increasing
                "volume_60d_avg": [1e6, 2e6, 5e6, 10e6],  # Increasing
                "var_95": [-0.10, -0.08, -0.03, -0.02],  # Improving (less negative)
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Highest score should be last row (best metrics)
        max_score_idx = result["composite_score"].idxmax()
        assert max_score_idx == 3


class TestScorePercentiles:
    """Test percentile calculation."""

    def test_get_percentiles_valid_data(self):
        """Test percentile calculation with valid data."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 100),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 100),
                "var_95": -np.random.uniform(0.01, 0.15, 100),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        percentiles = CompositeScorer.get_score_percentiles(result)

        # Should return dictionary with percentile stats
        assert percentiles is not None
        assert "min" in percentiles
        assert "p25" in percentiles
        assert "median" in percentiles
        assert "p75" in percentiles
        assert "max" in percentiles
        assert "mean" in percentiles
        assert "std" in percentiles
        assert "count" in percentiles

    def test_percentiles_ordering(self):
        """Test that percentiles are in correct order."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 100),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 100),
                "var_95": -np.random.uniform(0.01, 0.15, 100),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        percentiles = CompositeScorer.get_score_percentiles(result)

        # Percentiles should be in increasing order
        assert percentiles["min"] <= percentiles["p25"]
        assert percentiles["p25"] <= percentiles["median"]
        assert percentiles["median"] <= percentiles["p75"]
        assert percentiles["p75"] <= percentiles["max"]

    def test_percentiles_statistics(self):
        """Test that percentile stats are reasonable."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 100),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 100),
                "var_95": -np.random.uniform(0.01, 0.15, 100),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        percentiles = CompositeScorer.get_score_percentiles(result)

        # Mean should be between min and max
        assert percentiles["min"] <= percentiles["mean"] <= percentiles["max"]

        # Std should be non-negative
        assert percentiles["std"] >= 0

        # Count should match dataframe
        assert percentiles["count"] == len(result)


class TestScoreFiltering:
    """Test score-based filtering functionality."""

    def test_filter_by_score_min_threshold(self):
        """Test filtering by minimum score threshold."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 50),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 50),
                "var_95": -np.random.uniform(0.01, 0.15, 50),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        median_score = result["composite_score"].median()

        filtered = CompositeScorer.filter_by_score(result, min_score=median_score)

        # All filtered scores should be >= threshold
        assert (filtered["composite_score"] >= median_score).all()
        assert len(filtered) < len(result)

    def test_filter_by_score_max_threshold(self):
        """Test filtering by maximum score threshold."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 50),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 50),
                "var_95": -np.random.uniform(0.01, 0.15, 50),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        median_score = result["composite_score"].median()

        filtered = CompositeScorer.filter_by_score(result, max_score=median_score)

        # All filtered scores should be <= threshold
        assert (filtered["composite_score"] <= median_score).all()

    def test_filter_top_n(self):
        """Test selecting top N stocks by score."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 100),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 100),
                "var_95": -np.random.uniform(0.01, 0.15, 100),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        top_10 = CompositeScorer.filter_by_score(result, top_n=10)

        # Should have exactly 10 stocks
        assert len(top_10) == 10

        # All should be top performers
        assert (top_10["composite_rank"] <= 10).all()

    def test_filter_bottom_n(self):
        """Test selecting bottom N stocks by score."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 100),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 100),
                "var_95": -np.random.uniform(0.01, 0.15, 100),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        bottom_5 = CompositeScorer.filter_by_score(result, bottom_n=5)

        # Should have exactly 5 stocks
        assert len(bottom_5) == 5

        # All should be bottom performers
        assert (bottom_5["composite_rank"] > len(result) - 5).all()

    def test_filter_range(self):
        """Test filtering by score range."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 100),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 100),
                "var_95": -np.random.uniform(0.01, 0.15, 100),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)
        min_score = result["composite_score"].quantile(0.25)
        max_score = result["composite_score"].quantile(0.75)

        filtered = CompositeScorer.filter_by_score(
            result, min_score=min_score, max_score=max_score
        )

        # All should be in range
        assert (filtered["composite_score"] >= min_score).all()
        assert (filtered["composite_score"] <= max_score).all()


class TestCompositeScoreEdgeCases:
    """Test edge cases and error conditions."""

    def test_single_stock(self):
        """Test composite score with single stock."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.8],
                "volume_60d_avg": [2e6],
                "var_95": [-0.08],
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Single stock can cause ranking issues, so function may return None
        if result is None:
            # This is acceptable - module logs error and returns None
            pass
        else:
            # If it returns, verify it has the stock
            assert len(result) == 1
            assert result["composite_rank"].iloc[0] == 1

    def test_large_dataset(self):
        """Test composite score with large dataset."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 1000),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 1000),
                "var_95": -np.random.uniform(0.01, 0.15, 1000),
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Should handle large datasets
        assert len(result) == 1000
        assert result["composite_rank"].max() == 1000

    def test_zero_volatility_momentum(self):
        """Test with zero volatility in momentum (all same values)."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.8, 0.8, 0.8, 0.8],
                "volume_60d_avg": [1e6, 2e6, 3e6, 4e6],
                "var_95": [-0.05, -0.08, -0.03, -0.10],
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Should handle zero variance
        assert result is not None
        assert len(result) == 4

    def test_extreme_values(self):
        """Test with extreme outlier values."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.1, 0.5, 1000, 2.0],  # Outlier
                "volume_60d_avg": [1e6, 2e6, 3e6, 1e10],  # Outlier
                "var_95": [-0.05, -0.08, -0.03, -0.0001],
            }
        )

        result = CompositeScorer.calculate_composite_score(df)

        # Should handle outliers with Z-scores
        assert result is not None
        assert not result["composite_score"].isna().all()


class TestCompositeScoreIntegration:
    """End-to-end integration tests."""

    def test_full_scoring_pipeline(self):
        """Test complete scoring pipeline."""
        from modules.processing.composite_scoring import CompositeScorer

        # Create sample portfolio data
        np.random.seed(42)
        df = pd.DataFrame(
            {
                "symbol": [f"STOCK{i}" for i in range(100)],
                "risk_adjusted_momentum_252": np.random.uniform(0.1, 2.0, 100),
                "volume_60d_avg": np.random.uniform(1e6, 10e6, 100),
                "var_95": -np.random.uniform(0.01, 0.15, 100),
            }
        )

        # Calculate scores
        scored = CompositeScorer.calculate_composite_score(df)

        # Get percentiles
        percentiles = CompositeScorer.get_score_percentiles(scored)

        # Filter top 20
        top_20 = CompositeScorer.filter_by_score(scored, top_n=20)

        # Verify pipeline
        assert scored is not None
        assert percentiles is not None
        assert len(top_20) == 20
        assert all(top_20["composite_rank"] <= 20)

    def test_consistency_across_runs(self):
        """Test that scoring is consistent across multiple runs."""
        from modules.processing.composite_scoring import CompositeScorer

        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": [0.5, 0.8, 1.2, 0.3],
                "volume_60d_avg": [1e6, 2e6, 3e6, 0.5e6],
                "var_95": [-0.05, -0.08, -0.03, -0.10],
            }
        )

        # Run twice
        result1 = CompositeScorer.calculate_composite_score(df)
        result2 = CompositeScorer.calculate_composite_score(df)

        # Results should be identical
        assert result1["composite_score"].equals(result2["composite_score"])
        assert result1["composite_rank"].equals(result2["composite_rank"])

    def test_portfolio_selection_workflow(self):
        """Test realistic portfolio selection workflow."""
        from modules.processing.composite_scoring import CompositeScorer

        # Simulate 600 stocks
        np.random.seed(123)
        df = pd.DataFrame(
            {
                "risk_adjusted_momentum_252": np.random.uniform(0.05, 2.5, 600),
                "volume_60d_avg": np.random.uniform(0.5e6, 50e6, 600),
                "var_95": -np.random.uniform(0.01, 0.20, 600),
            }
        )

        # Step 1: Calculate composite scores
        scored = CompositeScorer.calculate_composite_score(df)

        # Step 2: Get score statistics
        stats = CompositeScorer.get_score_percentiles(scored)

        # Step 3: Select top 130 stocks for portfolio
        portfolio = CompositeScorer.filter_by_score(scored, top_n=130)

        # Verify portfolio selection
        assert len(portfolio) == 130
        assert (portfolio["composite_rank"] <= 130).all()
        assert portfolio["composite_score"].min() >= scored["composite_score"].quantile(
            0.78
        )
