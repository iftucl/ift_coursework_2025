"""Step 9: Transaction cost sensitivity scenarios.

Reuses baseline portfolio positions and gross returns. Only recomputes
transaction cost, net return, excess return, cumulative return, and the
summary metrics under each alternative cost assumption.

This is the PM shortcut approach (Q1 Option A):
  - Portfolio positions remain fixed at baseline
  - Only the cost formula changes per scenario
  - Does NOT re-optimise the no-trade threshold to match the new cost
  - Documented limitation: tests cost drag on a fixed strategy, not
    counterfactual strategy behaviour under different cost regimes.

Three new scenarios are produced. The existing baseline scenario
(scenario_id='baseline') already represents moderate cost (25 bps + 0.75%).
"""

import logging
from dataclasses import dataclass

import pandas as pd

from modules.db.db_connection import PostgresConnection
from modules.evaluation.metrics import compute_summary_metrics
from modules.output.data_writer import DataWriter

logger = logging.getLogger(__name__)
SCHEMA = "team_wittgenstein"


@dataclass(frozen=True)
class CostScenario:
    """A transaction cost configuration for one sensitivity run."""

    scenario_id: str
    cost_bps: float  # one-way turnover cost in basis points
    borrow_rate: float  # annual short-borrow rate


# The 3 scenarios additional to baseline (which is moderate: 25 bps + 0.75%)
COST_SCENARIOS = (
    CostScenario("cost_frictionless", 0.0, 0.0),
    CostScenario("cost_low", 10.0, 0.0075),
    CostScenario("cost_high", 50.0, 0.0075),
)


# ---------------------------------------------------------------------------
# DB access helpers
# ---------------------------------------------------------------------------


def fetch_baseline_returns(db: PostgresConnection) -> pd.DataFrame:
    """Load baseline backtest_returns rows (gross, turnover, benchmark)."""
    query = """
        SELECT rebalance_date, gross_return, long_return, short_return,
               benchmark_return, turnover
        FROM team_wittgenstein.backtest_returns
        WHERE scenario_id = 'baseline'
        ORDER BY rebalance_date
    """
    return db.read_query(query)


def fetch_short_notional(db: PostgresConnection) -> pd.DataFrame:
    """Sum short final_weights per rebalance_date to get short notional."""
    query = """
        SELECT rebalance_date, SUM(final_weight) AS short_notional
        FROM team_wittgenstein.portfolio_positions
        WHERE direction = 'short'
        GROUP BY rebalance_date
        ORDER BY rebalance_date
    """
    return db.read_query(query)


# ---------------------------------------------------------------------------
# Pure logic (testable without DB)
# ---------------------------------------------------------------------------


def recompute_returns(
    baseline: pd.DataFrame,
    short_notional_df: pd.DataFrame,
    scenario: CostScenario,
) -> pd.DataFrame:
    """Apply a new cost formula to baseline returns.

    The gross return and turnover come from baseline. Short notional is
    merged per date. The cost, net return, excess return, and cumulative
    return are recomputed. scenario_id is set to the new scenario's id.

    Args:
        baseline:         DataFrame from fetch_baseline_returns.
        short_notional_df: DataFrame from fetch_short_notional.
        scenario:         CostScenario to apply.

    Returns:
        DataFrame ready to write to backtest_returns.
    """
    df = baseline.copy()
    df = df.merge(short_notional_df, on="rebalance_date", how="left")
    df["short_notional"] = df["short_notional"].fillna(0.0)

    # New cost formula
    df["transaction_cost"] = (
        df["turnover"].astype(float) * scenario.cost_bps / 10_000
        + df["short_notional"].astype(float) * scenario.borrow_rate / 12
    )

    df["net_return"] = df["gross_return"].astype(float) - df["transaction_cost"]
    df["excess_return"] = df["net_return"] - df["benchmark_return"].astype(float)

    # Compound net returns for cumulative_return
    df = df.sort_values("rebalance_date").reset_index(drop=True)
    df["cumulative_return"] = (1 + df["net_return"]).cumprod() - 1

    df["scenario_id"] = scenario.scenario_id

    # Drop the helper column - not part of backtest_returns schema
    df = df.drop(columns=["short_notional"])

    return df[
        [
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
        ]
    ]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_cost_sensitivity(db: PostgresConnection) -> list[str]:
    """Run all 3 additional cost scenarios and compute their summary metrics.

    For each scenario:
      1. Read baseline backtest_returns and short notional
      2. Recompute net/excess/cumulative returns under the new cost
      3. Delete any existing rows for the scenario_id (idempotent re-runs)
      4. Write new rows to backtest_returns
      5. Call compute_summary_metrics to populate backtest_summary

    Returns:
        List of scenario_ids created.
    """
    baseline = fetch_baseline_returns(db)
    if baseline is None or baseline.empty:
        raise RuntimeError(
            "No baseline backtest_returns found - run baseline backtest first"
        )

    short_notional_df = fetch_short_notional(db)
    writer = DataWriter(db)
    created = []

    for scenario in COST_SCENARIOS:
        logger.info(
            "Cost scenario: %s (bps=%.1f, borrow=%.4f)",
            scenario.scenario_id,
            scenario.cost_bps,
            scenario.borrow_rate,
        )

        new_df = recompute_returns(baseline, short_notional_df, scenario)

        # Idempotent: wipe prior rows for this scenario before writing
        db.execute(
            "DELETE FROM team_wittgenstein.backtest_returns "
            "WHERE scenario_id = :scenario_id",
            {"scenario_id": scenario.scenario_id},
        )
        writer.write_backtest_returns(new_df, scenario.scenario_id)

        summary = compute_summary_metrics(db, scenario.scenario_id)
        created.append(scenario.scenario_id)

        logger.info(
            "%s | ann_ret=%.4f sharpe=%.4f max_dd=%.4f",
            scenario.scenario_id,
            summary["annualised_return"],
            summary["sharpe_ratio"],
            summary["max_drawdown"],
        )

    logger.info("Cost sensitivity complete: %d scenarios created", len(created))
    return created
