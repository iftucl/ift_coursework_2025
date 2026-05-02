"""Step 11: Visualisation and reporting.

Reads from backtest_returns, backtest_summary, and ic_weights tables and
produces 10 charts (PNG) and 4 summary tables (CSV) for the strategy
report.

Charts (per the PM flowchart):

Performance:
  1. Equity curve - portfolio vs benchmark cumulative return
  2. Drawdown over time
  3. Monthly excess return (green/red bars)
  4. Long/Short cumulative contribution

Factor Analysis:
  5. IC weight evolution (4 factors)
  6. Rolling 12-month Sharpe

Robustness:
  7. Parameter sensitivity (Sharpe + Alpha)
  8. Cost sensitivity cumulative returns (4 lines)
  9. Factor exclusion (Sharpe + Alpha)

Trading:
 10. Monthly turnover bars

Tables:
  - performance_summary.csv (baseline metrics)
  - cost_scenarios.csv
  - factor_exclusion.csv
  - parameter_sensitivity.csv
"""

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend - no display required
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from modules.db.db_connection import PostgresConnection  # noqa: E402

logger = logging.getLogger(__name__)
SCHEMA = "team_wittgenstein"

# Consistent style across all charts
plt.rcParams.update(
    {
        "figure.figsize": (10, 6),
        "figure.dpi": 100,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 11,
    }
)


# ---------------------------------------------------------------------------
# DB access helpers
# ---------------------------------------------------------------------------


def _fetch_returns(db: PostgresConnection, scenario_id: str) -> pd.DataFrame:
    """Fetch all monthly return rows for a scenario, ordered by date."""
    query = """
        SELECT rebalance_date, gross_return, net_return, long_return,
               short_return, benchmark_return, excess_return,
               cumulative_return, turnover, transaction_cost
        FROM team_wittgenstein.backtest_returns
        WHERE scenario_id = :scenario_id
        ORDER BY rebalance_date
    """
    df = db.read_query(query, {"scenario_id": scenario_id})
    if not df.empty:
        df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])
    return df


def _fetch_summary(db: PostgresConnection, like: str | None = None) -> pd.DataFrame:
    """Fetch backtest_summary rows. Optionally filter by scenario_id LIKE pattern."""
    if like:
        query = """
            SELECT * FROM team_wittgenstein.backtest_summary
            WHERE scenario_id LIKE :pat
            ORDER BY scenario_id
        """
        return db.read_query(query, {"pat": like})
    return db.read_query(
        "SELECT * FROM team_wittgenstein.backtest_summary ORDER BY scenario_id"
    )


def _fetch_ic_weights(db: PostgresConnection) -> pd.DataFrame:
    """Fetch all IC weight rows for the baseline run."""
    df = db.read_query("""
        SELECT rebalance_date, factor_name, ic_mean_36m, ic_weight
        FROM team_wittgenstein.ic_weights
        ORDER BY rebalance_date, factor_name
        """)
    if not df.empty:
        df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])
    return df


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Performance charts (4)
# ---------------------------------------------------------------------------


