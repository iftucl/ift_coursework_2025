"""Tests for dashboard.lib.queries with the DB mocked.

We don't run real SQL. We patch lib.db.query to return controlled
DataFrames and verify each query function:
  - Calls the right SQL
  - Returns the data shaped correctly
  - Handles empty / null results
  - Validates inputs (e.g. factor_col whitelist)

Note: Streamlit's @st.cache_data caches results across tests. We call
each function via __wrapped__ to bypass the cache entirely.
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard"))

from lib import queries as q  # noqa: E402


def _call(fn, *args, **kwargs):
    """Call a Streamlit-cached function bypassing the cache."""
    underlying = getattr(fn, "__wrapped__", fn)
    return underlying(*args, **kwargs)


# ---------------------------------------------------------------------------
# Universe / metadata
# ---------------------------------------------------------------------------


class TestGetDatabaseStats:
    def test_returns_dict(self):
        mock_df = pd.DataFrame(
            [
                {
                    "scenarios": 23,
                    "stocks_used": 402,
                    "months": 62,
                    "start_date": date(2021, 3, 1),
                    "end_date": date(2026, 3, 31),
                }
            ]
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_database_stats)
        assert result["scenarios"] == 23
        assert result["stocks_used"] == 402

    def test_empty_returns_empty_dict(self):
        with patch.object(q, "query", return_value=pd.DataFrame()):
            result = _call(q.get_database_stats)
        assert result == {}


class TestGetScenarioList:
    def test_returns_list(self):
        mock_df = pd.DataFrame(
            {"scenario_id": ["baseline", "cost_low", "excl_quality"]}
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_scenario_list)
        assert result == ["baseline", "cost_low", "excl_quality"]


class TestGetSymbols:
    def test_returns_clean_strings(self):
        mock_df = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "security": "Apple Inc.",
                    "gics_sector": "Tech",
                    "gics_industry": "Hardware",
                    "country": "USA",
                },
                {
                    "symbol": "GOOG",
                    "security": "Alphabet",
                    "gics_sector": "Tech",
                    "gics_industry": "Software",
                    "country": "USA",
                },
            ]
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_symbols)
        assert "AAPL" in result["symbol"].tolist()
        assert "GOOG" in result["symbol"].tolist()


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_returns_series(self):
        mock_df = pd.DataFrame(
            [
                {
                    "scenario_id": "baseline",
                    "sharpe_ratio": 0.63,
                    "annualised_return": 0.10,
                }
            ]
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_summary, "baseline")
        assert isinstance(result, pd.Series)
        assert result["sharpe_ratio"] == 0.63

    def test_empty_returns_empty_series(self):
        with patch.object(q, "query", return_value=pd.DataFrame()):
            result = _call(q.get_summary, "missing")
        assert isinstance(result, pd.Series)
        assert result.empty


class TestGetReturns:
    def test_parses_dates(self):
        mock_df = pd.DataFrame(
            {
                "rebalance_date": ["2024-01-31", "2024-02-29"],
                "gross_return": [0.01, 0.02],
                "net_return": [0.008, 0.018],
                "long_return": [0.01, 0.02],
                "short_return": [0.0, 0.0],
                "benchmark_return": [0.005, 0.01],
                "excess_return": [0.003, 0.008],
                "cumulative_return": [0.01, 0.03],
                "turnover": [0.5, 0.6],
                "transaction_cost": [0.001, 0.001],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_returns, "baseline")
        assert pd.api.types.is_datetime64_any_dtype(result["rebalance_date"])

    def test_empty(self):
        with patch.object(q, "query", return_value=pd.DataFrame()):
            result = _call(q.get_returns, "missing")
        assert result.empty


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class TestGetRebalanceDates:
    def test_returns_list(self):
        mock_df = pd.DataFrame(
            {"rebalance_date": ["2024-01-31", "2024-02-29", "2024-03-31"]}
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_rebalance_dates)
        assert len(result) == 3
        assert isinstance(result[0], pd.Timestamp)


class TestGetHoldings:
    def test_passes_date_to_query(self):
        mock_df = pd.DataFrame()
        with patch.object(q, "query", return_value=mock_df) as mock_query:
            _call(q.get_holdings, pd.Timestamp("2024-01-31"))
        # query is called with (sql, params); check params has 'rd'
        args, _ = mock_query.call_args
        assert "rd" in args[1]


class TestGetSelectionStatus:
    def test_returns_dataframe(self):
        mock_df = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "sector": "Tech",
                    "composite_score": 1.5,
                    "percentile_rank": 0.92,
                    "status": "long_core",
                    "buffer_months_count": 0,
                    "entry_date": "2023-06-01",
                    "exit_reason": None,
                }
            ]
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_selection_status, pd.Timestamp("2024-01-31"))
        assert len(result) == 1


class TestGetPositionHistory:
    def test_parses_dates(self):
        mock_df = pd.DataFrame(
            {
                "rebalance_date": ["2024-01-31", "2024-02-29"],
                "sector": ["Tech", "Tech"],
                "direction": ["long", "long"],
                "final_weight": [0.05, 0.05],
                "target_weight": [0.05, 0.05],
                "risk_adj_score": [1.5, 1.5],
                "ewma_vol": [0.20, 0.20],
                "liquidity_capped": [False, False],
                "trade_action": ["trade", "hold"],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_position_history, "AAPL")
        assert pd.api.types.is_datetime64_any_dtype(result["rebalance_date"])


# ---------------------------------------------------------------------------
# Factor analysis
# ---------------------------------------------------------------------------


class TestGetICWeights:
    def test_parses_dates(self):
        mock_df = pd.DataFrame(
            {
                "rebalance_date": ["2024-01-31", "2024-02-29"],
                "factor_name": ["value", "value"],
                "ic_mean_36m": [0.005, 0.006],
                "ic_weight": [0.25, 0.30],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_ic_weights)
        assert pd.api.types.is_datetime64_any_dtype(result["rebalance_date"])


class TestGetCompositeDistribution:
    def test_returns_dataframe(self):
        mock_df = pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "composite_score": [1.5, -0.5, 0.2],
                "sector": ["Tech", "Energy", "Tech"],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_composite_distribution, pd.Timestamp("2024-01-31"))
        assert len(result) == 3


class TestGetZscoreBySector:
    def test_validates_factor_col(self):
        with pytest.raises(ValueError, match="Unknown factor column"):
            _call(q.get_zscore_by_sector, pd.Timestamp("2024-01-31"), "z_invalid")

    def test_accepts_valid_columns(self):
        mock_df = pd.DataFrame({"symbol": ["A"], "z": [1.0], "sector": ["Tech"]})
        for col in ["z_value", "z_quality", "z_momentum", "z_low_vol"]:
            with patch.object(q, "query", return_value=mock_df):
                result = _call(q.get_zscore_by_sector, pd.Timestamp("2024-01-31"), col)
            assert len(result) == 1


class TestGetFactorScores:
    def test_parses_dates(self):
        mock_df = pd.DataFrame(
            {
                "score_date": ["2024-01-31"],
                "z_value": [1.0],
                "z_quality": [0.5],
                "z_momentum": [0.2],
                "z_low_vol": [-0.1],
                "composite_score": [0.4],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_factor_scores, "AAPL")
        assert pd.api.types.is_datetime64_any_dtype(result["score_date"])


class TestGetFactorMetrics:
    def test_parses_dates(self):
        mock_df = pd.DataFrame(
            {
                "calc_date": ["2024-01-31"],
                "pb_ratio": [3.5],
                "asset_growth": [0.05],
                "roe": [0.18],
                "leverage": [0.4],
                "earnings_stability": [0.02],
                "momentum_6m": [0.10],
                "momentum_12m": [0.20],
                "volatility_3m": [0.18],
                "volatility_12m": [0.22],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_factor_metrics, "AAPL")
        assert pd.api.types.is_datetime64_any_dtype(result["calc_date"])


class TestGetFactorCorrelations:
    def test_returns_dataframe(self):
        mock_df = pd.DataFrame(
            {
                "z_value": [1.0, -1.0],
                "z_quality": [0.5, -0.5],
                "z_momentum": [0.2, -0.2],
                "z_low_vol": [-0.1, 0.1],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_factor_correlations)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Home page health metrics
# ---------------------------------------------------------------------------


class TestGetActiveFactorCount:
    def test_returns_int(self):
        mock_df = pd.DataFrame(
            {
                "factor_name": ["value", "quality", "momentum"],
                "avg_w": [0.25, 0.30, 0.20],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_active_factor_count)
        assert result == 3


class TestGetUniverseSizeLatest:
    def test_returns_count(self):
        mock_df = pd.DataFrame({"n": [100]})
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_universe_size_latest)
        assert result == 100

    def test_empty(self):
        with patch.object(q, "query", return_value=pd.DataFrame()):
            result = _call(q.get_universe_size_latest)
        assert result == 0


class TestGetLatestNetExposure:
    def test_computes_net_correctly(self):
        # short weights stored as positive; net = long - |short|
        mock_df = pd.DataFrame(
            {
                "direction": ["long", "short"],
                "total": [1.30, 0.30],
            }
        )
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_latest_net_exposure)
        assert result["long"] == 1.30
        assert result["short"] == 0.30
        assert abs(result["net"] - 1.00) < 1e-10

    def test_handles_missing_direction(self):
        mock_df = pd.DataFrame({"direction": ["long"], "total": [1.30]})
        with patch.object(q, "query", return_value=mock_df):
            result = _call(q.get_latest_net_exposure)
        assert result["long"] == 1.30
        assert result["short"] == 0.0
