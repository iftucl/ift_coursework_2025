import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from modules.db_loader import minio_db, mongodb, postgres

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_portfolio_performance(bucket_name: str = None):
    """
    Fetches daily portfolio performance metrics from the 'strategy_daily_stats.parquet' file in MinIO.

    Acts as a standardized accessor for strategy health data (e.g., net capital, daily returns), allowing for flexible bucket targeting across different backtest iterations.

    Args:
        bucket_name (str, optional): The MinIO bucket identifier.

    Returns:
        pd.DataFrame: Portfolio performance statistics or None if the object is not found.
    """

    load_kwargs = {"object_name": "performance/strategy_daily_stats.parquet"}
    if bucket_name:
        load_kwargs["bucket_name"] = bucket_name
    performance_df = minio_db.load_parquet(**load_kwargs)
    return performance_df


def get_portfolio_return(from_date: str, to_date: str, performance_df: pd.DataFrame):
    """
    Calculates cumulative point-to-point portfolio returns between two specific dates.

    Determines performance by comparing the 'net_capital' at the closest available timestamps within the provided range. Includes robust safety logic to handle chronological errors, missing historical baselines, and data gaps.

    Args:
        from_date (str): The starting date for return calculation (YYYY-MM-DD).
        to_date (str): The terminal date for return calculation (YYYY-MM-DD).
        performance_df (pd.DataFrame): Time-series containing 'date' and 'net_capital'.

    Returns:
        float: Rounded cumulative return (decimal). Returns np.nan if data is missing or dates are invalid.
    """

    from_dt = pd.to_datetime(from_date)
    to_dt = pd.to_datetime(to_date)
    if from_dt > to_dt:
        print(f"Error: from_date ({from_date}) is later than to_date ({to_date})")
        return np.nan

    if performance_df is None or performance_df.empty:
        print("No performance data available.")
        return np.nan

    performance_df["date"] = pd.to_datetime(performance_df["date"])
    performance_df = performance_df.sort_values("date")
    try:
        start_mask = performance_df["date"] <= from_dt
        end_mask = performance_df["date"] <= to_dt
        if not start_mask.any():
            print(
                f"Warning: No historical data exists before {from_date} to set a baseline."
            )
            return np.nan
        if not end_mask.any():
            print(f"Warning: No data exists before {to_date}.")
            return np.nan

        start_capital = performance_df.loc[start_mask, "net_capital"].iloc[-1]
        end_capital = performance_df.loc[end_mask, "net_capital"].iloc[-1]
        port_return = (end_capital / start_capital) - 1

        return round(float(port_return), 6)

    except Exception as e:
        print(f"Portfolio return calculation error: {e}")
        return np.nan


def get_portfolio_volatility(
    from_date: str, to_date: str, performance_df: pd.DataFrame
):
    """
    Computes the annualized realized volatility of portfolio returns for a specified date range.

    By prepending a baseline capital record, the function ensures the first daily return in the analysis period is calculated accurately via percentage change. The standard deviation of these returns is subsequently scaled by the square root of 252 trading days to provide a normalized annual risk metric.

    Args:
        from_date (str): The starting date for the observation period (YYYY-MM-DD).
        to_date (str): The terminal date for the observation period (YYYY-MM-DD).
        performance_df (pd.DataFrame): Time-series containing 'date' and 'net_capital'.

    Returns:
        float: Annualized volatility (decimal). Returns np.nan if insufficient data points exist or date ranges are invalid.
    """

    from_dt = pd.to_datetime(from_date)
    to_dt = pd.to_datetime(to_date)
    if from_dt > to_dt:
        print(f"Error: from_date ({from_date}) is later than to_date ({to_date})")
        return np.nan

    if performance_df is None or performance_df.empty:
        print("No performance data available.")
        return np.nan

    performance_df["date"] = pd.to_datetime(performance_df["date"])
    performance_df = performance_df.sort_values("date")

    try:
        baseline_row = performance_df[performance_df["date"] <= from_dt].tail(1)
        period_rows = performance_df[
            (performance_df["date"] > from_dt) & (performance_df["date"] <= to_dt)
        ]
        if period_rows.empty or baseline_row.empty:
            print("Insufficient data to calculate portfolio returns")
            return np.nan

        calc_df = pd.concat([baseline_row, period_rows])
        calc_df["daily_return"] = calc_df["net_capital"].pct_change()
        analysis_returns = calc_df.loc[
            calc_df["date"] > from_dt, "daily_return"
        ].dropna()
        if len(analysis_returns) < 2:
            print("Insufficient data to calculate portfolio volatility")
            return np.nan

        daily_std = analysis_returns.std()
        annualized_vol = daily_std * np.sqrt(252)
        return round(float(annualized_vol), 6)

    except Exception as e:
        print(f"Portfolio volatility calculation error: {e}")
        return np.nan


