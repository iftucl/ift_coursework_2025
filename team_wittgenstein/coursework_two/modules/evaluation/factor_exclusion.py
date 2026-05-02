"""Step 10: Factor exclusion robustness analysis.

For each of the four factors (value, quality, momentum, low_vol), re-runs
the full pipeline with that factor's IC weight forced to zero. The
remaining three factors are renormalised. This tells us whether any single
factor disproportionately drives strategy returns.

Implementation follows Q2 Option A (in-memory DataFrames):
  - Composite scores computed in-memory (persist=False)
  - Stock selection done in-memory using the variant composites
  - Portfolio positions built in-memory using the variant's own
    prior-month positions for the no-trade zone
  - Only backtest_returns and backtest_summary are persisted (per scenario_id)
  - Baseline DB tables (factor_scores, selection_status, portfolio_positions)
    are never touched

This keeps baseline data intact and lets all 4 factor exclusion runs share
the underlying factor z-scores and price data without contention.
"""

import logging
from dataclasses import dataclass

import pandas as pd

from modules.backtest.backtest_engine import BacktestConfig, run_backtest
from modules.composite.composite_scorer import CompositeConfig, run_composite_scorer
from modules.db.db_connection import PostgresConnection
from modules.evaluation.metrics import compute_summary_metrics
from modules.output.data_writer import DataWriter
from modules.portfolio.ewma_volatility import EWMAConfig, run_ewma_volatility
from modules.portfolio.position_builder import PositionConfig, build_portfolio_positions
from modules.portfolio.risk_adjusted import compute_risk_adjusted_scores
from modules.portfolio.stock_selector import SelectionConfig, run_stock_selection

logger = logging.getLogger(__name__)
SCHEMA = "team_wittgenstein"

EXCLUDED_FACTORS = ("value", "quality", "momentum", "low_vol")


@dataclass(frozen=True)
class FactorExclusionConfig:
    """Bundle of all configs needed to re-run the pipeline per scenario."""

    composite: CompositeConfig
    selection: SelectionConfig
    ewma: EWMAConfig
    position: PositionConfig
    backtest: BacktestConfig


# ---------------------------------------------------------------------------
# Per-rebalance-date in-memory pipeline
# ---------------------------------------------------------------------------


