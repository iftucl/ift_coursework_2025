from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/cw2_mplconfig")

import matplotlib
import pandas as pd
from matplotlib.ticker import PercentFormatter

matplotlib.use("Agg")
import matplotlib.pyplot as plt


SCENARIO_PALETTE = {
    "monthly | 10 bps": "#4C78A8",
    "monthly | 20 bps": "#72B7B2",
    "monthly | 50 bps": "#2F4B7C",
    "quarterly | 10 bps": "#F58518",
    "quarterly | 20 bps": "#E45756",
    "quarterly | 50 bps": "#B279A2",
}


def build_cumulative_returns_panel(strategy_returns: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    merged = strategy_returns.merge(benchmarks, on="date", how="left")
    panel = merged[["date", "strategy_return"]].copy()
    panel["strategy"] = (1 + panel["strategy_return"].fillna(0)).cumprod() - 1

    for column in benchmarks.columns:
        if column == "date":
            continue
        series = pd.to_numeric(merged[column], errors="coerce").fillna(0.0)
        panel[column] = (1 + series).cumprod() - 1

    return panel.drop(columns=["strategy_return"])


def build_drawdown_panel(cumulative_returns: pd.DataFrame) -> pd.DataFrame:
    drawdowns = cumulative_returns.copy()
    for column in drawdowns.columns:
        if column == "date":
            continue
        equity = 1 + drawdowns[column].fillna(0)
        drawdowns[column] = equity / equity.cummax() - 1
    return drawdowns


def _plot_lines(df: pd.DataFrame, output_path: Path, title: str, ylabel: str) -> None:
    if df.empty:
        return

    plt.figure(figsize=(10, 6))
    for column in df.columns:
        if column == "date":
            continue
        if not df[column].dropna().any():
            continue
        plt.plot(df["date"], df[column], label=column)

    plt.title(title)
    plt.xlabel("Date")
    plt.ylabel(ylabel)
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150)
    plt.close()


def _ordered_robustness_methods(plot_df: pd.DataFrame) -> list[str]:
    preferred_method_order = ["equal_weight", "inverse_volatility", "rank_weighted"]
    available_methods = plot_df["weighting_method"].astype(str).tolist()
    available_methods = list(dict.fromkeys(available_methods))
    methods = [method for method in preferred_method_order if method in available_methods]
    methods.extend(method for method in available_methods if method not in methods)
    return methods


