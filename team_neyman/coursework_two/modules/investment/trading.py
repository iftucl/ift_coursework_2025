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


def establish_portfolio(run_date: str, collection_name: str = None):
    factors_df = fetch_factors.get_target_factors(run_date)
    filtered_df = fetch_factors.apply_filter(factors_df)
    scored_df = fetch_factors.apply_scoring(filtered_df)
    final_df = fetch_factors.apply_weight(scored_df)

    score_cols = [
        "total_score",
        "momentum_score",
        "fey_score",
        "trend_score",
        "risk_score",
        "liquidity_score",
    ]

    currency_df = postgres.get_currency(final_df["symbol"].to_list())
    final_df = pd.merge(final_df, currency_df, on="symbol", how="left")
    final_df["currency"] = final_df["currency"].fillna("USD")

    mongo_documents = final_df.apply(
        lambda x: {
            "symbol": x["symbol"],
            "gics_sector": x["gics_sector"],
            "currency": x["currency"],
            "scores": x[score_cols].to_dict(),
            "weight": x["weight"],
        },
        axis=1,
    ).tolist()

    mongodb.save_trade_log(run_date, mongo_documents, collection_name)
    print(f"Portfolio established and logged for {run_date}")


def update_holdings(
    run_date: str, current_holdings_df: pd.DataFrame = None, bucket_name: str = None
):
    if current_holdings_df is None or current_holdings_df.empty:
        current_holdings_df = minio_db.load_current_holdings(bucket_name=bucket_name)

    if current_holdings_df is None or current_holdings_df.empty:
        print(f"No holdings to update for {run_date}")
        return

    for col in ["current_price", "fx_rate"]:
        if col not in current_holdings_df.columns:
            current_holdings_df[col] = np.nan

    new_prices_data = postgres.get_ohlcv_data(
        current_holdings_df["symbol"].tolist(), start_date=run_date, end_date=run_date
    )
    if new_prices_data is not None and not new_prices_data.empty:
        new_prices_data = new_prices_data.rename(columns={"close_price": "new_price"})
        new_prices_data = new_prices_data[["symbol", "new_price"]]
        current_holdings_df = pd.merge(
            current_holdings_df, new_prices_data, on="symbol", how="left"
        )
        current_holdings_df["current_price"] = current_holdings_df[
            "new_price"
        ].combine_first(current_holdings_df["current_price"])
        current_holdings_df = current_holdings_df.drop(columns=["new_price"])

    new_fx_data = postgres.get_fx_data(start_date=run_date, end_date=run_date)
    if new_fx_data is not None and not new_fx_data.empty:
        new_fx_data = new_fx_data.rename(
            columns={"USD_to": "currency", "close_price": "new_fx_rate"}
        )[["currency", "new_fx_rate"]]
        current_holdings_df = pd.merge(
            current_holdings_df, new_fx_data, on="currency", how="left"
        )
        current_holdings_df.loc[
            current_holdings_df["currency"] == "USD", "new_fx_rate"
        ] = 1.0
        gbp_lookup = new_fx_data.loc[
            new_fx_data["currency"] == "GBP", "new_fx_rate"
        ].iloc[0]
        if not gbp_lookup.empty:
            current_holdings_df.loc[
                current_holdings_df["currency"] == "GBp", "new_fx_rate"
            ] = (gbp_lookup * 100)
        current_holdings_df["fx_rate"] = current_holdings_df[
            "new_fx_rate"
        ].combine_first(current_holdings_df["fx_rate"])
        current_holdings_df = current_holdings_df.drop(columns=["new_fx_rate"])
    current_holdings_df["fx_rate"] = current_holdings_df["fx_rate"].fillna(1.0)

    current_holdings_df["current_value"] = (
        (current_holdings_df["current_price"] / current_holdings_df["fx_rate"])
        * current_holdings_df["current_shares"]
    ).round(4)
    current_holdings_df["P&L"] = (
        current_holdings_df["current_value"] - current_holdings_df["total_investment"]
    ).round(4)
    current_holdings_df["percentage_change"] = (
        (current_holdings_df["current_price"] / current_holdings_df["fx_rate"])
        / current_holdings_df["avg_cost"]
    ).round(6) - 1

    holdings_file_path = f"holdings/{run_date}_holdings.parquet"
    current_holdings_df.to_csv(f"output/{run_date}_holding_test.csv")
    minio_db.upload_dataframe_to_parquet(
        current_holdings_df, object_name=holdings_file_path, bucket_name=bucket_name
    )
    print(f"Daily holdings updated and saved for {run_date}")


