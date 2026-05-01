"""Tests for risk-adjusted score calculation."""

import pandas as pd

from modules.portfolio.risk_adjusted import compute_risk_adjusted_scores

# ---------------------------------------------------------------------------
# compute_risk_adjusted_scores
# ---------------------------------------------------------------------------


class TestComputeRiskAdjustedScores:

    def test_long_formula(self):
        """Longs: risk_adj = composite / ewma_vol."""
        selected = pd.DataFrame(
            {
                "symbol": ["A"],
                "sector": ["Tech"],
                "direction": ["long"],
                "composite_score": [2.0],
                "percentile_rank": [0.95],
                "status": ["long_core"],
                "buffer_months_count": [0],
            }
        )
        ewma = pd.DataFrame({"symbol": ["A"], "ewma_vol": [0.20]})

        result = compute_risk_adjusted_scores(selected, ewma)
        # 2.0 / 0.20 = 10.0
        assert abs(result.iloc[0]["risk_adj_score"] - 10.0) < 1e-10

    def test_short_uses_absolute_value(self):
        """Shorts: risk_adj = |composite| / ewma_vol."""
        selected = pd.DataFrame(
            {
                "symbol": ["A"],
                "sector": ["Tech"],
                "direction": ["short"],
                "composite_score": [-2.0],
                "percentile_rank": [0.05],
                "status": ["short_core"],
                "buffer_months_count": [0],
            }
        )
        ewma = pd.DataFrame({"symbol": ["A"], "ewma_vol": [0.25]})

        result = compute_risk_adjusted_scores(selected, ewma)
        # |-2.0| / 0.25 = 8.0
        assert abs(result.iloc[0]["risk_adj_score"] - 8.0) < 1e-10

    def test_lower_vol_gets_higher_score(self):
        """Same composite score, lower vol stock gets higher risk-adjusted score."""
        selected = pd.DataFrame(
            {
                "symbol": ["A", "B"],
                "sector": ["Tech", "Tech"],
                "direction": ["long", "long"],
                "composite_score": [2.0, 2.0],
                "percentile_rank": [0.95, 0.92],
                "status": ["long_core", "long_core"],
                "buffer_months_count": [0, 0],
            }
        )
        ewma = pd.DataFrame({"symbol": ["A", "B"], "ewma_vol": [0.20, 0.55]})

        result = compute_risk_adjusted_scores(selected, ewma)
        a_score = result[result["symbol"] == "A"]["risk_adj_score"].iloc[0]
        b_score = result[result["symbol"] == "B"]["risk_adj_score"].iloc[0]
        assert a_score > b_score

    def test_missing_ewma_dropped(self):
        """Stocks without EWMA vol data are excluded from output."""
        selected = pd.DataFrame(
            {
                "symbol": ["A", "B"],
                "sector": ["Tech", "Tech"],
                "direction": ["long", "long"],
                "composite_score": [2.0, 1.5],
                "percentile_rank": [0.95, 0.92],
                "status": ["long_core", "long_core"],
                "buffer_months_count": [0, 0],
            }
        )
        # Only A has EWMA vol
        ewma = pd.DataFrame({"symbol": ["A"], "ewma_vol": [0.20]})

        result = compute_risk_adjusted_scores(selected, ewma)
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "A"

    def test_empty_inputs(self):
        """Empty selected stocks returns empty DataFrame."""
        selected = pd.DataFrame(
            columns=[
                "symbol",
                "sector",
                "direction",
                "composite_score",
                "percentile_rank",
                "status",
                "buffer_months_count",
            ]
        )
        ewma = pd.DataFrame(columns=["symbol", "ewma_vol"])

        result = compute_risk_adjusted_scores(selected, ewma)
        assert result.empty

    def test_zero_vol_dropped(self):
        """Stocks with zero EWMA vol are excluded from output."""
        selected = pd.DataFrame(
            {
                "symbol": ["A"],
                "sector": ["Tech"],
                "direction": ["long"],
                "composite_score": [2.0],
                "percentile_rank": [0.95],
                "status": ["long_core"],
                "buffer_months_count": [0],
            }
        )
        ewma = pd.DataFrame({"symbol": ["A"], "ewma_vol": [0.0]})

        result = compute_risk_adjusted_scores(selected, ewma)
        assert result.empty
