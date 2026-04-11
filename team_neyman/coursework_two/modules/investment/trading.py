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


def update_holdings(run_date: str, current_holdings_df=None):
    if current_holdings_df is None:
        current_holdings_df = minio_db.load_current_holdings()
    if current_holdings_df.empty:
        print(f"No holdings to update for {run_date}")
        return

    new_prices_data = postgres.get_ohlcv_data(
        current_holdings_df["symbol"], start_date=run_date, end_date=run_date
    )
    if not new_prices_data.empty:
        new_prices_data = new_prices_data.rename(columns={"close_price": "new_price"})
        new_prices_data = new_prices_data[["symbol", "new_price"]]
        current_holdings_df = pd.merge(
            current_holdings_df, new_prices_data, on="symbol", how="left"
        )
        current_holdings_df["current_price"] = current_holdings_df[
            "new_price"
        ].combine_first(current_holdings_df["current_price"])
        current_holdings_df = current_holdings_df.drop(columns=["new_price"])

    current_holdings_df["current_value"] = (
        current_holdings_df["current_price"] * current_holdings_df["current_shares"]
    )
    current_holdings_df["P&L"] = (
        current_holdings_df["current_value"] - current_holdings_df["total_investment"]
    )
    current_holdings_df["percentage_change"] = (
        current_holdings_df["current_price"] / current_holdings_df["avg_cost"]
    ) - 1

    holdings_file_path = f"holdings/{run_date}_holdings.parquet"
    minio_db.upload_dataframe_to_parquet(
        current_holdings_df, object_name=holdings_file_path
    )
    print(f"Daily holdings updated and saved for {run_date}")


def update_performace_data(
    run_date: str,
    performance_df=None,
    current_holdings_df=None,
    capital_add=0,
    cash_change=0,
):
    file_path = "performance/strategy_daily_stats.parquet"
    if performance_df is None:
        performance_df = minio_db.load_parquet(
            object_name=file_path,
        )
    if current_holdings_df is None:
        current_holdings_df = minio_db.load_current_holdings()

    if not performance_df.empty:
        last_capital = performance_df["initial_capital"].iloc[-1]
        last_cash = performance_df["cash"].iloc[-1]
    else:
        last_capital = load_config()["initial_capital"]
        last_cash = load_config()["initial_capital"]

    initial_capital = last_capital + capital_add
    investment_cost = current_holdings_df["total_investment"].sum()
    investment_value = current_holdings_df["current_value"].sum()
    cash = last_cash + cash_change
    net_capital = investment_value + cash
    pnl = net_capital - initial_capital
    pct_change = pnl / initial_capital if initial_capital != 0 else 0

    new_data = {
        "date": run_date,
        "initial_capital": initial_capital,
        "investment_cost": investment_cost,
        "investment_value": investment_value,
        "cash": cash,
        "net_capital": net_capital,
        "P&L": pnl,
        "percentage_change": pct_change,
    }
    performance_df = pd.concat(
        [performance_df, pd.DataFrame([new_data])], ignore_index=True
    )
    minio_db.upload_dataframe_to_parquet(performance_df, file_path)
    print(f"Performance updated for {run_date}.")


