import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from functools import reduce

import pandas as pd

from modules.db_loader import postgres

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))


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


def calculate_ntm_eps(data: pd.DataFrame):
    """Calculate next twelve months earning per share (EPS) base on consensus prediction"""
    if data is not None and not data.empty:
        eps_pivot = data.pivot(
            index="symbol",
            columns="period",
            values=["period_end_date", "consensus_eps"],
        )

        eps_pivot.columns = [
            f"{col[1].lower().replace(' ', '_')}_{col[0]}" for col in eps_pivot.columns
        ]
        eps_pivot.reset_index(inplace=True)

        required_cols = [
            "current_year_period_end_date",
            "current_year_consensus_eps",
            "next_year_consensus_eps",
        ]
        for col in required_cols:
            if col not in eps_pivot.columns:
                eps_pivot[col] = pd.NA

        eps_pivot["current_year_period_end_date"] = pd.to_datetime(
            eps_pivot["current_year_period_end_date"]
        )
        today = pd.Timestamp.today().normalize()

        days_left_fy1 = (eps_pivot["current_year_period_end_date"] - today).dt.days
        days_left_fy1 = days_left_fy1.clip(lower=0, upper=365)

        weight_fy1 = days_left_fy1 / 365.0
        weight_fy2 = 1.0 - weight_fy1

        eps_pivot["current_year_consensus_eps"] = pd.to_numeric(
            eps_pivot["current_year_consensus_eps"], errors="coerce"
        )
        eps_pivot["next_year_consensus_eps"] = pd.to_numeric(
            eps_pivot["next_year_consensus_eps"], errors="coerce"
        )

        eps_pivot["ntm_eps"] = (
            (eps_pivot["current_year_consensus_eps"] * weight_fy1)
            + (eps_pivot["next_year_consensus_eps"] * weight_fy2)
        ).round(2)

        return eps_pivot[["symbol", "ntm_eps"]]
    else:
        return pd.DataFrame(columns=["symbol", "ntm_eps"])


def get_latest_indicators(symbols: list, as_of_date: str):
    """
    Fetch the latest target indicators used for trading stretagies to form a portfolio.
    Process raw data with symbol as the key into an intergrated dataframe.
    Calculate and add new columns for strategies execution.
    """
    latest_ohlcv = postgres.get_latest_data(
        "daily_ohlcv", columns=["close_price"], symbols=symbols, as_of_date=as_of_date
    )
    latest_liquidity = postgres.get_latest_data(
        "liquidity_factors",
        columns=["adv_20d", "addv_20d"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_trend = postgres.get_latest_data(
        "trend_factors",
        columns=["ma200", "ma200_20d_roc"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_momentum = postgres.get_latest_data(
        "momentum_factors",
        columns=["risk_adj_mom_12m", "positive_ret_pct_60d"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_risk = postgres.get_latest_data(
        "risk_factors",
        columns=["vol_60d", "max_drawdown_1y", "historical_var_95_1m"],
        symbols=symbols,
        as_of_date=as_of_date,
    )

    latest_eps_estimate = postgres.get_latest_data(
        "eps_estimate",
        columns=["period", "period_end_date", "consensus_eps"],
        date_col="estimate_date",
        distinct_cols=["symbol", "period"],
        periods=["Current Year", "Next Year"],
        symbols=symbols,
        as_of_date=as_of_date,
    )
    latest_ntm_eps = calculate_ntm_eps(latest_eps_estimate)

    # Put the factor tables in a list so we can loop through them
    factor_dfs = [latest_liquidity, latest_trend, latest_momentum, latest_risk]

    # Drop the redundant 'price_date' columns from the factor tables
    for df in factor_dfs:
        if df is not None and not df.empty and "price_date" in df.columns:
            df.drop(columns=["price_date"], inplace=True)

    # Compile the final list of DataFrames to merge
    all_dfs = [latest_ohlcv] + factor_dfs + [latest_ntm_eps]

    # Filter out any None or empty DataFrames just in case a database table is completely empty
    valid_dfs = [df for df in all_dfs if df is not None and not df.empty]
    if not valid_dfs:
        print("Error: No data retrieved from any tables.")
        return pd.DataFrame()

    # Merge everything on 'symbol' using a LEFT JOIN
    # This keeps every symbol in OHLCV, and attaches factors if they exist.
    final_merged_df = reduce(
        lambda left, right: pd.merge(left, right, on="symbol", how="left"), valid_dfs
    )
    print(f"Successfully merged indicators for {len(final_merged_df)} symbols.")

    final_merged_df["price_above_ma200"] = (
        final_merged_df["close_price"] > final_merged_df["ma200"]
    )
    final_merged_df["forward_earning_yields"] = (
        final_merged_df["ntm_eps"] / final_merged_df["close_price"]
    )
    final_merged_df["var_pct"] = final_merged_df["historical_var_95_1m"] / 10000

    return final_merged_df


def get_target_factors(run_date: str):
    target_sectors = ["Consumer Staples", "Utilities", "Health Care"]
    target_companies = postgres.get_companies_by_sector(target_sectors)
    latest_indicators = get_latest_indicators(
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


def apply_filter(df: pd.DataFrame):
    # 1. Liquidity Filter
    adv_cutoff = df["adv_20d"].quantile(0.15)
    addv_cutoff = df["addv_20d"].quantile(0.15)
    liquidity_mask = (df["adv_20d"] > adv_cutoff) & (df["addv_20d"] > addv_cutoff)
    df = df[liquidity_mask].copy()
    print(f"Liquidity mask count: {len(df)}")

    # 2. Trend Filter
    trend_mask = df["close_price"] > df["ma200"]
    df = df[trend_mask].copy()
    print(f"Trend mask count: {len(df)}")

    return df


def apply_scoring(df: pd.DataFrame):
    df["rar_rank"] = df["risk_adj_mom_12m"].rank(
        ascending=True, pct=True, na_option="keep"
    )
    df["stability_rank"] = df["positive_ret_pct_60d"].rank(
        ascending=True, pct=True, na_option="keep"
    )
    df["momentum_score"] = 0.7 * df["rar_rank"] + 0.3 * df["stability_rank"]

    df["fey_score"] = df["forward_earning_yields"].rank(
        ascending=True, pct=True, na_option="top"
    )

    df["trend_score"] = df["ma200_20d_roc"].rank(
        ascending=True, pct=True, na_option="keep"
    )

    df["vol_rank"] = df["vol_60d"].rank(ascending=False, pct=True, na_option="keep")
    df["mdd_rank"] = df["max_drawdown_1y"].rank(
        ascending=False, pct=True, na_option="keep"
    )
    df["var_rank"] = df["var_pct"].rank(ascending=False, pct=True, na_option="keep")
    df["risk_score"] = (df["vol_rank"] + df["mdd_rank"] + df["var_rank"]) / 3

    df["total_score"] = (
        df["momentum_score"] + df["fey_score"] + df["trend_score"] + df["risk_score"]
    )

    return df
