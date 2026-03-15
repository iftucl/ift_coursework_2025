import pandas as pd
import argparse
import time
import sys
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from a_pipeline.modules.db_loader import postgres, minio
from a_pipeline.modules.factors import calculate_factors
from a_pipeline.modules.url_parser import dolthub_pipeline, yf_pipeline


def wait_for_postgres():
    print("Checking database connection...")
    retries = 5
    while retries > 0:
        if postgres.check_connection():
            print("Database connected!")
            return True
        print(f"Waiting for database... ({retries} retries left)")
        time.sleep(5)
        retries -= 1
    raise ConnectionError("Could not connect to PostgreSQL container.")


def update_database():
    yf_pipeline.update_ohlcv_batch()
    yf_pipeline.update_factors()
    dolthub_pipeline.setup_dolt_database()


def fetch_factors(run_date: str):
    target_sectors = ["Consumer Staples", "Utilities", "Health Care"]
    target_companies = postgres.get_companies_by_sector(target_sectors)
    latest_indicators = calculate_factors.get_latest_indicators(
        list(target_companies["symbol"]), as_of_date=run_date
    )
    target_df = pd.merge(
        latest_indicators,
        target_companies[["symbol", "gics_sector"]],
        on="symbol",
        how="inner",
    )
    print(f"Total companies count: {len(target_df)}")
    return target_df


def apply_filter(target_df: pd.DataFrame):
    # 1. Liquidity Filter
    adv_cutoff = target_df["adv_20d"].quantile(0.15)
    addv_cutoff = target_df["addv_20d"].quantile(0.15)
    liquidity_mask = (target_df["adv_20d"] > adv_cutoff) & (
        target_df["addv_20d"] > addv_cutoff
    )
    df = target_df[liquidity_mask].copy()
    print(f"Liquidity mask count: {len(df)}")
    # 2. (Option A) Sequential Filter
    trend_mask = (df["close_price"] > df["ma200"]) & (df["ma200_20d_roc"] > 0)
    df = df[trend_mask].copy()
    print(f"Trend mask count: {len(df)}")
    earnings_mask = df["forward_earning_yields"] > 0
    df = df[earnings_mask].copy()
    print(f"Earnings mask count: {len(df)}")
    momentum_mask = df["momentum_score"] >= 0.4
    df = df[momentum_mask].copy()
    print(f"Momentum mask count: {len(df)}")
    # 3. Risk Filter
    risk_mask = (
        (df["vol_60d"] < 0.3) & (df["max_drawdown_1y"] > -0.5) & (df["var_pct"] < 0.15)
    )
    df = df[risk_mask].copy()
    print(f"Risk mask count: {len(df)}")
    return df


def main():
    parser = argparse.ArgumentParser(description="IFT Coursework Team Neyman")

    parser.add_argument(
        "--date",
        type=str,
        help="The specific date to run (YYYY-MM-DD). Defaults to yesterday.",
    )

    parser.add_argument(
        "--frequency",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="How much data to process (daily, weekly, or monthly)",
    )

    args = parser.parse_args()

    run_date = (
        args.date if args.date else (datetime.now() - timedelta(1)).strftime("%Y-%m-%d")
    )

    print(f"Starting {args.frequency} run for date: {run_date}")

    try:
        wait_for_postgres()
        update_database()
        raw_df = fetch_factors(run_date=run_date)
        if not raw_df.empty:
            filtered_df = apply_filter(target_df=raw_df)
            if not filtered_df.empty:
                filename = f"target_companies_{run_date}.parquet"
                minio.upload_dataframe_to_parquet(filtered_df, filename)
                print(f"SUCCESS: Results stored as {filename}")
            else:
                print("No companies passed the filters today.")
        else:
            print("No data found for the selected date/sectors.")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