def update_performance_data(
    run_date: str,
    performance_df: pd.DataFrame = None,
    current_holdings_df: pd.DataFrame = None,
    capital_add: float = 0,
    cash_change: float = 0,
    bucket_name: str = None,
):
    file_path = "performance/strategy_daily_stats.parquet"
    if performance_df is None or performance_df.empty:
        performance_df = minio_db.load_parquet(
            object_name=file_path, bucket_name=bucket_name
        )
    if current_holdings_df is None or current_holdings_df.empty:
        current_holdings_df = minio_db.load_current_holdings(bucket_name=bucket_name)

    if performance_df is not None and not performance_df.empty:
        last_capital = performance_df["initial_capital"].iloc[-1]
        last_cash = performance_df["cash"].iloc[-1]
    else:
        last_capital = load_config()["initial_capital"]
        last_cash = load_config()["initial_capital"]

    initial_capital = last_capital + capital_add
    investment_cost = current_holdings_df["total_investment"].sum().round(4)
    investment_value = current_holdings_df["current_value"].sum().round(4)
    if last_cash + cash_change < 0:
        print(f"ALERT: Cash went negative on {run_date}! Setting to 0 for accounting.")
        cash = 0
    else:
        cash = last_cash + cash_change
    net_capital = investment_value + cash
    pnl = net_capital - initial_capital
    pct_change = (pnl / initial_capital).round(6) if initial_capital != 0 else 0

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
    performance_df.to_csv("output/performance_test.csv")
    minio_db.upload_dataframe_to_parquet(
        performance_df, file_path, bucket_name=bucket_name
    )
    print(f"Performance updated for {run_date}.")