def plot_equity_curve(
    db: PostgresConnection, output_path: Path, scenario_id: str = "baseline"
) -> None:
    """Cumulative net return vs cumulative benchmark return."""
    df = _fetch_returns(db, scenario_id)
    if df.empty:
        logger.warning("No data for equity curve - skipping")
        return

    portfolio_cum = (1 + df["net_return"]).cumprod() - 1
    bench_cum = (1 + df["benchmark_return"]).cumprod() - 1

    fig, ax = plt.subplots()
    ax.plot(
        df["rebalance_date"],
        portfolio_cum * 100,
        label="Strategy",
        linewidth=2,
        color="#1f77b4",
    )
    ax.plot(
        df["rebalance_date"],
        bench_cum * 100,
        label="MSCI USA",
        linewidth=2,
        color="#ff7f0e",
        linestyle="--",
    )
    ax.set_title("Cumulative Return: Strategy vs Benchmark", fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Return (%)")
    ax.legend(loc="upper left")
    ax.axhline(y=0, color="gray", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


def plot_drawdown(
    db: PostgresConnection, output_path: Path, scenario_id: str = "baseline"
) -> None:
    """Drawdown from running peak over the backtest period."""
    df = _fetch_returns(db, scenario_id)
    if df.empty:
        logger.warning("No data for drawdown - skipping")
        return

    cum = (1 + df["net_return"]).cumprod()
    running_max = cum.cummax()
    drawdowns = (cum - running_max) / running_max * 100

    fig, ax = plt.subplots()
    ax.fill_between(
        df["rebalance_date"],
        drawdowns,
        0,
        color="#d62728",
        alpha=0.4,
    )
    ax.plot(df["rebalance_date"], drawdowns, color="#d62728", linewidth=1.5)
    ax.set_title("Strategy Drawdown", fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown (%)")
    ax.axhline(y=0, color="gray", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


def plot_monthly_excess(
    db: PostgresConnection, output_path: Path, scenario_id: str = "baseline"
) -> None:
    """Monthly excess return (net - benchmark), green for positive, red for negative."""
    df = _fetch_returns(db, scenario_id)
    if df.empty:
        logger.warning("No data for monthly excess - skipping")
        return

    excess = df["excess_return"] * 100
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in excess]

    fig, ax = plt.subplots()
    ax.bar(
        df["rebalance_date"],
        excess,
        color=colors,
        width=20,
        edgecolor="white",
        linewidth=0.5,
    )
    ax.set_title("Monthly Excess Return vs Benchmark", fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Excess Return (%)")
    ax.axhline(y=0, color="black", linewidth=0.7)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


def plot_long_short_contribution(
    db: PostgresConnection, output_path: Path, scenario_id: str = "baseline"
) -> None:
    """Cumulative contribution from long side vs short side."""
    df = _fetch_returns(db, scenario_id)
    if df.empty:
        logger.warning("No data for long/short contribution - skipping")
        return

    long_cum = df["long_return"].cumsum() * 100
    short_cum = df["short_return"].cumsum() * 100

    fig, ax = plt.subplots()
    ax.plot(
        df["rebalance_date"],
        long_cum,
        label="Long contribution",
        linewidth=2,
        color="#2ca02c",
    )
    ax.plot(
        df["rebalance_date"],
        short_cum,
        label="Short contribution",
        linewidth=2,
        color="#d62728",
    )
    ax.set_title("Cumulative Long vs Short Contribution", fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Contribution (%)")
    ax.legend(loc="upper left")
    ax.axhline(y=0, color="gray", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


# ---------------------------------------------------------------------------
# Factor Analysis charts (2)
# ---------------------------------------------------------------------------


def plot_ic_weights(db: PostgresConnection, output_path: Path) -> None:
    """One line per factor showing IC weight evolution over time."""
    df = _fetch_ic_weights(db)
    if df.empty:
        logger.warning("No IC weight data - skipping")
        return

    pivot = df.pivot(index="rebalance_date", columns="factor_name", values="ic_weight")

    fig, ax = plt.subplots()
    factor_colors = {
        "value": "#1f77b4",
        "quality": "#ff7f0e",
        "momentum": "#2ca02c",
        "low_vol": "#d62728",
    }
    for factor in pivot.columns:
        ax.plot(
            pivot.index,
            pivot[factor],
            label=factor.replace("_", " ").title(),
            linewidth=2,
            color=factor_colors.get(factor, "gray"),
        )
    ax.set_title("IC Weight Evolution by Factor", fontsize=13)
    ax.set_xlabel("Rebalance Date")
    ax.set_ylabel("IC Weight")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


def plot_rolling_sharpe(
    db: PostgresConnection,
    output_path: Path,
    scenario_id: str = "baseline",
    window: int = 12,
) -> None:
    """Rolling N-month annualised Sharpe ratio."""
    df = _fetch_returns(db, scenario_id)
    if df.empty or len(df) < window:
        logger.warning("Insufficient data for rolling sharpe - skipping")
        return

    net = df["net_return"]
    rolling_mean = net.rolling(window).mean() * 12
    rolling_std = net.rolling(window).std() * np.sqrt(12)
    rolling_sharpe = rolling_mean / rolling_std

    fig, ax = plt.subplots()
    ax.plot(df["rebalance_date"], rolling_sharpe, color="#1f77b4", linewidth=2)
    ax.set_title(f"Rolling {window}-Month Sharpe Ratio", fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Sharpe Ratio")
    ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")
    ax.axhline(y=1, color="green", linewidth=0.5, linestyle="--", alpha=0.5)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


# ---------------------------------------------------------------------------
# Robustness charts (3)
# ---------------------------------------------------------------------------


def plot_parameter_sensitivity(db: PostgresConnection, output_path: Path) -> None:
    """Grouped bar chart of Sharpe + Alpha across 15 sensitivity scenarios."""
    df = _fetch_summary(db, like="sens_%")
    if df.empty:
        logger.warning("No sensitivity scenarios - skipping")
        return

    df = df.sort_values("scenario_id")

    fig, ax1 = plt.subplots(figsize=(14, 7))
    x = np.arange(len(df))
    width = 0.4

    bars1 = ax1.bar(
        x - width / 2,
        df["sharpe_ratio"],
        width,
        label="Sharpe Ratio",
        color="#1f77b4",
    )
    ax1.set_ylabel("Sharpe Ratio", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.set_xticks(x)
    ax1.set_xticklabels(df["scenario_id"], rotation=60, ha="right", fontsize=9)
    ax1.axhline(y=0, color="gray", linewidth=0.5)

    ax2 = ax1.twinx()
    bars2 = ax2.bar(
        x + width / 2,
        df["alpha"] * 100,
        width,
        label="Alpha (%)",
        color="#ff7f0e",
    )
    ax2.set_ylabel("Alpha (%)", color="#ff7f0e")
    ax2.tick_params(axis="y", labelcolor="#ff7f0e")
    ax2.grid(False)

    ax1.set_title("Parameter Sensitivity: Sharpe Ratio and Alpha", fontsize=13)
    fig.legend(
        handles=[bars1, bars2],
        loc="upper right",
        bbox_to_anchor=(0.98, 0.95),
    )
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


def plot_cost_sensitivity(db: PostgresConnection, output_path: Path) -> None:
    """4 cumulative-return lines, one per cost scenario."""
    scenarios = [
        ("cost_frictionless", "Frictionless (0 bps)", "#2ca02c"),
        ("cost_low", "Low (10 bps)", "#1f77b4"),
        ("baseline", "Moderate (25 bps)", "#ff7f0e"),
        ("cost_high", "High (50 bps)", "#d62728"),
    ]

    fig, ax = plt.subplots()
    any_plotted = False
    for scenario_id, label, color in scenarios:
        df = _fetch_returns(db, scenario_id)
        if df.empty:
            continue
        cum = ((1 + df["net_return"]).cumprod() - 1) * 100
        ax.plot(
            df["rebalance_date"],
            cum,
            label=label,
            linewidth=2,
            color=color,
        )
        any_plotted = True

    if not any_plotted:
        plt.close(fig)
        logger.warning("No cost scenarios found - skipping")
        return

    ax.set_title("Transaction Cost Sensitivity: Cumulative Net Return", fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Return (%)")
    ax.legend(loc="upper left")
    ax.axhline(y=0, color="gray", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


def plot_factor_exclusion(db: PostgresConnection, output_path: Path) -> None:
    """Grouped bar of Sharpe + Alpha for baseline + 4 exclusion scenarios."""
    df = _fetch_summary(db)
    if df.empty:
        logger.warning("No summary data - skipping")
        return

    keep = df[
        (df["scenario_id"] == "baseline") | df["scenario_id"].str.startswith("excl_")
    ].copy()
    if keep.empty:
        logger.warning("No exclusion scenarios - skipping")
        return

    label_map = {
        "baseline": "Baseline (all 4)",
        "excl_value": "Excl. Value",
        "excl_quality": "Excl. Quality",
        "excl_momentum": "Excl. Momentum",
        "excl_low_vol": "Excl. Low Vol",
    }
    order = ["baseline", "excl_value", "excl_quality", "excl_momentum", "excl_low_vol"]
    keep = keep[keep["scenario_id"].isin(order)].copy()
    keep["sort_key"] = keep["scenario_id"].apply(lambda x: order.index(x))
    keep = keep.sort_values("sort_key")
    keep["label"] = keep["scenario_id"].map(label_map)

    x = np.arange(len(keep))
    width = 0.4

    fig, ax1 = plt.subplots()
    bars1 = ax1.bar(
        x - width / 2,
        keep["sharpe_ratio"],
        width,
        label="Sharpe Ratio",
        color="#1f77b4",
    )
    ax1.set_ylabel("Sharpe Ratio", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.set_xticks(x)
    ax1.set_xticklabels(keep["label"], rotation=20, ha="right")
    ax1.axhline(y=0, color="gray", linewidth=0.5)

    ax2 = ax1.twinx()
    bars2 = ax2.bar(
        x + width / 2,
        keep["alpha"] * 100,
        width,
        label="Alpha (%)",
        color="#ff7f0e",
    )
    ax2.set_ylabel("Alpha (%)", color="#ff7f0e")
    ax2.tick_params(axis="y", labelcolor="#ff7f0e")
    ax2.grid(False)

    ax1.set_title("Factor Exclusion: Sharpe Ratio and Alpha", fontsize=13)
    fig.legend(
        handles=[bars1, bars2],
        loc="upper right",
        bbox_to_anchor=(0.98, 0.95),
    )
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


# ---------------------------------------------------------------------------
# Trading chart (1)
# ---------------------------------------------------------------------------


def plot_monthly_turnover(
    db: PostgresConnection, output_path: Path, scenario_id: str = "baseline"
) -> None:
    """Bar chart of monthly turnover."""
    df = _fetch_returns(db, scenario_id)
    if df.empty:
        logger.warning("No data for turnover - skipping")
        return

    fig, ax = plt.subplots()
    ax.bar(
        df["rebalance_date"],
        df["turnover"] * 100,
        color="#1f77b4",
        width=20,
        edgecolor="white",
        linewidth=0.5,
    )
    avg = df["turnover"].mean() * 100
    ax.axhline(
        y=avg,
        color="#d62728",
        linewidth=1.5,
        linestyle="--",
        label=f"Mean = {avg:.1f}%",
    )
    ax.set_title("Monthly Portfolio Turnover", fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Turnover (%)")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    logger.info("Wrote %s", output_path)


# ---------------------------------------------------------------------------
# Tables (4)
# ---------------------------------------------------------------------------


def export_summary_table(
    db: PostgresConnection, output_path: Path, scenario_id: str = "baseline"
) -> None:
    """Headline performance metrics for one scenario, formatted for the report."""
    df = _fetch_summary(db)
    if df.empty:
        logger.warning("No summary rows - skipping")
        return
    row = df[df["scenario_id"] == scenario_id]
    if row.empty:
        logger.warning("No summary row for %s - skipping", scenario_id)
        return

    r = row.iloc[0]
    table = pd.DataFrame(
        [
            ("Annualised Return", f"{r['annualised_return'] * 100:.2f}%"),
            ("Cumulative Return", f"{r['cumulative_return'] * 100:.2f}%"),
            ("Annualised Volatility", f"{r['annualised_volatility'] * 100:.2f}%"),
            ("Sharpe Ratio", f"{r['sharpe_ratio']:.3f}"),
            ("Sortino Ratio", f"{r['sortino_ratio']:.3f}"),
            ("Calmar Ratio", f"{r['calmar_ratio']:.3f}"),
            ("Information Ratio", f"{r['information_ratio']:.3f}"),
            ("Max Drawdown", f"{r['max_drawdown'] * 100:.2f}%"),
            ("Tracking Error", f"{r['tracking_error'] * 100:.2f}%"),
            ("Alpha", f"{r['alpha'] * 100:.2f}%"),
            ("Benchmark Ann. Return", f"{r['benchmark_return_ann'] * 100:.2f}%"),
            ("Avg Monthly Turnover", f"{r['avg_monthly_turnover'] * 100:.2f}%"),
            ("Long Contribution", f"{r['long_contribution'] * 100:.2f}%"),
            ("Short Contribution", f"{r['short_contribution'] * 100:.2f}%"),
        ],
        columns=["Metric", "Value"],
    )
    table.to_csv(output_path, index=False)
    logger.info("Wrote %s", output_path)


def export_cost_table(db: PostgresConnection, output_path: Path) -> None:
    """4 cost scenarios x key metrics."""
    df = _fetch_summary(db)
    if df.empty:
        logger.warning("No cost scenarios - skipping")
        return
    keep = df[
        (df["scenario_id"] == "baseline") | df["scenario_id"].str.startswith("cost_")
    ].copy()
    if keep.empty:
        logger.warning("No cost scenarios - skipping")
        return

    order = ["cost_frictionless", "cost_low", "baseline", "cost_high"]
    label_map = {
        "cost_frictionless": "Frictionless (0 bps)",
        "cost_low": "Low (10 bps)",
        "baseline": "Moderate (25 bps)",
        "cost_high": "High (50 bps)",
    }
    keep = keep[keep["scenario_id"].isin(order)].copy()
    keep["sort_key"] = keep["scenario_id"].apply(lambda x: order.index(x))
    keep = keep.sort_values("sort_key")

    out = pd.DataFrame(
        {
            "Scenario": keep["scenario_id"].map(label_map).values,
            "Annualised Return (%)": (keep["annualised_return"] * 100).round(2).values,
            "Sharpe Ratio": keep["sharpe_ratio"].round(3).values,
            "Sortino Ratio": keep["sortino_ratio"].round(3).values,
            "Max Drawdown (%)": (keep["max_drawdown"] * 100).round(2).values,
            "Alpha (%)": (keep["alpha"] * 100).round(2).values,
            "Information Ratio": keep["information_ratio"].round(3).values,
        }
    )
    out.to_csv(output_path, index=False)
    logger.info("Wrote %s", output_path)


def export_factor_exclusion_table(db: PostgresConnection, output_path: Path) -> None:
    """Baseline + 4 factor exclusion scenarios x key metrics."""
    df = _fetch_summary(db)
    if df.empty:
        logger.warning("No exclusion scenarios - skipping")
        return
    order = ["baseline", "excl_value", "excl_quality", "excl_momentum", "excl_low_vol"]
    label_map = {
        "baseline": "Baseline (all 4)",
        "excl_value": "Excl. Value",
        "excl_quality": "Excl. Quality",
        "excl_momentum": "Excl. Momentum",
        "excl_low_vol": "Excl. Low Vol",
    }
    keep = df[df["scenario_id"].isin(order)].copy()
    if keep.empty:
        logger.warning("No exclusion scenarios - skipping")
        return
    keep["sort_key"] = keep["scenario_id"].apply(lambda x: order.index(x))
    keep = keep.sort_values("sort_key")

    out = pd.DataFrame(
        {
            "Scenario": keep["scenario_id"].map(label_map).values,
            "Annualised Return (%)": (keep["annualised_return"] * 100).round(2).values,
            "Sharpe Ratio": keep["sharpe_ratio"].round(3).values,
            "Sortino Ratio": keep["sortino_ratio"].round(3).values,
            "Max Drawdown (%)": (keep["max_drawdown"] * 100).round(2).values,
            "Alpha (%)": (keep["alpha"] * 100).round(2).values,
            "Information Ratio": keep["information_ratio"].round(3).values,
        }
    )
    out.to_csv(output_path, index=False)
    logger.info("Wrote %s", output_path)


def export_sensitivity_table(db: PostgresConnection, output_path: Path) -> None:
    """Baseline + 15 parameter sensitivity scenarios x key metrics."""
    df = _fetch_summary(db)
    if df.empty:
        logger.warning("No sensitivity scenarios - skipping")
        return
    keep = df[
        (df["scenario_id"] == "baseline") | df["scenario_id"].str.startswith("sens_")
    ].copy()
    if keep.empty:
        logger.warning("No sensitivity scenarios - skipping")
        return
    keep = keep.sort_values("scenario_id")

    out = pd.DataFrame(
        {
            "Scenario": keep["scenario_id"].values,
            "Annualised Return (%)": (keep["annualised_return"] * 100).round(2).values,
            "Sharpe Ratio": keep["sharpe_ratio"].round(3).values,
            "Sortino Ratio": keep["sortino_ratio"].round(3).values,
            "Max Drawdown (%)": (keep["max_drawdown"] * 100).round(2).values,
            "Alpha (%)": (keep["alpha"] * 100).round(2).values,
            "Information Ratio": keep["information_ratio"].round(3).values,
        }
    )
    out.to_csv(output_path, index=False)
    logger.info("Wrote %s", output_path)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_reporting(db: PostgresConnection, output_dir: str = "reports") -> None:
    """Generate all charts and tables for the strategy report."""
    base = Path(output_dir)
    charts_dir = base / "charts"
    tables_dir = base / "tables"
    _ensure_dir(charts_dir)
    _ensure_dir(tables_dir)

    logger.info("===== Step 11: Visualisation and reporting =====")

    # Performance
    plot_equity_curve(db, charts_dir / "01_equity_curve.png")
    plot_drawdown(db, charts_dir / "02_drawdown.png")
    plot_monthly_excess(db, charts_dir / "03_monthly_excess.png")
    plot_long_short_contribution(db, charts_dir / "04_long_short_contribution.png")

    # Factor analysis
    plot_ic_weights(db, charts_dir / "05_ic_weights.png")
    plot_rolling_sharpe(db, charts_dir / "06_rolling_sharpe.png")

    # Robustness
    plot_parameter_sensitivity(db, charts_dir / "07_parameter_sensitivity.png")
    plot_cost_sensitivity(db, charts_dir / "08_cost_sensitivity.png")
    plot_factor_exclusion(db, charts_dir / "09_factor_exclusion.png")

    # Trading
    plot_monthly_turnover(db, charts_dir / "10_monthly_turnover.png")

    # Tables
    export_summary_table(db, tables_dir / "performance_summary.csv")
    export_cost_table(db, tables_dir / "cost_scenarios.csv")
    export_factor_exclusion_table(db, tables_dir / "factor_exclusion.csv")
    export_sensitivity_table(db, tables_dir / "parameter_sensitivity.csv")

    logger.info("Reporting complete: outputs in %s", base.resolve())
