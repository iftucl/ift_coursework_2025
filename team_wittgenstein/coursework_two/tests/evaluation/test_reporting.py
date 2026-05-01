"""Tests for Step 11 reporting module.

Mocks the DB so each chart/table function is exercised without a live
connection. The tests verify each function writes the expected output
file. Visual quality is not checked - just that PNG/CSV files are
produced from valid input data.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from modules.evaluation.reporting import (
    export_cost_table,
    export_factor_exclusion_table,
    export_sensitivity_table,
    export_summary_table,
    plot_cost_sensitivity,
    plot_drawdown,
    plot_equity_curve,
    plot_factor_exclusion,
    plot_ic_weights,
    plot_long_short_contribution,
    plot_monthly_excess,
    plot_monthly_turnover,
    plot_parameter_sensitivity,
    plot_rolling_sharpe,
    run_reporting,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def returns_df():
    """24 months of synthetic backtest_returns rows."""
    dates = pd.date_range("2022-01-31", periods=24, freq="ME")
    return pd.DataFrame(
        {
            "rebalance_date": dates,
            "gross_return": [0.012] * 24,
            "net_return": [0.010, -0.005] * 12,
            "long_return": [0.008] * 24,
            "short_return": [0.002, -0.001] * 12,
            "benchmark_return": [0.007, 0.003] * 12,
            "excess_return": [0.003, -0.008] * 12,
            "cumulative_return": [0.01 * (i + 1) for i in range(24)],
            "turnover": [0.20, 0.15] * 12,
            "transaction_cost": [0.002] * 24,
        }
    )


@pytest.fixture
def summary_df():
    """One row per scenario type covering all the patterns the tests need."""
    rows = [
        (
            "baseline",
            0.10,
            0.50,
            0.16,
            -0.20,
            0.63,
            1.05,
            0.50,
            0.30,
            0.03,
            0.07,
            0.45,
            0.13,
            0.84,
            0.13,
            0.09,
        ),
        (
            "cost_frictionless",
            0.13,
            0.65,
            0.16,
            -0.18,
            0.83,
            1.40,
            0.70,
            0.50,
            0.06,
            0.07,
            0.45,
            0.13,
            0.84,
            0.13,
            0.09,
        ),
        (
            "cost_low",
            0.12,
            0.60,
            0.16,
            -0.19,
            0.74,
            1.25,
            0.60,
            0.40,
            0.05,
            0.07,
            0.45,
            0.13,
            0.84,
            0.13,
            0.09,
        ),
        (
            "cost_high",
            0.07,
            0.30,
            0.16,
            -0.25,
            0.45,
            0.70,
            0.30,
            -0.01,
            -0.001,
            0.07,
            0.45,
            0.13,
            0.84,
            0.13,
            0.09,
        ),
        (
            "excl_value",
            0.10,
            0.50,
            0.15,
            -0.15,
            0.66,
            1.20,
            0.65,
            0.30,
            0.03,
            0.07,
            0.45,
            0.13,
            0.84,
            0.15,
            0.09,
        ),
        (
            "excl_quality",
            0.08,
            0.40,
            0.16,
            -0.20,
            0.51,
            0.85,
            0.40,
            0.10,
            0.01,
            0.07,
            0.45,
            0.13,
            0.84,
            0.15,
            0.09,
        ),
        (
            "excl_momentum",
            0.10,
            0.50,
            0.15,
            -0.18,
            0.66,
            1.10,
            0.55,
            0.30,
            0.03,
            0.07,
            0.45,
            0.13,
            0.84,
            0.15,
            0.09,
        ),
        (
            "excl_low_vol",
            0.10,
            0.50,
            0.16,
            -0.22,
            0.63,
            1.05,
            0.45,
            0.30,
            0.03,
            0.07,
            0.45,
            0.13,
            0.84,
            0.15,
            0.09,
        ),
        (
            "sens_sel_0.05",
            0.09,
            0.45,
            0.17,
            -0.25,
            0.54,
            0.90,
            0.40,
            0.20,
            0.02,
            0.07,
            0.45,
            0.13,
            0.84,
            0.13,
            0.09,
        ),
        (
            "sens_ic_24",
            0.09,
            0.45,
            0.15,
            -0.18,
            0.60,
            1.00,
            0.50,
            0.30,
            0.02,
            0.07,
            0.45,
            0.13,
            0.84,
            0.13,
            0.09,
        ),
    ]
    cols = [
        "scenario_id",
        "annualised_return",
        "cumulative_return",
        "annualised_volatility",
        "max_drawdown",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "information_ratio",
        "alpha",
        "benchmark_return_ann",
        "benchmark_return_cum",
        "tracking_error",
        "downside_deviation",
        "long_contribution",
        "short_contribution",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["avg_monthly_turnover"] = 0.18
    return df


@pytest.fixture
def ic_weights_df():
    """24 months x 4 factors."""
    dates = pd.date_range("2022-01-31", periods=24, freq="ME")
    rows = []
    for d in dates:
        for factor in ["value", "quality", "momentum", "low_vol"]:
            rows.append((d, factor, 0.005, 0.25))
    return pd.DataFrame(
        rows, columns=["rebalance_date", "factor_name", "ic_mean_36m", "ic_weight"]
    )


@pytest.fixture
def mock_db_full(returns_df, summary_df, ic_weights_df):
    """Mock DB that returns appropriate data based on the query."""
    db = MagicMock()

    def read_query_side_effect(sql, params=None):
        sql_lower = sql.lower()
        if "ic_weights" in sql_lower:
            return ic_weights_df.copy()
        if "backtest_summary" in sql_lower:
            if params and "pat" in params:
                pat = params["pat"].replace("%", "")
                return summary_df[summary_df["scenario_id"].str.startswith(pat)].copy()
            return summary_df.copy()
        # backtest_returns
        if params and "scenario_id" in params:
            scenario = params["scenario_id"]
            df = returns_df.copy()
            if scenario.startswith("cost_") or scenario == "baseline":
                return df
            if scenario.startswith("excl_") or scenario.startswith("sens_"):
                return df
            return df
        return returns_df.copy()

    db.read_query.side_effect = read_query_side_effect
    return db


# ---------------------------------------------------------------------------
# Performance charts
# ---------------------------------------------------------------------------


class TestPerformanceCharts:

    def test_equity_curve_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "equity.png"
        plot_equity_curve(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_drawdown_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "drawdown.png"
        plot_drawdown(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_monthly_excess_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "excess.png"
        plot_monthly_excess(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_long_short_contribution_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "contrib.png"
        plot_long_short_contribution(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_skips_when_no_data(self, tmp_path):
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        out = tmp_path / "empty.png"
        plot_equity_curve(db, out)
        assert not out.exists()


# ---------------------------------------------------------------------------
# Factor analysis charts
# ---------------------------------------------------------------------------


class TestFactorAnalysisCharts:

    def test_ic_weights_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "ic.png"
        plot_ic_weights(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_rolling_sharpe_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "rolling.png"
        plot_rolling_sharpe(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_rolling_sharpe_skips_short_series(self, tmp_path):
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame(
            {
                "rebalance_date": pd.date_range("2024-01-31", periods=5, freq="ME"),
                "gross_return": [0.01] * 5,
                "net_return": [0.01] * 5,
                "long_return": [0.008] * 5,
                "short_return": [0.002] * 5,
                "benchmark_return": [0.007] * 5,
                "excess_return": [0.003] * 5,
                "cumulative_return": [0.01, 0.02, 0.03, 0.04, 0.05],
                "turnover": [0.2] * 5,
                "transaction_cost": [0.002] * 5,
            }
        )
        out = tmp_path / "rolling.png"
        plot_rolling_sharpe(db, out, window=12)
        assert not out.exists()


# ---------------------------------------------------------------------------
# Robustness charts
# ---------------------------------------------------------------------------


class TestRobustnessCharts:

    def test_parameter_sensitivity_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "sens.png"
        plot_parameter_sensitivity(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_cost_sensitivity_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "cost.png"
        plot_cost_sensitivity(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0

    def test_factor_exclusion_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "excl.png"
        plot_factor_exclusion(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# Trading chart
# ---------------------------------------------------------------------------


class TestTradingChart:

    def test_monthly_turnover_writes_png(self, tmp_path, mock_db_full):
        out = tmp_path / "turnover.png"
        plot_monthly_turnover(mock_db_full, out)
        assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class TestTables:

    def test_summary_table_writes_csv(self, tmp_path, mock_db_full):
        out = tmp_path / "summary.csv"
        export_summary_table(mock_db_full, out)
        assert out.exists()
        df = pd.read_csv(out)
        assert "Metric" in df.columns and "Value" in df.columns
        assert len(df) >= 10  # at least 10 metric rows

    def test_summary_table_skips_unknown_scenario(self, tmp_path, mock_db_full):
        out = tmp_path / "summary.csv"
        export_summary_table(mock_db_full, out, scenario_id="does_not_exist")
        assert not out.exists()

    def test_cost_table_writes_csv(self, tmp_path, mock_db_full):
        out = tmp_path / "cost.csv"
        export_cost_table(mock_db_full, out)
        assert out.exists()
        df = pd.read_csv(out)
        assert len(df) == 4
        assert "Sharpe Ratio" in df.columns

    def test_factor_exclusion_table_writes_csv(self, tmp_path, mock_db_full):
        out = tmp_path / "excl.csv"
        export_factor_exclusion_table(mock_db_full, out)
        assert out.exists()
        df = pd.read_csv(out)
        assert len(df) == 5

    def test_sensitivity_table_writes_csv(self, tmp_path, mock_db_full):
        out = tmp_path / "sens.csv"
        export_sensitivity_table(mock_db_full, out)
        assert out.exists()
        df = pd.read_csv(out)
        # baseline + sens_sel_0.05 + sens_ic_24 = 3 rows in fixture
        assert len(df) >= 3


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestRunReporting:

    def test_creates_directory_structure(self, tmp_path, mock_db_full):
        run_reporting(mock_db_full, output_dir=str(tmp_path))
        charts_dir = tmp_path / "charts"
        tables_dir = tmp_path / "tables"
        assert charts_dir.exists()
        assert tables_dir.exists()

    def test_writes_all_10_charts(self, tmp_path, mock_db_full):
        run_reporting(mock_db_full, output_dir=str(tmp_path))
        charts_dir = tmp_path / "charts"
        png_files = list(charts_dir.glob("*.png"))
        assert len(png_files) == 10

    def test_writes_all_4_tables(self, tmp_path, mock_db_full):
        run_reporting(mock_db_full, output_dir=str(tmp_path))
        tables_dir = tmp_path / "tables"
        csv_files = list(tables_dir.glob("*.csv"))
        assert len(csv_files) == 4

    def test_creates_output_dir_when_missing(self, tmp_path, mock_db_full):
        target = tmp_path / "subdir" / "nested"
        run_reporting(mock_db_full, output_dir=str(target))
        assert target.exists()


# ---------------------------------------------------------------------------
# Empty-data skip branches (one per chart and table)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_empty():
    """Mock DB that returns an empty DataFrame for any query."""
    db = MagicMock()
    db.read_query.return_value = pd.DataFrame()
    return db


class TestEmptyDataSkipBranches:

    def test_drawdown_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_drawdown(mock_db_empty, out)
        assert not out.exists()

    def test_monthly_excess_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_monthly_excess(mock_db_empty, out)
        assert not out.exists()

    def test_long_short_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_long_short_contribution(mock_db_empty, out)
        assert not out.exists()

    def test_ic_weights_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_ic_weights(mock_db_empty, out)
        assert not out.exists()

    def test_parameter_sensitivity_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_parameter_sensitivity(mock_db_empty, out)
        assert not out.exists()

    def test_cost_sensitivity_skips_when_all_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_cost_sensitivity(mock_db_empty, out)
        assert not out.exists()

    def test_factor_exclusion_skips_when_summary_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_factor_exclusion(mock_db_empty, out)
        assert not out.exists()

    def test_factor_exclusion_skips_when_no_matching_rows(self, tmp_path):
        """summary_df has rows but none match baseline or excl_*."""
        db = MagicMock()
        df = pd.DataFrame(
            {
                "scenario_id": ["sens_sel_0.05"],
                "annualised_return": [0.09],
                "sharpe_ratio": [0.54],
                "alpha": [0.02],
            }
        )
        db.read_query.return_value = df
        out = tmp_path / "x.png"
        plot_factor_exclusion(db, out)
        assert not out.exists()

    def test_monthly_turnover_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.png"
        plot_monthly_turnover(mock_db_empty, out)
        assert not out.exists()

    def test_cost_table_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.csv"
        export_cost_table(mock_db_empty, out)
        assert not out.exists()

    def test_factor_exclusion_table_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.csv"
        export_factor_exclusion_table(mock_db_empty, out)
        assert not out.exists()

    def test_sensitivity_table_skips_when_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.csv"
        export_sensitivity_table(mock_db_empty, out)
        assert not out.exists()

    def test_summary_table_skips_when_db_empty(self, tmp_path, mock_db_empty):
        out = tmp_path / "x.csv"
        export_summary_table(mock_db_empty, out)
        assert not out.exists()

    def test_cost_table_skips_when_no_matching_scenarios(self, tmp_path):
        """df has rows but none match baseline or cost_*."""
        db = MagicMock()
        df = pd.DataFrame({"scenario_id": ["sens_sel_0.05", "excl_value"]})
        db.read_query.return_value = df
        out = tmp_path / "x.csv"
        export_cost_table(db, out)
        assert not out.exists()

    def test_factor_exclusion_table_skips_when_no_matches(self, tmp_path):
        """df has rows but none match baseline or excl_*."""
        db = MagicMock()
        df = pd.DataFrame({"scenario_id": ["sens_sel_0.05", "cost_low"]})
        db.read_query.return_value = df
        out = tmp_path / "x.csv"
        export_factor_exclusion_table(db, out)
        assert not out.exists()

    def test_sensitivity_table_skips_when_no_matches(self, tmp_path):
        """df has rows but none match baseline or sens_*."""
        db = MagicMock()
        df = pd.DataFrame({"scenario_id": ["cost_low", "excl_value"]})
        db.read_query.return_value = df
        out = tmp_path / "x.csv"
        export_sensitivity_table(db, out)
        assert not out.exists()


# ---------------------------------------------------------------------------
# Path argument shape
# ---------------------------------------------------------------------------


class TestPathTypes:

    def test_accepts_pathlib_path(self, tmp_path, mock_db_full):
        out = Path(tmp_path) / "p.png"
        plot_equity_curve(mock_db_full, out)
        assert out.exists()
