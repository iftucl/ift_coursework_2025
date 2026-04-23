import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import yaml

from pathlib import Path
from datetime import datetime
from modules.db_loader import minio_db, mongodb, postgres


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_portfolio_perforamance(bucket_name: str = None):
    load_kwargs = {"object_name": "performance/strategy_daily_stats.parquet"}
    if bucket_name:
        load_kwargs["bucket_name"] = bucket_name
    performance_df = minio_db.load_parquet(**load_kwargs)
    return performance_df


def get_portfolio_return(from_date: str, to_date: str, performance_df: pd.DataFrame):
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
            print(f"Insufficient historical buffer to find prices before target dates.")
            return np.nan
        start_price = benchmark_data.loc[start_mask, "close_price"].iloc[-1]
        end_price = benchmark_data.loc[end_mask, "close_price"].iloc[-1]
        benchmark_return = (end_price / start_price) - 1

        return round(float(benchmark_return), 6)

    except Exception as e:
        print(f"Benchmark error for {benchmark_symbol}: {e}")
        return np.nan


def get_benchmark_volatility(benchmark_symbol: str, from_date: str, to_date: str):
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


def generate_return_chart():
    port_perform_df = load_portfolio_perforamance(bucket_name="backtest")

    base_date = datetime.now()
    base_date_str = base_date.strftime("%Y-%m-%d")
    periods = {
        "1-month": base_date - pd.DateOffset(months=1),
        "3-months": base_date - pd.DateOffset(months=3),
        "6-months": base_date - pd.DateOffset(months=6),
        "1-year": base_date - pd.DateOffset(years=1),
        "2-years": base_date - pd.DateOffset(years=2),
        "3-years": base_date - pd.DateOffset(years=3),
        "5-years": base_date - pd.DateOffset(years=5),
        "Total": pd.to_datetime(port_perform_df["date"]).min(),
    }

    benchmark_symbol = "^892400-USD-STRD"
    results = []
    for label, start_dt in periods.items():
        start_str = start_dt.strftime("%Y-%m-%d")

        p_ret = get_portfolio_return(start_str, base_date_str, port_perform_df)
        b_ret = get_benchmark_return(benchmark_symbol, start_str, base_date_str)
        p_vol = get_portfolio_volatility(start_str, base_date_str, port_perform_df)
        b_vol = get_benchmark_volatility(benchmark_symbol, start_str, base_date_str)

        results.append(
            {
                "Period": label,
                "Portfolio Return": p_ret,
                "Portfolio Volatility": p_vol,
                "Benchmark Return": b_ret,
                "Benchmark Volatility": b_vol,
                "Alpha": p_ret - b_ret,
            }
        )

    summary_df = pd.DataFrame(results).set_index("Period").T

    cols = [c for c in summary_df.columns if c != "Total"] + ["Total"]
    summary_df = summary_df[cols]

    return summary_df


if __name__ == "__main__":
    summary_df = generate_return_chart()
    summary_df.to_csv("output/summary.csv")