def execute_trade(
    execute_date: str,
    fee_rate: float = load_config()["transaction_fee"],
    mongodb_collection_name: str = None,
    minio_bucket_name: str = None,
):
    config = load_config()
    portfolio = mongodb.get_pending(collection_name=mongodb_collection_name)

    if not portfolio:
        print("Nothing to execute today.")
        return False

    # Initialize Dataframe and Columns
    trade_df = pd.DataFrame(portfolio["trades"])
    expected_cols = ["exec_price", "exec_shares", "investment", "fees"]
    for col in expected_cols:
        if col not in trade_df.columns:
            trade_df[col] = np.nan

    # Align Current Holdings
    current_holdings_df = minio_db.load_current_holdings(bucket_name=minio_bucket_name)
    if current_holdings_df is None or current_holdings_df.empty:
        current_holdings_df = pd.DataFrame(
            columns=[
                "symbol",
                "currency",
                "current_shares",
                "total_investment",
                "avg_cost",
                "current_price",
            ]
        )
        current_shares_df = pd.DataFrame(columns=["symbol", "current_shares"])
    else:
        current_shares_df = current_holdings_df[["symbol", "current_shares"]]

    trade_df = pd.merge(trade_df, current_shares_df, on="symbol", how="left")
    with pd.option_context("future.no_silent_downcasting", True):
        trade_df["current_shares"] = (
            trade_df["current_shares"].fillna(0).infer_objects(copy=False)
        )

    # Get Capital for Rebalance
    performance_df = minio_db.load_parquet(
        object_name="performance/strategy_daily_stats.parquet",
        bucket_name=minio_bucket_name,
    )
    capital = (
        performance_df["net_capital"].iloc[-1]
        if performance_df is not None and not performance_df.empty
        else config["initial_capital"]
    ) * 0.99  # 1% buffer
    print(f"Trading capital: {capital}")

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

    # Fetch and Merge FX
    new_fx_data = postgres.get_fx_data(start_date=execute_date, end_date=execute_date)
    if new_fx_data is not None and not new_fx_data.empty:
        fx_rates = new_fx_data.rename(
            columns={"USD_to": "currency", "close_price": "fx_rate"}
        )[["currency", "fx_rate"]]

        trade_df = pd.merge(trade_df, fx_rates, on="currency", how="left")

    gbp_lookup = fx_rates.loc[fx_rates["currency"] == "GBP", "fx_rate"].iloc[0]
    if not gbp_lookup.empty:
        trade_df.loc[trade_df["currency"] == "GBp", "fx_rate"] = gbp_lookup * 100
    else:
        print("Warning: GBp stocks found but no GBP rate in database!")
    trade_df.loc[trade_df["currency"] == "USD", "fx_rate"] = 1.0
    trade_df["fx_rate"] = trade_df["fx_rate"].fillna(1.0)

    # Execution Logic
    to_execute_mask = trade_df["exec_price"].notna() & trade_df["exec_shares"].isna()
    usd_price = (
        trade_df.loc[to_execute_mask, "exec_price"]
        / trade_df.loc[to_execute_mask, "fx_rate"]
    )
    target_shares = (
        (trade_df.loc[to_execute_mask, "weight"] * capital * (1 - 2 * fee_rate))
        / usd_price
    ).apply(
        np.floor
    )  # Using floor to ensure affordability
    trade_df.loc[to_execute_mask, "exec_shares"] = (
        target_shares - trade_df.loc[to_execute_mask, "current_shares"]
    )
    trade_df.loc[to_execute_mask, "investment"] = (
        trade_df["exec_shares"] * (trade_df["exec_price"] / trade_df["fx_rate"])
    ).round(4)
    trade_df.loc[to_execute_mask, "fees"] = (
        abs(trade_df["investment"]) * fee_rate
    ).round(4)

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

    trade_info_df.to_csv(f"output/{execute_date}_trading_test.csv")

    mongodb.update_trade_log(portfolio, collection_name=mongodb_collection_name)
    mongodb.check_pending(collection_name=mongodb_collection_name)

    # Update MinIO Holdings Snapshot and Perfomance
    holdings_change_df = trade_df.loc[
        trade_df["exec_shares"] != 0,
        ["symbol", "exec_shares", "exec_price", "fees", "currency", "fx_rate"],
    ]
    with pd.option_context("future.no_silent_downcasting", True):
        updated_holdings = (
            pd.merge(current_holdings_df, holdings_change_df, on="symbol", how="outer")
            .fillna(0)
            .infer_objects(copy=False)
        )
    updated_holdings["total_investment"] = updated_holdings["total_investment"].astype(
        float
    )
    updated_holdings["current_shares"] = (
        updated_holdings["current_shares"] + updated_holdings["exec_shares"]
    )

    is_buy = updated_holdings["exec_shares"] > 0
    updated_holdings.loc[is_buy, "total_investment"] += (
        (
            updated_holdings["exec_shares"]
            * (updated_holdings["exec_price"] / updated_holdings["fx_rate"])
        )
        + updated_holdings["fees"]
    ).round(4)

    is_total_exit = (updated_holdings["current_shares"] <= 0.001) & (
        updated_holdings["exec_shares"] < 0
    )
    is_partial_sell = (updated_holdings["current_shares"] > 0.001) & (
        updated_holdings["exec_shares"] < 0
    )
    if is_partial_sell.any():
        denom = updated_holdings.loc[is_partial_sell, "current_shares"] + abs(
            updated_holdings.loc[is_partial_sell, "exec_shares"]
        )
        updated_holdings.loc[is_partial_sell, "total_investment"] *= (
            updated_holdings.loc[is_partial_sell, "current_shares"] / denom
        )
    updated_holdings.loc[is_total_exit, "total_investment"] = 0

    updated_holdings = updated_holdings[
        updated_holdings["current_shares"] > 0.001
    ].copy()
    updated_holdings["avg_cost"] = (
        updated_holdings["total_investment"] / updated_holdings["current_shares"]
    ).round(4)
    updated_holdings = updated_holdings.drop(
        columns=["exec_shares", "exec_price", "fees", "fx_rate"]
    )

    print("Updating holdings...")

    update_holdings(execute_date, updated_holdings, bucket_name=minio_bucket_name)

    update_performance_data(
        execute_date,
        performance_df,
        cash_change=cash_flow,
        bucket_name=minio_bucket_name,
    )

    return True


def initiate_portfolio(
    init_date: str, minio_bucket_name: str = None, mongodb_collection_name: str = None
):
    object_name = "performance/strategy_daily_stats.parquet"
    columns = [
        "date",
        "initial_capital",
        "investment_cost",
        "investment_value",
        "cash",
        "net_capital",
        "P&L",
        "percentage_change",
    ]
    if minio_bucket_name is None:
        minio_db.create_empty_parquet(object_name=object_name, columns=columns)
    else:
        minio_db.create_empty_parquet(
            object_name=object_name, bucket_name=minio_bucket_name, columns=columns
        )
    establish_portfolio(init_date, collection_name=mongodb_collection_name)
    print("Sucessfully Initiate Portfolio.")


def rebalance(rebalance_date: str, mongodb_collection_name: str = None):
    establish_portfolio(rebalance_date, collection_name=mongodb_collection_name)
    print("Sucessfully Rebalance Portfolio.")