def write_robustness_return_chart(robustness: pd.DataFrame, output_dir: Path) -> None:
    required_columns = {
        "weighting_method",
        "rebalance_frequency",
        "annual_return",
        "max_drawdown",
    }
    if robustness.empty or not required_columns.issubset(robustness.columns):
        return

    plot_df = robustness.copy()
    for column in ["annual_return", "max_drawdown"]:
        plot_df[column] = pd.to_numeric(plot_df[column], errors="coerce")
    plot_df = plot_df.dropna(subset=["annual_return", "max_drawdown"], how="all")
    if plot_df.empty:
        return

    if "transaction_cost_bps" in plot_df.columns:
        plot_df["transaction_cost_bps"] = pd.to_numeric(plot_df["transaction_cost_bps"], errors="coerce")
        plot_df = (
            plot_df.groupby(["weighting_method", "rebalance_frequency", "transaction_cost_bps"], as_index=False)[
                ["annual_return", "max_drawdown"]
            ]
            .mean()
        )
        frequency_keys = [
            (str(row["rebalance_frequency"]), int(row["transaction_cost_bps"]))
            for _, row in plot_df[["rebalance_frequency", "transaction_cost_bps"]].drop_duplicates().iterrows()
        ]
    else:
        frequency_keys = [(freq, None) for freq in plot_df["rebalance_frequency"].astype(str).drop_duplicates().tolist()]

    methods = _ordered_robustness_methods(plot_df)
    x_positions = list(range(len(methods)))
    bar_width = 0.8 / max(len(frequency_keys), 1)

    figure, axes = plt.subplots(1, 2, figsize=(14, 6))
    metric_specs = [
        ("annual_return", "Annual Return"),
        ("max_drawdown", "Maximum Drawdown"),
    ]

    for axis, (metric_column, title) in zip(axes, metric_specs):
        for index, (frequency, cost_bps) in enumerate(frequency_keys):
            if cost_bps is None:
                frequency_slice = plot_df[plot_df["rebalance_frequency"] == frequency]
                label = frequency
            else:
                frequency_slice = plot_df[
                    (plot_df["rebalance_frequency"] == frequency)
                    & (plot_df["transaction_cost_bps"] == cost_bps)
                ]
                label = f"{frequency} | {cost_bps} bps"

            frequency_slice = frequency_slice.set_index("weighting_method").reindex(methods)
            offsets = [x + (index - (len(frequency_keys) - 1) / 2) * bar_width for x in x_positions]
            color = SCENARIO_PALETTE.get(label, "#8E8E8E")
            axis.bar(
                offsets,
                frequency_slice[metric_column],
                width=bar_width,
                label=label,
                color=color,
                edgecolor="white",
                linewidth=0.5,
            )

        axis.set_title(title, fontweight="bold")
        axis.set_xlabel("Weighting Method")
        axis.set_ylabel(metric_column.replace("_", " ").title())
        axis.set_xticks(x_positions)
        axis.set_xticklabels(methods)
        axis.axhline(0, color="black", linewidth=0.8)
        if metric_column == "max_drawdown":
            axis.yaxis.set_major_formatter(PercentFormatter(1.0))
        axis.grid(axis="y", alpha=0.3)

    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, title="scenario", loc="center left", bbox_to_anchor=(0.93, 0.5), borderaxespad=0.0)
    figure.suptitle("Annual Return and Maximum Drawdown by Weighting and Frequency", fontsize=14, fontweight="bold")
    figure.tight_layout(rect=(0.0, 0.0, 0.90, 0.95))
    output_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_dir / "return_comparison_chart.png", dpi=150, bbox_inches="tight")
    plt.close(figure)


def write_robustness_cost_chart(robustness: pd.DataFrame, output_dir: Path) -> None:
    required_columns = {
        "weighting_method",
        "rebalance_frequency",
        "average_turnover",
        "average_transaction_cost",
    }
    if robustness.empty or not required_columns.issubset(robustness.columns):
        return

    plot_df = robustness.copy()
    for column in ["average_turnover", "average_transaction_cost"]:
        plot_df[column] = pd.to_numeric(plot_df[column], errors="coerce")
    plot_df = plot_df.dropna(subset=["average_turnover", "average_transaction_cost"], how="all")
    if plot_df.empty:
        return

    if "transaction_cost_bps" in plot_df.columns:
        plot_df["transaction_cost_bps"] = pd.to_numeric(plot_df["transaction_cost_bps"], errors="coerce")
        plot_df = (
            plot_df.groupby(
                ["weighting_method", "rebalance_frequency", "transaction_cost_bps"],
                as_index=False,
            )[["average_turnover", "average_transaction_cost"]]
            .mean()
        )
        frequency_keys = [
            (str(row["rebalance_frequency"]), int(row["transaction_cost_bps"]))
            for _, row in plot_df[["rebalance_frequency", "transaction_cost_bps"]].drop_duplicates().iterrows()
        ]
    else:
        frequency_keys = [(freq, None) for freq in plot_df["rebalance_frequency"].astype(str).drop_duplicates().tolist()]

    methods = _ordered_robustness_methods(plot_df)
    x_positions = list(range(len(methods)))
    bar_width = 0.8 / max(len(frequency_keys), 1)

    figure, axes = plt.subplots(1, 2, figsize=(14, 6))
    metric_specs = [
        ("average_turnover", "Average Turnover"),
        ("average_transaction_cost", "Average Transaction Cost"),
    ]

    for axis, (metric_column, title) in zip(axes, metric_specs):
        for index, (frequency, cost_bps) in enumerate(frequency_keys):
            if cost_bps is None:
                frequency_slice = plot_df[plot_df["rebalance_frequency"] == frequency]
                label = frequency
            else:
                frequency_slice = plot_df[
                    (plot_df["rebalance_frequency"] == frequency)
                    & (plot_df["transaction_cost_bps"] == cost_bps)
                ]
                label = f"{frequency} | {cost_bps} bps"

            frequency_slice = frequency_slice.set_index("weighting_method").reindex(methods)
            offsets = [x + (index - (len(frequency_keys) - 1) / 2) * bar_width for x in x_positions]
            color = SCENARIO_PALETTE.get(label, "#8E8E8E")
            axis.bar(offsets, frequency_slice[metric_column], width=bar_width, label=label, color=color)

        axis.set_title(title)
        axis.set_xlabel("Weighting Method")
        axis.set_ylabel(metric_column.replace("_", " ").title())
        axis.set_xticks(x_positions)
        axis.set_xticklabels(methods)
        axis.grid(axis="y", alpha=0.3)

    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, title="scenario", loc="center left", bbox_to_anchor=(0.93, 0.5), borderaxespad=0.0)
    figure.suptitle("Average Turnover and Transaction Cost by Weighting and Frequency")
    figure.tight_layout(rect=(0.0, 0.0, 0.90, 0.95))
    output_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_dir / "cost_comparison_chart.png", dpi=150, bbox_inches="tight")
    plt.close(figure)


