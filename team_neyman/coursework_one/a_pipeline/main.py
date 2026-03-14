import pandas as pd
import argparse
from datetime import datetime, timedelta
from a_pipeline.modules.db_loader import postgres
from a_pipeline.modules.factors import calculate_factors
from a_pipeline.modules.url_parser import dolthub_pipeline, yf_pipeline


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
    target_df = target_df[liquidity_mask]
    print(f"Liquidity mask count: {len(target_df)}")
    # 2. (Option A) Sequential Filter
    trend_mask = (target_df["close_price"] > target_df["ma200"]) & (
        target_df["ma200_20d_roc"] > 0
    )
    target_df = target_df[trend_mask]
    print(f"Trend mask count: {len(target_df)}")
    earnings_mask = target_df["forward_earning_yields"] > 0
    target_df = target_df[earnings_mask]
    print(f"Earnings mask count: {len(target_df)}")
    momentum_mask = target_df["momentum_score"] >= 0.4
    target_df = target_df[momentum_mask]
    print(f"Momentum mask count: {len(target_df)}")
    # 3. Risk Filter
    risk_mask = (
        (target_df["vol_60d"] < 0.3)
        & (target_df["max_drawdown_1y"] > -0.5)
        & (target_df["var_pct"] < 0.15)
    )
    target_df = target_df[risk_mask]
    print(f"Risk mask count: {len(target_df)}")


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

    # Pass these parameters into your factor calculation functions
    # run_pipeline(date=run_date, freq=args.frequency)
    update_database()
    target_df = fetch_factors(run_date=run_date)
    apply_filter(target_df=target_df)


if __name__ == "__main__":
    main()
