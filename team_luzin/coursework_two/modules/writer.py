from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.metrics import (
    build_benchmark_comparison_summary,
    build_portfolio_diagnostics,
    build_return_series_panel,
    build_rolling_metrics_panel,
    build_sector_exposure_summary,
)
from modules.reporting import (
    write_methodology_note,
    write_report_charts,
    write_robustness_cost_chart,
    write_robustness_return_chart,
    write_sector_allocation_chart,
)


def _write_table(df: pd.DataFrame, output_dir: Path, file_stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / f"{file_stem}.csv", index=False)
    try:
        df.to_parquet(output_dir / f"{file_stem}.parquet", index=False)
    except Exception:
        pass


def write_outputs(
    config: dict,
    universe: pd.DataFrame,
    selections: pd.DataFrame,
    portfolio: pd.DataFrame,
    backtest_results,
    benchmarks: pd.DataFrame,
    performance: pd.DataFrame,
    robustness: pd.DataFrame,
    rebalance_frequency: str | None = None,
    factor_snapshots: pd.DataFrame | None = None,
    selection_snapshots: pd.DataFrame | None = None,
) -> Path:
    output_dir = Path(config["paths"]["output_dir"])
    benchmark_status = pd.DataFrame([config.get("_runtime", {}).get("sp500_status", {})])

    _write_table(universe, output_dir / "universe", "investable_universe")
    _write_table(selections, output_dir / "selection", "selected_stocks")
    _write_table(portfolio, output_dir / "portfolio", "baseline_portfolio")
    _write_table(backtest_results.returns, output_dir / "backtest", "strategy_returns")
    _write_table(backtest_results.returns, output_dir / "backtest", "monthly_returns")
    _write_table(backtest_results.equity_curve, output_dir / "backtest", "equity_curve")
    if not backtest_results.holdings_history.empty:
        _write_table(backtest_results.holdings_history, output_dir / "backtest", "rebalance_holdings")
    _write_table(
        pd.DataFrame([{"backtest_mode": backtest_results.backtest_mode}]),
        output_dir / "backtest",
        "backtest_mode_summary",
    )
    _write_table(benchmarks, output_dir / "benchmark", "benchmark_returns")
    _write_table(performance, output_dir / "performance", "performance_table")
    _write_table(performance, output_dir / "performance", "absolute_performance_summary")
    if factor_snapshots is not None and not factor_snapshots.empty:
        _write_table(factor_snapshots, output_dir / "snapshots", "monthly_factor_snapshots")
    if selection_snapshots is not None and not selection_snapshots.empty:
        _write_table(selection_snapshots, output_dir / "snapshots", "monthly_selection_snapshots")

    holdings_for_diagnostics = backtest_results.holdings if not backtest_results.holdings.empty else portfolio
    sector_exposure_summary = build_sector_exposure_summary(holdings_for_diagnostics)
    portfolio_diagnostics = build_portfolio_diagnostics(holdings_for_diagnostics, backtest_results.returns)
    return_series_panel = build_return_series_panel(backtest_results.returns, benchmarks)
    rolling_metrics = build_rolling_metrics_panel(backtest_results.returns, window=12)

    if not sector_exposure_summary.empty:
        _write_table(sector_exposure_summary, output_dir / "backtest", "sector_exposure_summary")
        sector_weight_breakdown = sector_exposure_summary.rename(columns={"sector_weight": "total_weight"})
        _write_table(sector_weight_breakdown, output_dir / "portfolio", "sector_weight_breakdown")
        write_sector_allocation_chart(sector_weight_breakdown, output_dir / "portfolio")
    if not portfolio_diagnostics.empty:
        _write_table(portfolio_diagnostics, output_dir / "backtest", "portfolio_diagnostics")
    if not return_series_panel.empty:
        _write_table(return_series_panel, output_dir / "backtest", "return_series_panel")
    if not rolling_metrics.empty:
        _write_table(rolling_metrics, output_dir / "backtest", "rolling_metrics")

    benchmark_comparison = build_benchmark_comparison_summary(
        backtest_results.returns,
        benchmarks,
        config,
    )
    _write_table(benchmark_comparison, output_dir / "performance", "benchmark_comparison_summary")
    if not benchmark_status.empty and benchmark_status.shape[1] > 0:
        _write_table(benchmark_status, output_dir / "performance", "benchmark_source_summary")

    cumulative_returns, drawdowns = write_report_charts(
        backtest_results.returns,
        benchmarks,
        output_dir / "reporting",
    )
    _write_table(cumulative_returns, output_dir / "reporting", "cumulative_returns")
    _write_table(drawdowns, output_dir / "reporting", "drawdowns")
    write_methodology_note(output_dir / "reporting")

    if not robustness.empty:
        _write_table(robustness, output_dir / "robustness", "weighting_comparison")
        write_robustness_return_chart(robustness, output_dir / "robustness")
        write_robustness_cost_chart(robustness, output_dir / "robustness")

    return output_dir