def _build_one_rebalance(
    db: PostgresConnection,
    rebalance_date,
    sector_map: dict,
    excluded_factor: str | None,
    config: FactorExclusionConfig,
    prior_selection: pd.DataFrame,
    prior_positions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the full per-month pipeline in-memory for one variant scenario.

    excluded_factor=None runs a normal pipeline (no exclusion); used by
    parameter sensitivity scenarios that vary configs other than factor IC.

    Returns a tuple of (positions, full_selection) where positions is the
    portfolio_positions-shaped DataFrame for this date and full_selection is
    the complete selection_status (including not_selected) for use as the
    next month's prior_selection.

    On any empty intermediate, returns (empty, empty) so callers can skip
    the date and reuse the previous prior_*.
    """
    # 1. Composite score with excluded factor (no DB persistence)
    composite = run_composite_scorer(
        db,
        rebalance_date,
        config.composite,
        excluded_factor=excluded_factor,
        persist=False,
    )
    if composite.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 2. Stock selection - feed in our composite + variant's own prior selection
    selected = run_stock_selection(
        db,
        rebalance_date,
        sector_map,
        config.selection,
        composite_scores=composite,
        prior_selection=prior_selection,
        persist=False,
    )
    if selected.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 3. EWMA volatility (reads price_data only - no contention)
    symbols_selected = selected["symbol"].tolist()
    ewma_vols = run_ewma_volatility(db, symbols_selected, rebalance_date, config.ewma)

    # 4. Risk-adjusted scores (pure function)
    scored = compute_risk_adjusted_scores(selected, ewma_vols)
    if scored.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 5. Portfolio construction with variant's own prior positions
    positions = build_portfolio_positions(
        db,
        scored,
        rebalance_date,
        config.position,
        prior_positions=prior_positions,
    )

    # 6. Build full_selection with same shape as DB selection_status
    #    (we reconstruct it from `selected` plus implicit not_selected entries)
    #    For simplicity, just keep the selected stocks as the prior_selection
    #    next month - "not_selected" stocks will get default treatment.
    full_selection = selected[["symbol", "status", "buffer_months_count"]].copy()
    full_selection["entry_date"] = None

    return positions, full_selection


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_factor_exclusion(
    db: PostgresConnection,
    sector_map: dict,
    config: FactorExclusionConfig,
) -> list[str]:
    """Run all 4 factor exclusion scenarios in-memory.

    For each excluded factor:
      1. Loop over the same rebalance dates as the baseline run
      2. Build positions in-memory (no DB writes for intermediate state)
      3. Run the backtest with positions_override
      4. Persist backtest_returns + backtest_summary under scenario_id
         'excl_<factor>'
      5. compute_summary_metrics for that scenario

    Args:
        db:        Active PostgresConnection.
        sector_map: symbol -> GICS sector mapping (same as baseline).
        config:    Bundle of all configs needed for the pipeline.

    Returns:
        List of scenario_ids created.
    """
    # Discover the rebalance dates from baseline portfolio_positions
    dates_df = db.read_query("""
        SELECT DISTINCT rebalance_date
        FROM team_wittgenstein.portfolio_positions
        ORDER BY rebalance_date
        """)
    if dates_df.empty:
        raise RuntimeError("portfolio_positions is empty - run baseline backfill first")
    rebalance_dates = pd.to_datetime(dates_df["rebalance_date"]).dt.date.tolist()

    writer = DataWriter(db)
    created = []

    for excluded_factor in EXCLUDED_FACTORS:
        scenario_id = f"excl_{excluded_factor}"
        logger.info(
            "===== Factor exclusion scenario: %s (%d dates) =====",
            scenario_id,
            len(rebalance_dates),
        )

        # Loop through dates building positions in-memory
        all_positions = []
        prior_selection = pd.DataFrame()
        prior_positions = pd.DataFrame()

        for i, rd in enumerate(rebalance_dates, 1):
            logger.info("[%s] [%d/%d] %s", scenario_id, i, len(rebalance_dates), rd)
            positions, full_selection = _build_one_rebalance(
                db,
                rd,
                sector_map,
                excluded_factor,
                config,
                prior_selection=prior_selection,
                prior_positions=prior_positions,
            )
            if not positions.empty:
                all_positions.append(positions)
                prior_positions = positions[
                    ["symbol", "direction", "final_weight"]
                ].copy()
                prior_selection = full_selection

        if not all_positions:
            logger.warning("No positions built for %s - skipping backtest", scenario_id)
            continue

        # Concatenate all monthly positions for the backtest engine
        all_positions_df = pd.concat(all_positions, ignore_index=True)

        # Run the in-memory backtest for this scenario
        scenario_config = BacktestConfig(
            cost_bps=config.backtest.cost_bps,
            borrow_rate=config.backtest.borrow_rate,
            scenario_id=scenario_id,
        )
        backtest_df = run_backtest(
            db, scenario_config, positions_override=all_positions_df
        )

        # Wipe any prior rows for this scenario before writing
        db.execute(
            "DELETE FROM team_wittgenstein.backtest_returns "
            "WHERE scenario_id = :scenario_id",
            {"scenario_id": scenario_id},
        )
        writer.write_backtest_returns(backtest_df, scenario_id)

        summary = compute_summary_metrics(db, scenario_id)
        created.append(scenario_id)

        logger.info(
            "%s | ann_ret=%.4f sharpe=%.4f max_dd=%.4f",
            scenario_id,
            summary["annualised_return"],
            summary["sharpe_ratio"],
            summary["max_drawdown"],
        )

    logger.info("Factor exclusion complete: %d scenarios created", len(created))
    return created