def write_sector_allocation_chart(sector_weights: pd.DataFrame, output_dir: Path) -> None:
    required_columns = {"sector", "total_weight"}
    if sector_weights.empty or not required_columns.issubset(sector_weights.columns):
        return

    plot_df = sector_weights.copy()
    plot_df["total_weight"] = pd.to_numeric(plot_df["total_weight"], errors="coerce")
    plot_df = plot_df.dropna(subset=["total_weight"])
    if plot_df.empty:
        return

    plt.figure(figsize=(10, 6))
    plt.bar(plot_df["sector"].astype(str), plot_df["total_weight"])
    plt.title("Baseline Portfolio Sector Allocation")
    plt.xlabel("Sector")
    plt.ylabel("Portfolio Weight")
    plt.xticks(rotation=30, ha="right")
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_dir / "sector_allocation_chart.png", dpi=150)
    plt.close()


def write_report_charts(
    strategy_returns: pd.DataFrame,
    benchmarks: pd.DataFrame,
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cumulative_returns = build_cumulative_returns_panel(strategy_returns, benchmarks)
    drawdowns = build_drawdown_panel(cumulative_returns)

    _plot_lines(
        cumulative_returns,
        output_dir / "cumulative_return_chart.png",
        title="Cumulative Returns: Strategy vs Benchmarks",
        ylabel="Cumulative Return",
    )
    _plot_lines(
        drawdowns,
        output_dir / "drawdown_chart.png",
        title="Drawdown: Strategy vs Benchmarks",
        ylabel="Drawdown",
    )

    return cumulative_returns, drawdowns


def write_methodology_note(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    note = """CW2 methodology note

CW2 treats CW1 as a frozen upstream data product.
It does not modify CW1, but it can consume both published CW1 outputs and the
historical raw price cache exposed by CW1.
When historical OHLCV price files are available, CW2 rebuilds monthly factor and
selection snapshots using the CW1 factor formulas, then runs a point-in-time
rolling rebalance backtest.
If only latest snapshots are available, CW2 falls back to a constrained fixed-portfolio
historical evaluation.
This allows the report to distinguish clearly between true rolling evaluation and
latest-snapshot fallback mode.
"""
    (output_dir / "methodology_note.txt").write_text(note, encoding="utf-8")
