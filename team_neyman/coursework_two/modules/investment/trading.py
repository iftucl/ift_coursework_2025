import numpy as np
import pandas as pd
import yaml
import sys
from pathlib import Path
from modules.factors import fetch_factors
from modules.db_loader import postgres, minio_db, mongodb

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["trading"]


def establish_portfolio(run_date: str):
    factors_df = fetch_factors.get_target_factors(run_date)
    filtered_df = fetch_factors.apply_filter(factors_df)
    final_df = fetch_factors.apply_scoring(filtered_df)

    # Adjusted for the actual weight calculation
    total_score_sum = final_df["total_score"].sum()
    if total_score_sum != 0:
        final_df["weight"] = final_df["total_score"] / total_score_sum
    else:
        final_df["weight"] = 0

    score_cols = [
        "total_score",
        "momentum_score",
        "fey_score",
        "trend_score",
        "risk_score",
    ]
    mongo_documents = final_df.apply(
        lambda x: {
            "symbol": x["symbol"],
            "gics_sector": x["gics_sector"],
            "scores": x[score_cols].to_dict(),
            "weight": x["weight"],
        },
        axis=1,
    ).tolist()

    mongodb.save_trade_log(run_date, mongo_documents)


def execute_trade(capital: float, fee_rate: float):
    portfolio = mongodb.get_pending()
    if not portfolio:
        print("Nothing to execute today.")
        return

    trade_df = pd.DataFrame(portfolio["trades"])
    expected_cols = ["exec_price", "shares", "investment", "fees"]
    for col in expected_cols:
        if col not in trade_df.columns:
            trade_df[col] = np.nan

    symbols_to_fetch = trade_df.loc[trade_df["exec_price"].isna(), "symbol"].tolist()
    execute_price_df = postgres.get_ohlcv_data(
        symbols_to_fetch, start_date=portfolio["portfolio_date"]
    )
    new_prices = (
        execute_price_df[
            pd.to_datetime(execute_price_df["price_date"])
            > pd.to_datetime(portfolio["portfolio_date"])
        ]
        .sort_values("price_date")
        .groupby("symbol")
        .head(1)
    )[["symbol", "close_price"]]
    new_prices = new_prices.rename(columns={"close_price": "new_price"})
    trade_df = pd.merge(trade_df, new_prices, on="symbol", how="left")
    trade_df["exec_price"] = trade_df["exec_price"].combine_first(trade_df["new_price"])
    trade_df = trade_df.drop(columns=["new_price"])

    to_execute_mask = trade_df["exec_price"].notna() & trade_df["shares"].isna()
    trade_df.loc[to_execute_mask, "shares"] = (
        (trade_df.loc[to_execute_mask, "weight"] * capital * (1 - fee_rate))
        / trade_df.loc[to_execute_mask, "exec_price"]
    ).round()
    trade_df.loc[to_execute_mask, "investment"] = (
        trade_df["shares"] * trade_df["exec_price"]
    )
    trade_df.loc[to_execute_mask, "fees"] = trade_df["investment"] * fee_rate

    missing_symbols = trade_df.loc[trade_df["exec_price"].isna(), "symbol"].tolist()

    portfolio["trades"] = trade_df.replace({np.nan: None}).to_dict("records")
    portfolio["total_investment"] = trade_df["investment"].sum()
    portfolio["total_fee"] = trade_df["fees"].sum()
    portfolio["net_capital"] = capital - portfolio["total_fee"]
    portfolio["cash"] = portfolio["net_capital"] - portfolio["total_investment"]
    if not missing_symbols:
        portfolio["status"] = "EXECUTED"
        print("Full execution complete.")
    else:
        portfolio["status"] = "PENDING"
        print(f"Partial execution. Still waiting for: {missing_symbols}")

    mongodb.update_trade_log(portfolio)
    mongodb.check_pending()

    # (Unfinished) Saving to MinIO
    minio_file_path = ""
    minio_db.upload_dataframe_to_parquet(
        trade_df, bucket_name="portfolio", object_name=minio_file_path
    )


def initiate_portfolio():
    config = load_config()
    capital = config["initial_capital"]
    fee_rate = config["transaction_fee"]
    execute_trade(capital, fee_rate)


def rebalance():
    return
