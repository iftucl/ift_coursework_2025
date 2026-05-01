"""Tests for Step 9 transaction cost sensitivity."""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from modules.evaluation.cost_sensitivity import (
    COST_SCENARIOS,
    CostScenario,
    fetch_baseline_returns,
    fetch_short_notional,
    recompute_returns,
    run_cost_sensitivity,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def baseline_df():
    """Minimal baseline backtest_returns rows."""
    return pd.DataFrame(
        {
            "rebalance_date": [
                date(2024, 1, 31),
                date(2024, 2, 29),
                date(2024, 3, 31),
            ],
            "gross_return": [0.02, 0.01, -0.01],
            "long_return": [0.025, 0.015, 0.005],
            "short_return": [0.005, 0.005, 0.015],
            "benchmark_return": [0.015, 0.010, -0.005],
            "turnover": [0.25, 0.30, 0.28],
        }
    )


@pytest.fixture
def short_notional_df():
    """Short notional for each rebalance date (0.3 matches baseline 130/30)."""
    return pd.DataFrame(
        {
            "rebalance_date": [
                date(2024, 1, 31),
                date(2024, 2, 29),
                date(2024, 3, 31),
            ],
            "short_notional": [0.3, 0.3, 0.3],
        }
    )


# ---------------------------------------------------------------------------
# CostScenario + module-level constants
# ---------------------------------------------------------------------------


class TestCostScenarios:

    def test_three_scenarios_defined(self):
        """Exactly 3 scenarios additional to baseline (moderate)."""
        assert len(COST_SCENARIOS) == 3

    def test_scenario_ids_match_spec(self):
        ids = {s.scenario_id for s in COST_SCENARIOS}
        assert ids == {"cost_frictionless", "cost_low", "cost_high"}

    def test_frictionless_has_zero_costs(self):
        frictionless = next(
            s for s in COST_SCENARIOS if s.scenario_id == "cost_frictionless"
        )
        assert frictionless.cost_bps == 0.0
        assert frictionless.borrow_rate == 0.0

    def test_high_is_costliest(self):
        high = next(s for s in COST_SCENARIOS if s.scenario_id == "cost_high")
        low = next(s for s in COST_SCENARIOS if s.scenario_id == "cost_low")
        assert high.cost_bps > low.cost_bps


# ---------------------------------------------------------------------------
# recompute_returns — pure function
# ---------------------------------------------------------------------------


class TestRecomputeReturns:

    def test_frictionless_net_equals_gross(self, baseline_df, short_notional_df):
        """At 0 bps + 0% borrow, net return equals gross return."""
        scenario = CostScenario("cost_frictionless", 0.0, 0.0)
        result = recompute_returns(baseline_df, short_notional_df, scenario)

        # transaction_cost should all be zero
        assert (result["transaction_cost"] == 0).all()
        # net_return should equal gross_return
        for gross, net in zip(baseline_df["gross_return"], result["net_return"]):
            assert abs(gross - net) < 1e-10

    def test_cost_formula_applied(self, baseline_df, short_notional_df):
        """cost = turnover * bps/10000 + short_notional * borrow/12."""
        scenario = CostScenario("cost_test", 50.0, 0.0120)
        result = recompute_returns(baseline_df, short_notional_df, scenario)

        # Jan: turnover=0.25, short=0.3
        # cost = 0.25 * 50/10000 + 0.3 * 0.0120/12
        expected_jan = 0.25 * 50 / 10000 + 0.3 * 0.0120 / 12
        assert abs(result.iloc[0]["transaction_cost"] - expected_jan) < 1e-10

        # Feb: turnover=0.30, short=0.3
        expected_feb = 0.30 * 50 / 10000 + 0.3 * 0.0120 / 12
        assert abs(result.iloc[1]["transaction_cost"] - expected_feb) < 1e-10

    def test_net_return_is_gross_minus_cost(self, baseline_df, short_notional_df):
        scenario = CostScenario("cost_high", 50.0, 0.0075)
        result = recompute_returns(baseline_df, short_notional_df, scenario)

        for idx in range(len(result)):
            gross = baseline_df.iloc[idx]["gross_return"]
            cost = result.iloc[idx]["transaction_cost"]
            net = result.iloc[idx]["net_return"]
            assert abs(net - (gross - cost)) < 1e-10

    def test_excess_return_is_net_minus_benchmark(self, baseline_df, short_notional_df):
        scenario = CostScenario("cost_low", 10.0, 0.0075)
        result = recompute_returns(baseline_df, short_notional_df, scenario)

        for idx in range(len(result)):
            bench = baseline_df.iloc[idx]["benchmark_return"]
            net = result.iloc[idx]["net_return"]
            excess = result.iloc[idx]["excess_return"]
            assert abs(excess - (net - bench)) < 1e-10

    def test_cumulative_return_is_cumprod(self, baseline_df, short_notional_df):
        scenario = CostScenario("cost_low", 10.0, 0.0075)
        result = recompute_returns(baseline_df, short_notional_df, scenario)

        net = result["net_return"].values
        # Hand-calc cumulative: (1+r0)(1+r1)(1+r2) - 1
        expected = (1 + net[0]) * (1 + net[1]) * (1 + net[2]) - 1
        assert abs(result.iloc[-1]["cumulative_return"] - expected) < 1e-10

    def test_scenario_id_stamped_on_rows(self, baseline_df, short_notional_df):
        scenario = CostScenario("cost_high", 50.0, 0.0075)
        result = recompute_returns(baseline_df, short_notional_df, scenario)
        assert (result["scenario_id"] == "cost_high").all()

    def test_output_columns_match_backtest_returns_schema(
        self, baseline_df, short_notional_df
    ):
        scenario = CostScenario("cost_low", 10.0, 0.0075)
        result = recompute_returns(baseline_df, short_notional_df, scenario)
        expected_cols = {
            "scenario_id",
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
        }
        assert set(result.columns) == expected_cols

    def test_higher_cost_produces_lower_net(self, baseline_df, short_notional_df):
        low = recompute_returns(
            baseline_df,
            short_notional_df,
            CostScenario("cost_low", 10.0, 0.0075),
        )
        high = recompute_returns(
            baseline_df,
            short_notional_df,
            CostScenario("cost_high", 50.0, 0.0075),
        )
        # High cost gives lower net return across all months
        assert (high["net_return"].values < low["net_return"].values).all()


# ---------------------------------------------------------------------------
# DB access helpers
# ---------------------------------------------------------------------------


class TestFetchBaselineReturns:

    def test_queries_baseline_scenario(self):
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        fetch_baseline_returns(db)

        args, _ = db.read_query.call_args
        assert "scenario_id = 'baseline'" in args[0]


class TestFetchShortNotional:

    def test_queries_short_direction(self):
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        fetch_short_notional(db)

        args, _ = db.read_query.call_args
        assert "direction = 'short'" in args[0]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestRunCostSensitivity:

    def test_empty_baseline_raises(self):
        """No baseline rows -> informative error."""
        db = MagicMock()
        db.read_query.return_value = pd.DataFrame()
        with pytest.raises(RuntimeError, match="No baseline backtest_returns"):
            run_cost_sensitivity(db)

    def test_creates_three_scenarios(self, baseline_df, short_notional_df):
        """Runs all 3 cost scenarios and returns their ids."""
        db = MagicMock()
        # Each scenario does: fetch_baseline + fetch_short_notional + compute_summary
        # But only the first two fetches happen at the start of run_cost_sensitivity,
        # and each compute_summary_metrics call does its own reads.
        db.read_query.side_effect = [
            baseline_df,
            short_notional_df,
            # compute_summary_metrics for each scenario does returns + rf_rate fetches
            baseline_df.assign(
                scenario_id="cost_frictionless",
                net_return=baseline_df["gross_return"],
                excess_return=baseline_df["gross_return"]
                - baseline_df["benchmark_return"],
                cumulative_return=0,
                transaction_cost=0,
            ),
            pd.DataFrame({"avg_rate": [0.02]}),
            baseline_df.assign(
                scenario_id="cost_low",
                net_return=baseline_df["gross_return"] - 0.001,
                excess_return=0.0,
                cumulative_return=0,
                transaction_cost=0.001,
            ),
            pd.DataFrame({"avg_rate": [0.02]}),
            baseline_df.assign(
                scenario_id="cost_high",
                net_return=baseline_df["gross_return"] - 0.005,
                excess_return=0.0,
                cumulative_return=0,
                transaction_cost=0.005,
            ),
            pd.DataFrame({"avg_rate": [0.02]}),
        ]

        with patch(
            "modules.evaluation.cost_sensitivity.DataWriter"
        ) as mock_writer_cls, patch(
            "modules.evaluation.metrics.DataWriter"
        ) as mock_metrics_writer_cls:
            mock_writer_cls.return_value = MagicMock()
            mock_metrics_writer_cls.return_value = MagicMock()
            result = run_cost_sensitivity(db)

        assert result == ["cost_frictionless", "cost_low", "cost_high"]

    def test_deletes_prior_rows_before_writing(self, baseline_df, short_notional_df):
        """Idempotent: each scenario deletes any prior rows with same scenario_id."""
        db = MagicMock()
        # Interleave returns + rf_rate reads per scenario (compute_summary_metrics
        # calls fetch_scenario_returns then fetch_risk_free_rate for each)
        returns_with_net = baseline_df.assign(net_return=0.01, cumulative_return=0.01)
        rf_rate = pd.DataFrame({"avg_rate": [0.02]})
        db.read_query.side_effect = [
            baseline_df,
            short_notional_df,
            returns_with_net,
            rf_rate,  # scenario 1
            returns_with_net,
            rf_rate,  # scenario 2
            returns_with_net,
            rf_rate,  # scenario 3
        ]

        with patch(
            "modules.evaluation.cost_sensitivity.DataWriter"
        ) as mock_writer_cls, patch(
            "modules.evaluation.metrics.DataWriter"
        ) as mock_metrics_writer_cls:
            mock_writer_cls.return_value = MagicMock()
            mock_metrics_writer_cls.return_value = MagicMock()
            run_cost_sensitivity(db)

        # Should have 3 DELETE calls (one per scenario)
        delete_calls = [c for c in db.execute.call_args_list if "DELETE" in c.args[0]]
        assert len(delete_calls) == 3