def execute_trade(fee_rate: float, execute_date: str):
    config = load_config()
    portfolio = mongodb.get_pending()

    if not portfolio:
        print("Nothing to execute today.")
        return

    # Initialize Dataframe and Columns
    trade_df = pd.DataFrame(portfolio["trades"])
    expected_cols = ["exec_price", "exec_shares", "investment", "fees"]
    for col in expected_cols:
        if col not in trade_df.columns:
            trade_df[col] = np.nan

    # Align Current Holdings
    current_holdings_df = minio_db.load_current_holdings()
    if current_holdings_df is None or current_holdings_df.empty:
        current_holdings_df = pd.DataFrame(
            columns=["symbol", "current_shares", "total_investment", "avg_cost"]
        )
        current_shares_df = pd.DataFrame(columns=["symbol", "current_shares"])
    else:
        current_shares_df = current_holdings_df[["symbol", "current_shares"]]

    trade_df = pd.merge(trade_df, current_shares_df, on="symbol", how="left")
    trade_df["current_shares"] = trade_df["current_shares"].fillna(0)

    # Get Capital for Rebalance
    performance_df = minio_db.load_parquet(
        object_name="performance/strategy_daily_stats.parquet",
    )
    capital = (
        performance_df["net_capital"].iloc[-1]
        if not performance_df.empty
        else config["initial_capital"]
    )

    # Fetch and Merge Prices
    new_prices_data = postgres.get_ohlcv_data(
        trade_df["symbol"].tolist(), start_date=execute_date, end_date=execute_date
    )
    if not new_prices_data.empty:
        new_prices_data = new_prices_data.rename(columns={"close_price": "new_price"})[
            ["symbol", "new_price"]
        ]
        trade_df = pd.merge(trade_df, new_prices_data, on="symbol", how="left")
        trade_df["exec_price"] = trade_df["exec_price"].combine_first(
            trade_df["new_price"]
        )

    # Execution Logic
    to_execute_mask = trade_df["exec_price"].notna() & trade_df["shares"].isna()
    target_shares = (
        (trade_df.loc[to_execute_mask, "weight"] * capital * (1 - fee_rate))
        / trade_df.loc[to_execute_mask, "exec_price"]
    ).round()
    trade_df.loc[to_execute_mask, "exec_shares"] = (
        target_shares - trade_df.loc[to_execute_mask, "current_shares"]
    )
    trade_df.loc[to_execute_mask, "investment"] = (
        trade_df["exec_shares"] * trade_df["exec_price"]
    )
    trade_df.loc[to_execute_mask, "fees"] = abs(trade_df["investment"]) * fee_rate

    # Update MongoDB Trading Info
    missing_symbols = trade_df.loc[trade_df["exec_price"].isna(), "symbol"].tolist()
    trade_info_df = trade_df.drop(columns=["new_price", "current_shares"])
    cash_flow = -(trade_df["investment"].sum() + trade_df["fees"].sum())

    portfolio.update(
        {
            "trades": trade_info_df.replace({np.nan: None}).to_dict("records"),
            "net_investment": trade_df["investment"].sum(),
            "total_flow": abs(trade_df["investment"]).sum(),
            "total_fee": trade_df["fees"].sum(),
            "status": "EXECUTED" if not missing_symbols else "PENDING",
        }
    )

    mongodb.update_trade_log(portfolio)
    mongodb.check_pending()

    # Update MinIO Holdings Snapshot and Perfomance
    holdings_change_df = trade_df.loc[
        trade_df["exec_shares"] != 0, ["symbol", "exec_shares", "exec_price", "fees"]
    ]
    updated_holdings = pd.merge(
        current_holdings_df, holdings_change_df, on="symbol", how="outer"
    ).fillna(0)
    updated_holdings["current_shares"] = (
        updated_holdings["current_shares"] + updated_holdings["exec_shares"]
    )

    is_buy = updated_holdings["exec_shares"] > 0
    updated_holdings.loc[is_buy, "total_investment"] += (
        updated_holdings["exec_shares"] * updated_holdings["exec_price"]
    ) + updated_holdings["fees"]

    is_sell = updated_holdings["exec_shares"] < 0
    updated_holdings.loc[is_sell, "total_investment"] = updated_holdings[
        "total_investment"
    ] * (
        updated_holdings["current_shares"]
        / (updated_holdings["current_shares"] + updated_holdings["exec_shares"])
    )

    updated_holdings["avg_cost"] = (
        updated_holdings["total_investment"] / updated_holdings["current_shares"]
    )
    updated_holdings = updated_holdings[
        updated_holdings["current_shares"] > 0.001
    ].drop(columns=["exec_shares", "exec_price", "fees"])

    update_holdings(execute_date, updated_holdings)
    update_performace_data(
        execute_date, performance_df, updated_holdings, cash_change=cash_flow
    )


def initiate_portfolio(init_date: str):
    config = load_config()
    fee_rate = config["transaction_fee"]

    minio_db.create_empty_parquet(
        object_name="performance/strategy_daily_stats.parquet",
        columns=[
            "date",
            "initial_capital",
            "investment_cost",
            "investment_value",
            "cash",
            "net_capital",
            "P&L",
            "percentage_change",
        ],
    )

    execute_trade(fee_rate, init_date)
    print("Sucessfully Initiate Portfolio.")


def rebalance(trade_date: str):
    config = load_config()
    fee_rate = config["transaction_fee"]
    execute_trade(fee_rate, trade_date)
    print("Sucessfully Rebalance Portfolio.")