def get_benchmark_return(benchmark_symbol: str, from_date: str, to_date: str):
    """
    Calculates cumulative benchmark returns by retrieving historical OHLCV data from PostgreSQL.

    To ensure robust performance tracking across non-trading days, the function implements a 7-day look-back buffer to secure a valid baseline price. It determines the relative change between the final closing prices available prior to the 'from' and 'to' timestamps.

    Args:
        benchmark_symbol (str): The ticker symbol (e.g., 'SPY').
        from_date (str): Start date for the return calculation (YYYY-MM-DD).
        to_date (str): Terminal date for the return calculation (YYYY-MM-DD).

    Returns:
        float: Cumulative benchmark return (decimal). Returns np.nan if data is unavailable or chronological errors occur.
    """

    from_dt = pd.to_datetime(from_date)
    to_dt = pd.to_datetime(to_date)
    if from_dt > to_dt:
        print(f"Error: from_date ({from_date}) is later than to_date ({to_date})")
        return np.nan

    fetch_start = (from_dt - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    benchmark_data = postgres.get_ohlcv_data(
        [benchmark_symbol], start_date=fetch_start, end_date=to_date
    )
    if benchmark_data is None or benchmark_data.empty:
        print(f"No data available for {benchmark_symbol}.")
        return np.nan
    benchmark_data["price_date"] = pd.to_datetime(benchmark_data["price_date"])
    benchmark_data = benchmark_data.sort_values("price_date")

    try:
        start_mask = benchmark_data["price_date"] < from_dt
        end_mask = benchmark_data["price_date"] < to_dt
        if not start_mask.any() or not end_mask.any():
            print("Insufficient historical buffer to find prices before target dates.")
            return np.nan
        start_price = benchmark_data.loc[start_mask, "close_price"].iloc[-1]
        end_price = benchmark_data.loc[end_mask, "close_price"].iloc[-1]
        benchmark_return = (end_price / start_price) - 1

        return round(float(benchmark_return), 6)

    except Exception as e:
        print(f"Benchmark error for {benchmark_symbol}: {e}")
        return np.nan


def get_benchmark_volatility(benchmark_symbol: str, from_date: str, to_date: str):
    """
    Calculates the annualized realized volatility of a benchmark symbol using historical OHLCV data from PostgreSQL.

    The function establishes a valid price baseline via a 7-day look-back buffer to ensure accurate daily return calculations. It computes the standard deviation of returns for the observation period and annualizes the metric using the square root of 252 trading days.

    Args:
        benchmark_symbol (str): Ticker symbol for analysis (e.g., 'SPY').
        from_date (str): Start date for the observation period (YYYY-MM-DD).
        to_date (str): End date for the observation period (YYYY-MM-DD).

    Returns:
        float: Annualized volatility (decimal). Returns np.nan if data is insufficient or invalid.
    """

    from_dt = pd.to_datetime(from_date)
    to_dt = pd.to_datetime(to_date)
    if from_dt > to_dt:
        print(f"Error: from_date ({from_date}) is later than to_date ({to_date})")
        return np.nan

    fetch_start = (from_dt - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    benchmark_data = postgres.get_ohlcv_data(
        [benchmark_symbol], start_date=fetch_start, end_date=to_date
    )
    if benchmark_data is None or benchmark_data.empty:
        print(f"No data available for {benchmark_symbol}.")
        return np.nan
    benchmark_data["price_date"] = pd.to_datetime(benchmark_data["price_date"])
    benchmark_data = benchmark_data.sort_values("price_date")

    try:
        baseline_row = benchmark_data[benchmark_data["price_date"] <= from_dt].tail(1)
        period_rows = benchmark_data[
            (benchmark_data["price_date"] > from_dt)
            & (benchmark_data["price_date"] <= to_dt)
        ]
        if period_rows.empty or baseline_row.empty:
            print(f"Insufficient data to calculate {benchmark_symbol} returns")
            return np.nan

        calc_df = pd.concat([baseline_row, period_rows])
        calc_df["daily_return"] = calc_df["close_price"].pct_change()
        analysis_returns = calc_df.loc[
            calc_df["price_date"] > from_dt, "daily_return"
        ].dropna()
        if len(analysis_returns) < 2:
            print(f"Insufficient data to calculate {benchmark_symbol} volatility")
            return np.nan

        daily_std = analysis_returns.std()
        annualized_vol = daily_std * np.sqrt(252)
        return round(float(annualized_vol), 6)

    except Exception as e:
        print(f"Benchmark volatility calculation error: {e}")
        return np.nan


def generate_return_chart(
    bucket_name: str, start_date_str: str = None, end_date_str: str = None
):
    """
    Constructs a comparative performance and risk summary table across standardized financial time horizons.

    The function computes cumulative returns, annualized volatility, and excess return (Alpha) relative to a benchmark for periods ranging from 1 month to 5 years. It features a critical inception-guard logic that dynamically omits look-back periods pre-dating the portfolio's actual start date. The resulting DataFrame is transposed and reordered to provide a professional vertical summary with 'Total' performance as the terminal anchor.

    Args:
        bucket_name (str): The MinIO bucket containing strategy performance logs.
        start_date_str (str, optional): Overrides the baseline for the 'Total' period calculation (YYYY-MM-DD).
        end_date_str (str, optional): The anchor date for all look-back periods (YYYY-MM-DD). Defaults to the latest record.

    Returns:
        pd.DataFrame: A transposed summary of metrics per horizon. Returns an empty DataFrame if no data exists.
    """

    port_perform_df = load_portfolio_performance(bucket_name=bucket_name)
    if port_perform_df is None or port_perform_df.empty:
        print(f"No data for {bucket_name}")
        return pd.DataFrame()

    port_perform_df["date"] = pd.to_datetime(port_perform_df["date"])
    actual_start = port_perform_df["date"].min()
    actual_end = port_perform_df["date"].max()

    end_date = pd.to_datetime(end_date_str) if end_date_str else actual_end
    total_start = pd.to_datetime(start_date_str) if start_date_str else actual_start
    end_date_fmt = end_date.strftime("%Y-%m-%d")

    periods = {
        "1-month": end_date - pd.DateOffset(months=1),
        "3-months": end_date - pd.DateOffset(months=3),
        "6-months": end_date - pd.DateOffset(months=6),
        "1-year": end_date - pd.DateOffset(years=1),
        "2-years": end_date - pd.DateOffset(years=2),
        "3-years": end_date - pd.DateOffset(years=3),
        "5-years": end_date - pd.DateOffset(years=5),
        "Total": total_start,
    }

    benchmark_symbol = load_config()["portfolio"]["benchmark_symbol"]
    results = []
    for label, start_dt in periods.items():

        if label != "Total" and start_dt < actual_start:
            continue

        start_str = start_dt.strftime("%Y-%m-%d")

        try:
            p_ret = get_portfolio_return(start_str, end_date_fmt, port_perform_df)
            b_ret = get_benchmark_return(benchmark_symbol, start_str, end_date_fmt)
            p_vol = get_portfolio_volatility(start_str, end_date_fmt, port_perform_df)
            b_vol = get_benchmark_volatility(benchmark_symbol, start_str, end_date_fmt)

            results.append(
                {
                    "Period": label,
                    "Portfolio Return": p_ret,
                    "Portfolio Volatility": p_vol,
                    "Benchmark Return": b_ret,
                    "Benchmark Volatility": b_vol,
                    "Alpha": (
                        p_ret - b_ret
                        if (p_ret is not None and b_ret is not None)
                        else None
                    ),
                }
            )
        except Exception as e:
            print(f"Skipping period {label} for {bucket_name} due to error: {e}")

    if not results:
        return pd.DataFrame()

    summary_df = pd.DataFrame(results).set_index("Period").T

    cols = [c for c in summary_df.columns if c != "Total"] + ["Total"]
    summary_df = summary_df[cols]

    return summary_df


def get_sectors_total_return(
    portfolio_name: str, start_date: str = None, end_date: str = None
):
    """
    Calculates sector PnL and ROI adjusted for intra-period trades.

    Combines MinIO snapshots and MongoDB logs to capture realized gains from exited
    positions and net investment flows. Returns are capital-weighted to account
    for intra-period deployment.

    Args:
        portfolio_name (str): Portfolio ID.
        start_date (str, optional): Start YYYY-MM-DD. Defaults to inception.
        end_date (str, optional): End YYYY-MM-DD. Defaults to latest.

    Returns:
        pd.DataFrame: Sector-level PnL, flows, and capital-adjusted returns.
    """

    all_sectors = load_config()["portfolio"]["sectors"]
    sector_df = postgres.get_companies_by_sector(all_sectors)
    sector_map = sector_df.set_index("symbol")["gics_sector"].to_dict()

    if start_date is None:
        start_date = minio_db.get_initial_date(portfolio_name)
    if end_date is None:
        end_date = minio_db.get_latest_date(portfolio_name)

    v0_df = minio_db.load_parquet(
        f"holdings/{start_date}_holdings.parquet", portfolio_name
    )
    v0_df["sector"] = v0_df["symbol"].map(sector_map).fillna("Unknown")
    v0_stats = v0_df.groupby("sector")["current_value"].sum()

    v1_df = minio_db.load_parquet(
        f"holdings/{end_date}_holdings.parquet", portfolio_name
    )
    v1_df["sector"] = v1_df["symbol"].map(sector_map).fillna("Unknown")
    v1_stats = v1_df.groupby("sector")["current_value"].sum()

    collection = mongodb.get_collection(portfolio_name)
    trades_cursor = collection.find(
        {"portfolio_date": {"$gt": start_date, "$lte": end_date}, "status": "EXECUTED"}
    )

    cash_flows = []
    for doc in trades_cursor:
        for trade in doc["trades"]:
            symbol = trade["symbol"]
            sector = trade.get("gics_sector") or sector_map.get(symbol, "Unknown")
            cash_flows.append(
                {
                    "sector": sector,
                    "investment": trade.get("investment", 0) + trade.get("fees", 0),
                }
            )

    flow_df = pd.DataFrame(cash_flows)
    net_flows = (
        flow_df.groupby("sector")["investment"].sum()
        if not flow_df.empty
        else pd.Series()
    )

    results = pd.DataFrame(index=all_sectors)
    results["v0"] = v0_stats.reindex(results.index).fillna(0)
    results["v1"] = v1_stats.reindex(results.index).fillna(0)
    results["net_flow"] = net_flows.reindex(results.index).fillna(0)
    results["pnl"] = results["v1"] - results["v0"] - results["net_flow"]

    denominator = results["v0"] + results["net_flow"].clip(lower=0)
    results["return_pct"] = (results["pnl"] / denominator).fillna(0)

    return results.sort_values("return_pct", ascending=False)


def generate_return_graph(
    portfolio_list: list,
    start_date_str: str = None,
    end_date_str: str = None,
    include_benchmark: bool = False,
):
    """
    Plots indexed cumulative performance for multiple portfolios and an optional benchmark.

    Normalizes net capital to a base of 100 at the start date to enable relative growth comparison. Dynamically resolves global date boundaries across portfolios and saves the resulting chart as a PNG.

    Args:
        portfolio_list (list): List of portfolio identifiers to compare.
        start_date_str (str, optional): Plot start date. Defaults to earliest inception.
        end_date_str (str, optional): Plot end date. Defaults to latest record.
        include_benchmark (bool): If True, overlays indexed benchmark performance.

    Returns:
        None: Saves the visualization to the 'output/' directory.
    """

    plt.figure(figsize=(12, 6))
    portfolio_dfs = {}
    global_min_dt = None
    global_max_dt = None

    for bucket in portfolio_list:
        df = load_portfolio_performance(bucket)

        if df is None or df.empty:
            print(f"Skipping {bucket}: No data found.")
            continue

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")

        if global_min_dt is None or df["date"].min() < global_min_dt:
            global_min_dt = df["date"].min()
        if global_max_dt is None or df["date"].max() > global_max_dt:
            global_max_dt = df["date"].max()

        portfolio_dfs[bucket] = df

    if not portfolio_dfs:
        print("No valid portfolio data found to plot.")
        return

    start_dt = pd.to_datetime(start_date_str) if start_date_str else global_min_dt
    end_dt = pd.to_datetime(end_date_str) if end_date_str else global_max_dt

    final_start_str = start_dt.strftime("%Y-%m-%d")
    final_end_str = end_dt.strftime("%Y-%m-%d")

    for bucket, df in portfolio_dfs.items():

        mask = (df["date"] >= start_dt) & (df["date"] <= end_dt)
        filtered_df = df.loc[mask].copy()

        if filtered_df.empty:
            print(
                f"No data for {bucket} within the range {final_start_str} to {final_end_str}."
            )
            continue

        initial_val = filtered_df["net_capital"].iloc[0]
        filtered_df["indexed_performance"] = (
            filtered_df["net_capital"] / initial_val
        ) * 100

        plt.plot(
            filtered_df["date"],
            filtered_df["indexed_performance"],
            label=f"Bucket: {bucket}",
        )

    if include_benchmark:
        benchmark_symbol = load_config()["portfolio"]["benchmark_symbol"]
        bench_df = postgres.get_ohlcv_data(
            [benchmark_symbol], start_date=final_start_str, end_date=final_end_str
        )

        if not bench_df.empty:
            bench_df["price_date"] = pd.to_datetime(bench_df["price_date"])
            bench_df = bench_df.sort_values("price_date")

            b_initial = bench_df["close_price"].iloc[0]
            bench_df["indexed_bench"] = (bench_df["close_price"] / b_initial) * 100

            plt.plot(
                bench_df["price_date"],
                bench_df["indexed_bench"],
                label=f"Benchmark ({benchmark_symbol})",
                color="black",
                linestyle="--",
                linewidth=2,
                zorder=10,
            )

    plt.axhline(100, color="gray", linestyle=":", alpha=0.5)
    plt.title(f"Strategy Performance Comparison ({final_start_str} to {final_end_str})")
    plt.xlabel("Date")
    plt.ylabel("Indexed Performance (Base 100)")
    plt.legend(loc="upper left")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.tight_layout()

    png_path = f"output/comparison_{final_start_str}_to_{final_end_str}.png"
    plt.savefig(png_path)
    print(f"Saved graph to {png_path}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Analyse Portfolio Performance")

    parser.add_argument(
        "--portfolio_list",
        nargs="+",
        required=True,
        help="The portfolio name stroing in MongoDB and MinIO.",
    )

    parser.add_argument(
        "--start_date",
        type=str,
        help="The specific starting date to calculate performance (YYYY-MM-DD). Default to initial date",
    )

    parser.add_argument(
        "--end_date",
        type=str,
        help="The specific ending date to calculate performance (YYYY-MM-DD). Default to latest date.",
    )

    args = parser.parse_args()

    start_date = args.start_date
    end_date = args.end_date

    if start_date and end_date:
        file_date_name = f"{start_date}_to_{end_date}"
    elif start_date:
        file_date_name = f"{start_date}_to_latest"
    elif end_date:
        file_date_name = f"initial_to_{end_date}"
    else:
        file_date_name = "all_time"

    for portfolio in args.portfolio_list:
        try:
            summary_df = generate_return_chart(portfolio, start_date, end_date)
            summary_csv_path = f"output/{portfolio}_{file_date_name}_summary.csv"
            summary_df.to_csv(summary_csv_path)
            print(f"Saved summary to {summary_csv_path}")

            sectors_return_df = get_sectors_total_return(
                portfolio, start_date, end_date
            )
            sectors_return_csv_path = (
                f"output/{portfolio}_{file_date_name}_sectors_return.csv"
            )
            sectors_return_df.to_csv(sectors_return_csv_path)
            print(f"Saved sectors return to {sectors_return_csv_path}")

        except Exception as e:
            print(f"Failed to generate chart for {portfolio}: {e}")

    generate_return_graph(
        portfolio_list=args.portfolio_list,
        start_date_str=start_date,
        end_date_str=end_date,
        include_benchmark=True,
    )
