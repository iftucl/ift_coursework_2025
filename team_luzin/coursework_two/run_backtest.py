#!/usr/bin/env python3
"""
Coursework Two portfolio construction and backtesting orchestrator.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from modules.backtest import run_strategy_backtest
from modules.benchmarks import build_benchmark_panel
from modules.config import load_config
from modules.cw1_loader import load_cw1_inputs
from modules.metrics import evaluate_strategy
from modules.portfolio import build_portfolio
from modules.robustness import run_robustness_checks
from modules.selection import select_stocks
from modules.snapshot_builder import build_monthly_snapshot_history
from modules.universe import define_investable_universe
from modules.writer import write_outputs

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coursework Two backtesting pipeline")
    parser.add_argument(
        "--config",
        type=str,
        default="config/conf.json",
        help="Path to the CW2 configuration file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load config and validate paths without running the full pipeline",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))

    if args.dry_run:
        logger.info("CW2 dry run complete. Config loaded successfully.")
        logger.info("CW1 analytics path: %s", config["paths"]["cw1_analytics_dir"])
        return 0

    cw1_inputs = load_cw1_inputs(config)
    built_factors, built_selections = build_monthly_snapshot_history(cw1_inputs, config)
    if not built_factors.empty:
        cw1_inputs.historical_factors = built_factors
        cw1_inputs.historical_selections = built_selections
        logger.info(
            "Built %s monthly factor snapshots and %s monthly selection snapshots from raw price history.",
            built_factors["snapshot_date"].nunique(),
            built_selections["snapshot_date"].nunique() if not built_selections.empty else 0,
        )

    investable_universe = define_investable_universe(cw1_inputs, config)
    selections = select_stocks(investable_universe, config)
    portfolio = build_portfolio(selections, config)
    baseline_frequency = config.get("project", {}).get("rebalance_frequency", "monthly")
    backtest_results = run_strategy_backtest(cw1_inputs, portfolio, config, baseline_frequency)
    benchmarks = build_benchmark_panel(
        cw1_inputs.price_history,
        investable_universe,
        config,
        baseline_frequency,
        snapshot_history=getattr(cw1_inputs, "historical_factors", pd.DataFrame()),
    )
    performance = evaluate_strategy(backtest_results.returns, benchmarks, config)
    robustness = run_robustness_checks(cw1_inputs, selections, config)
    if not robustness.empty and not performance.empty:
        strategy_row = performance[performance["series"] == "strategy"]
        if not strategy_row.empty:
            strategy_annual_return = float(strategy_row.iloc[0]["annual_return"])
            baseline_mask = robustness["is_baseline"].fillna(False)
            if baseline_mask.any() and "annual_return" in robustness.columns:
                robustness["matches_main_strategy"] = False
                robustness.loc[baseline_mask, "matches_main_strategy"] = (
                    (robustness.loc[baseline_mask, "annual_return"] - strategy_annual_return).abs() < 1e-12
                )
                logger.info(
                    "Baseline robustness row matches main strategy annual return: %s",
                    bool(robustness.loc[baseline_mask, "matches_main_strategy"].all()),
                )

    output_dir = write_outputs(
        config=config,
        universe=investable_universe,
        selections=selections,
        portfolio=portfolio,
        backtest_results=backtest_results,
        benchmarks=benchmarks,
        performance=performance,
        robustness=robustness,
        rebalance_frequency=baseline_frequency,
        factor_snapshots=getattr(cw1_inputs, "historical_factors", pd.DataFrame()),
        selection_snapshots=getattr(cw1_inputs, "historical_selections", pd.DataFrame()),
    )

    logger.info("CW2 pipeline complete. Outputs written to %s", output_dir)
    return 0
