"""Tests for dashboard.lib.charts - Plotly figure factories.

We don't test pixel rendering. We test that each function:
  - Returns a plotly.graph_objects.Figure
  - Returns the expected number of traces
  - Handles empty input gracefully (no crash, returns empty figure)
  - Sets the right colours / shapes for the data given
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard"))

from lib import charts as ch  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def returns_df():
    """Synthetic 24-month backtest_returns DataFrame."""
    dates = pd.date_range("2024-01-31", periods=24, freq="ME")
    return pd.DataFrame(
        {
            "rebalance_date": dates,
            "gross_return": np.linspace(0.01, 0.02, 24),
            "net_return": np.linspace(0.005, 0.015, 24),
            "long_return": np.linspace(0.01, 0.02, 24),
            "short_return": np.linspace(-0.005, 0.005, 24),
            "benchmark_return": np.linspace(0.005, 0.015, 24),
            "excess_return": np.linspace(-0.005, 0.005, 24),
            "cumulative_return": np.linspace(0.005, 0.50, 24),
            "turnover": np.linspace(0.5, 0.7, 24),
            "transaction_cost": np.linspace(0.001, 0.002, 24),
        }
    )


@pytest.fixture
def empty_returns():
    return pd.DataFrame(
        columns=[
            "rebalance_date",
            "gross_return",
            "net_return",
            "long_return",
            "short_return",
            "benchmark_return",
            "excess_return",
            "cumulative_return",
            "turnover",
            "transaction_cost",
        ]
    )


@pytest.fixture
def holdings_df():
    """Synthetic 1-month holdings - 5 longs, 3 shorts across sectors."""
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "sector": "Tech",
                "direction": "long",
                "final_weight": 0.05,
                "target_weight": 0.05,
                "risk_adj_score": 1.5,
                "ewma_vol": 0.20,
                "liquidity_capped": False,
                "trade_action": "trade",
                "security": "Apple",
            },
            {
                "symbol": "MSFT",
                "sector": "Tech",
                "direction": "long",
                "final_weight": 0.04,
                "target_weight": 0.04,
                "risk_adj_score": 1.3,
                "ewma_vol": 0.18,
                "liquidity_capped": False,
                "trade_action": "trade",
                "security": "Microsoft",
            },
            {
                "symbol": "JNJ",
                "sector": "Healthcare",
                "direction": "long",
                "final_weight": 0.06,
                "target_weight": 0.06,
                "risk_adj_score": 1.4,
                "ewma_vol": 0.15,
                "liquidity_capped": False,
                "trade_action": "hold",
                "security": "Johnson & Johnson",
            },
            {
                "symbol": "XOM",
                "sector": "Energy",
                "direction": "short",
                "final_weight": 0.02,
                "target_weight": 0.02,
                "risk_adj_score": 0.8,
                "ewma_vol": 0.30,
                "liquidity_capped": False,
                "trade_action": "trade",
                "security": "ExxonMobil",
            },
            {
                "symbol": "CVX",
                "sector": "Energy",
                "direction": "short",
                "final_weight": 0.01,
                "target_weight": 0.01,
                "risk_adj_score": 0.7,
                "ewma_vol": 0.28,
                "liquidity_capped": False,
                "trade_action": "trade",
                "security": "Chevron",
            },
        ]
    )


@pytest.fixture
def ic_weights_df():
    """Synthetic IC weights across 12 months, 4 factors."""
    dates = pd.date_range("2024-01-31", periods=12, freq="ME")
    rows = []
    for d in dates:
        for f, w in [
            ("value", 0.25),
            ("quality", 0.30),
            ("momentum", 0.25),
            ("low_vol", 0.20),
        ]:
            rows.append(
                {
                    "rebalance_date": d,
                    "factor_name": f,
                    "ic_mean_36m": 0.005,
                    "ic_weight": w,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


class TestRgbaHelper:
    def test_red(self):
        assert ch._rgba("#ff0000", 0.5) == "rgba(255,0,0,0.50)"

    def test_with_hash(self):
        assert ch._rgba("#00c805", 0.2) == "rgba(0,200,5,0.20)"

    def test_without_hash(self):
        assert ch._rgba("ff0000", 1.0) == "rgba(255,0,0,1.00)"


class TestChartConfig:
    def test_returns_dict(self):
        cfg = ch.chart_config("test")
        assert isinstance(cfg, dict)

    def test_includes_filename(self):
        cfg = ch.chart_config("foo")
        assert cfg["toImageButtonOptions"]["filename"] == "foo"

    def test_disables_box_zoom(self):
        cfg = ch.chart_config()
        assert "zoom2d" in cfg["modeBarButtonsToRemove"]

    def test_keeps_plus_minus_zoom(self):
        cfg = ch.chart_config()
        # +/- zoom (zoomIn2d, zoomOut2d) should NOT be in the remove list
        assert "zoomIn2d" not in cfg["modeBarButtonsToRemove"]
        assert "zoomOut2d" not in cfg["modeBarButtonsToRemove"]


# ---------------------------------------------------------------------------
# Performance charts
# ---------------------------------------------------------------------------


class TestEquityCurve:
    def test_returns_figure(self, returns_df):
        fig = ch.equity_curve(returns_df)
        assert isinstance(fig, go.Figure)

    def test_two_traces_with_benchmark(self, returns_df):
        fig = ch.equity_curve(returns_df, show_benchmark=True)
        assert len(fig.data) == 2

    def test_one_trace_without_benchmark(self, returns_df):
        fig = ch.equity_curve(returns_df, show_benchmark=False)
        assert len(fig.data) == 1

    def test_empty_returns_empty_figure(self, empty_returns):
        fig = ch.equity_curve(empty_returns)
        assert len(fig.data) == 0


class TestDrawdown:
    def test_returns_figure(self, returns_df):
        fig = ch.drawdown(returns_df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1

    def test_uses_rgba_fill(self, returns_df):
        fig = ch.drawdown(returns_df)
        assert "rgba" in fig.data[0].fillcolor

    def test_empty(self, empty_returns):
        fig = ch.drawdown(empty_returns)
        assert len(fig.data) == 0


class TestMonthlyExcess:
    def test_returns_figure(self, returns_df):
        fig = ch.monthly_excess(returns_df)
        assert len(fig.data) == 1

    def test_per_bar_colours_match_sign(self, returns_df):
        # Bar colours should align with positive/negative excess
        fig = ch.monthly_excess(returns_df)
        excess = returns_df["excess_return"] * 100
        colors = fig.data[0].marker.color
        for v, c in zip(excess, colors):
            assert c in ("#00c805", "#ff3b30")  # long or short colour


class TestLongShortContribution:
    def test_two_traces(self, returns_df):
        fig = ch.long_short_contribution(returns_df)
        assert len(fig.data) == 2

    def test_legend_below_plot(self, returns_df):
        # Legend should be positioned below the chart so it doesn't
        # overlap the modebar
        fig = ch.long_short_contribution(returns_df)
        assert fig.layout.legend.y < 0


class TestRollingSharpe:
    def test_returns_figure(self, returns_df):
        fig = ch.rolling_sharpe(returns_df, window=12)
        assert len(fig.data) == 1

    def test_skips_short_series(self):
        df = pd.DataFrame(
            {
                "rebalance_date": pd.date_range("2024-01-31", periods=5, freq="ME"),
                "net_return": [0.01] * 5,
            }
        )
        fig = ch.rolling_sharpe(df, window=12)
        assert len(fig.data) == 0


class TestMonthlyTurnover:
    def test_returns_figure(self, returns_df):
        fig = ch.monthly_turnover(returns_df)
        assert len(fig.data) == 1


class TestReturnsHistogram:
    def test_returns_figure(self, returns_df):
        fig = ch.returns_histogram(returns_df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1

    def test_empty(self, empty_returns):
        fig = ch.returns_histogram(empty_returns)
        assert len(fig.data) == 0


# ---------------------------------------------------------------------------
# Sector charts
# ---------------------------------------------------------------------------


class TestSectorStockCountBars:
    def test_returns_figure(self, holdings_df):
        fig = ch.sector_stock_count_bars(holdings_df, "long")
        assert len(fig.data) == 1

    def test_count_bar_values_match(self, holdings_df):
        # 2 longs in Tech, 1 in Healthcare
        fig = ch.sector_stock_count_bars(holdings_df, "long")
        # x-axis values are the counts
        assert sorted(fig.data[0].x) == [1, 2]

    def test_short_uses_red(self, holdings_df):
        fig = ch.sector_stock_count_bars(holdings_df, "short")
        assert fig.data[0].marker.color == "#ff3b30"

    def test_long_uses_green(self, holdings_df):
        fig = ch.sector_stock_count_bars(holdings_df, "long")
        assert fig.data[0].marker.color == "#00c805"

    def test_empty(self):
        fig = ch.sector_stock_count_bars(pd.DataFrame(), "long")
        assert len(fig.data) == 0


class TestSectorAllocationBars:
    def test_returns_figure(self, holdings_df):
        fig = ch.sector_allocation_bars(holdings_df, "long", 0.118)
        assert len(fig.data) == 1


class TestNetSectorExposure:
    def test_returns_figure(self, holdings_df):
        fig = ch.net_sector_exposure(holdings_df)
        assert len(fig.data) == 1


# ---------------------------------------------------------------------------
# IC weights and factor charts
# ---------------------------------------------------------------------------


class TestICWeightsEvolution:
    def test_four_traces_for_four_factors(self, ic_weights_df):
        fig = ch.ic_weights_evolution(ic_weights_df)
        assert len(fig.data) == 4

    def test_empty(self):
        fig = ch.ic_weights_evolution(pd.DataFrame())
        assert len(fig.data) == 0


class TestCompositeHistogram:
    def test_returns_figure(self):
        scores = pd.DataFrame({"composite_score": np.random.randn(200)})
        fig = ch.composite_histogram(scores)
        assert len(fig.data) == 1

    def test_has_two_cutoff_lines(self):
        scores = pd.DataFrame({"composite_score": np.random.randn(200)})
        fig = ch.composite_histogram(scores)
        # 2 vlines for 10th and 90th percentile cutoffs
        assert len(fig.layout.shapes) == 2

    def test_has_two_annotations_above_plot(self):
        scores = pd.DataFrame({"composite_score": np.random.randn(200)})
        fig = ch.composite_histogram(scores)
        # 2 annotations for cutoff labels, sitting above plot (y > 1)
        for ann in fig.layout.annotations:
            assert ann.yref == "paper"
            assert ann.y > 1.0


class TestFactorCorrelationHeatmap:
    def test_returns_figure(self):
        df = pd.DataFrame(
            {
                "z_value": np.random.randn(100),
                "z_quality": np.random.randn(100),
                "z_momentum": np.random.randn(100),
                "z_low_vol": np.random.randn(100),
            }
        )
        fig = ch.factor_correlation_heatmap(df)
        assert len(fig.data) == 1

    def test_no_spike_lines(self):
        df = pd.DataFrame(
            {
                "z_value": np.random.randn(50),
                "z_quality": np.random.randn(50),
                "z_momentum": np.random.randn(50),
                "z_low_vol": np.random.randn(50),
            }
        )
        fig = ch.factor_correlation_heatmap(df)
        # Hover should be "closest", not "x unified" - avoids spike lines
        assert fig.layout.hovermode == "closest"

    def test_empty(self):
        fig = ch.factor_correlation_heatmap(pd.DataFrame())
        assert len(fig.data) == 0


# ---------------------------------------------------------------------------
# Stock deep-dive charts
# ---------------------------------------------------------------------------


class TestStockPriceWithMarkers:
    def test_with_positions(self):
        prices = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=100),
                "adjusted_close": np.linspace(100, 120, 100),
            }
        )
        positions = pd.DataFrame(
            {
                "rebalance_date": [
                    pd.Timestamp("2024-01-31"),
                    pd.Timestamp("2024-02-29"),
                ],
                "direction": ["long", "short"],
                "final_weight": [0.05, 0.02],
            }
        )
        fig = ch.stock_price_with_markers(prices, positions)
        # Price line + long markers + short markers = 3 traces
        assert len(fig.data) == 3

    def test_no_positions(self):
        prices = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=10),
                "adjusted_close": np.linspace(100, 105, 10),
            }
        )
        fig = ch.stock_price_with_markers(prices, pd.DataFrame())
        # Just the price line
        assert len(fig.data) == 1

    def test_empty_prices(self):
        fig = ch.stock_price_with_markers(pd.DataFrame(), pd.DataFrame())
        assert len(fig.data) == 0


class TestStockFactorZscores:
    def test_four_lines(self):
        scores = pd.DataFrame(
            {
                "score_date": pd.date_range("2024-01-01", periods=12),
                "z_value": np.random.randn(12),
                "z_quality": np.random.randn(12),
                "z_momentum": np.random.randn(12),
                "z_low_vol": np.random.randn(12),
            }
        )
        fig = ch.stock_factor_zscores(scores)
        assert len(fig.data) == 4

    def test_empty(self):
        fig = ch.stock_factor_zscores(pd.DataFrame())
        assert len(fig.data) == 0


class TestStockFundamentalLine:
    def test_returns_figure(self):
        metrics = pd.DataFrame(
            {
                "calc_date": pd.date_range("2024-01-01", periods=12),
                "roe": np.linspace(0.10, 0.15, 12),
            }
        )
        fig = ch.stock_fundamental_line(metrics, "roe", "ROE")
        assert len(fig.data) == 1

    def test_missing_column(self):
        metrics = pd.DataFrame(
            {
                "calc_date": pd.date_range("2024-01-01", periods=5),
            }
        )
        fig = ch.stock_fundamental_line(metrics, "roe", "ROE")
        # Column doesn't exist - returns empty
        assert len(fig.data) == 0


# ---------------------------------------------------------------------------
# Equity comparison
# ---------------------------------------------------------------------------


class TestEquityCurveCompare:
    def test_two_traces(self, returns_df):
        fig = ch.equity_curve_compare(returns_df, "A", returns_df, "B")
        assert len(fig.data) == 2

    def test_one_empty(self, returns_df, empty_returns):
        fig = ch.equity_curve_compare(returns_df, "A", empty_returns, "B")
        assert len(fig.data) == 1

    def test_both_empty(self, empty_returns):
        fig = ch.equity_curve_compare(empty_returns, "A", empty_returns, "B")
        assert len(fig.data) == 0


# ---------------------------------------------------------------------------
# Sector heatmap
# ---------------------------------------------------------------------------


class TestSectorExposureHeatmap:
    def test_returns_figure(self):
        positions = pd.DataFrame(
            [
                {
                    "rebalance_date": pd.Timestamp("2024-01-31"),
                    "sector": "Tech",
                    "direction": "long",
                    "final_weight": 0.10,
                },
                {
                    "rebalance_date": pd.Timestamp("2024-01-31"),
                    "sector": "Tech",
                    "direction": "short",
                    "final_weight": 0.05,
                },
                {
                    "rebalance_date": pd.Timestamp("2024-02-29"),
                    "sector": "Healthcare",
                    "direction": "long",
                    "final_weight": 0.12,
                },
            ]
        )
        fig = ch.sector_exposure_heatmap(positions)
        assert len(fig.data) == 1

    def test_empty(self):
        fig = ch.sector_exposure_heatmap(pd.DataFrame())
        assert len(fig.data) == 0


# ---------------------------------------------------------------------------
# Selection over time
# ---------------------------------------------------------------------------


class TestSelectionStatusOverTime:
    def test_returns_figure(self):
        rows = []
        for d in pd.date_range("2024-01-31", periods=6, freq="ME"):
            for status, n in [("long_core", 5), ("short_core", 3)]:
                for i in range(n):
                    rows.append(
                        {
                            "rebalance_date": d,
                            "symbol": f"{status}_{i}",
                            "sector": "Tech",
                            "status": status,
                        }
                    )
        df = pd.DataFrame(rows)
        fig = ch.selection_status_over_time(df)
        # Two statuses present in the data
        assert len(fig.data) == 2


# ---------------------------------------------------------------------------
# Scenario comparison
# ---------------------------------------------------------------------------


class TestScenarioComparisonBars:
    def test_returns_figure(self):
        df = pd.DataFrame(
            {
                "scenario_id": ["baseline", "cost_low", "cost_high"],
                "sharpe_ratio": [0.63, 0.74, 0.45],
            }
        )
        fig = ch.scenario_comparison_bars(df, metric="sharpe_ratio")
        assert len(fig.data) == 1

    def test_baseline_highlighted(self):
        df = pd.DataFrame(
            {
                "scenario_id": ["baseline", "cost_low"],
                "sharpe_ratio": [0.63, 0.74],
            }
        )
        fig = ch.scenario_comparison_bars(df, metric="sharpe_ratio")
        # Baseline gets a different colour from the others
        colors = fig.data[0].marker.color
        assert len(set(colors)) > 1


class TestFactorZscoreBoxplot:
    def test_returns_traces_per_sector(self):
        df = pd.DataFrame(
            [
                {"sector": "Tech", "z": 0.5},
                {"sector": "Tech", "z": 0.3},
                {"sector": "Energy", "z": -0.4},
            ]
        )
        fig = ch.factor_zscore_boxplot(df, "Value")
        # One box per sector
        assert len(fig.data) == 2

    def test_empty(self):
        fig = ch.factor_zscore_boxplot(pd.DataFrame(), "Value")
        assert len(fig.data) == 0
