from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from modules.db_loader import minio_db, mongodb, postgres
from modules.factors import fetch_factors

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["trading"]


def establish_portfolio(
    run_date: str,
    mongodb_collection_name: str = None,
    minio_bucket_name: str = None,
    omit_factor: str = None,
):
    """
    Constructs a target portfolio for a specific date and logs it as a pending trade event.

    This function serves as the "brain" of the rebalancing process. It orchestrates the
    entire pipeline: selecting the universe, filtering for liquidity/trends, scoring
    factors, and calculating constrained weights. It then calculates available trading
    capital (including a safety buffer) and archives the plan to MongoDB.

    Args:
        run_date (str): The date for portfolio construction (YYYY-MM-DD).
        mongodb_collection_name (str, optional): Target collection for trade logs.
        minio_bucket_name (str, optional): Source bucket for performance history.
        omit_factor (str, optional): Specific factor to exclude from the scoring model.

    Returns:
        None: Records the trade log and prints status updates to the console.
    """

    factors_df = fetch_factors.get_target_factors(run_date)
    filtered_df = fetch_factors.apply_filter(factors_df)
    scored_df = fetch_factors.apply_scoring(filtered_df, omit_factor)
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

    # Get Capital
    config = load_config()
    performance_df = minio_db.load_parquet(
        object_name="performance/strategy_daily_stats.parquet",
        bucket_name=minio_bucket_name,
    )
    capital = (
        performance_df["net_capital"].iloc[-1]
        if performance_df is not None and not performance_df.empty
        else config["initial_capital"]
    ) * 0.98  # 2% buffer
    print(f"Trading capital: {capital}")

    mongodb.save_trade_log(run_date, capital, mongo_documents, mongodb_collection_name)
    print(f"Portfolio established and logged for {run_date}")


def update_holdings(
    run_date: str, current_holdings_df: pd.DataFrame = None, bucket_name: str = None
):
    """
    Performs daily 'Mark-to-Market' (MTM) updates on current portfolio holdings.

    Synchronizes the latest asset prices and FX rates from PostgreSQL to calculate
    real-time valuations, profit and loss (P&L), and percentage performance. The
    updated snapshot is then archived as a Parquet file in MinIO.

    Args:
        run_date (str): The valuation date (YYYY-MM-DD).
        current_holdings_df (pd.DataFrame, optional): Existing holdings. If None,
                                                      loads from the latest MinIO file.
        bucket_name (str, optional): Target MinIO bucket.

    Returns:
        None: Updates the state and writes to MinIO.
    """

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

    lookback_start = (pd.to_datetime(run_date) - timedelta(days=7)).strftime("%Y-%m-%d")
    new_fx_data = postgres.get_fx_data(start_date=lookback_start, end_date=run_date)
    if new_fx_data is not None and not new_fx_data.empty:
        new_fx_data = new_fx_data.sort_values(
            ["usd_to", "price_date"], ascending=[True, False]
        )
        new_fx_data = new_fx_data.drop_duplicates(subset="usd_to", keep="first")
        new_fx_data = new_fx_data.rename(
            columns={"usd_to": "currency", "close_price": "new_fx_rate"}
        )[["currency", "new_fx_rate"]]
        current_holdings_df["currency"] = (
            current_holdings_df["currency"].astype(str).str.strip()
        )
        current_holdings_df = pd.merge(
            current_holdings_df, new_fx_data, on="currency", how="left"
        )
        current_holdings_df.loc[
            current_holdings_df["currency"] == "USD", "new_fx_rate"
        ] = 1.0
        gbp_lookup = new_fx_data.loc[new_fx_data["currency"] == "GBP", "new_fx_rate"]
        if not gbp_lookup.empty:
            current_holdings_df.loc[
                current_holdings_df["currency"] == "GBp", "new_fx_rate"
            ] = (gbp_lookup.iloc[0] * 100)
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
    # current_holdings_df.to_csv(f"output/{run_date}_holding_test.csv")
    minio_db.upload_dataframe_to_parquet(
        current_holdings_df, object_name=holdings_file_path, bucket_name=bucket_name
    )
    print(f"Daily holdings updated and saved for {run_date}")


def update_performance_data(
    run_date: str,
    current_holdings_df: pd.DataFrame = None,
    capital_add: float = 0,
    cash_change: float = 0,
    bucket_name: str = None,
):
    """
    Computes and archives daily portfolio performance metrics to track the strategy's NAV.

    Aggregates investment values and cash balances to determine total net capital,
    calculates absolute P&L and percentage returns relative to initial capital,
    and maintains a historical time-series in MinIO.

    Args:
        run_date (str): The valuation date (YYYY-MM-DD).
        current_holdings_df (pd.DataFrame, optional): Latest asset snapshot.
                                                      Loads from MinIO if omitted.
        capital_add (float): External capital injections or withdrawals.
        cash_change (float): Net movement in cash (from trades, dividends, or fees).
        bucket_name (str, optional): Target MinIO bucket.

    Returns:
        None: Appends a new performance record to the historical log.
    """

    file_path = "performance/strategy_daily_stats.parquet"
    performance_df = minio_db.load_parquet(
        object_name=file_path, bucket_name=bucket_name
    )
    if performance_df is None:
        performance_df = pd.DataFrame()

    if current_holdings_df is None or current_holdings_df.empty:
        current_holdings_df = minio_db.load_current_holdings(bucket_name=bucket_name)
    if current_holdings_df is None:
        current_holdings_df = pd.DataFrame(
            columns=["total_investment", "current_value"]
        )

    if performance_df is not None and not performance_df.empty:
        last_capital = performance_df["initial_capital"].iloc[-1]
        last_cash = performance_df["cash"].iloc[-1]
    else:
        last_capital = load_config()["initial_capital"]
        last_cash = load_config()["initial_capital"]

    initial_capital = last_capital + capital_add
    investment_cost = 0.0
    if "total_investment" in current_holdings_df.columns:
        investment_cost = round(current_holdings_df["total_investment"].sum(), 4)
    investment_value = 0.0
    if "current_value" in current_holdings_df.columns:
        investment_value = round(current_holdings_df["current_value"].sum(), 4)
    elif not current_holdings_df.empty:
        investment_value = investment_cost

    if last_cash + cash_change < 0:
        print(f"ALERT: Cash went negative on {run_date}!")
    cash = last_cash + cash_change
    net_capital = investment_value + cash
    pnl = net_capital - initial_capital
    pct_change = round((pnl / initial_capital), 6) if initial_capital != 0 else 0

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
    performance_df.to_csv(f"output/performance_{bucket_name}.csv")
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
    """
    Simulates the transition from a target portfolio signal to realized market positions.

    This function acts as the Order Management System (OMS). It reconciles current
    holdings with desired weights, fetches real-time execution prices/FX rates,
    calculates net share changes, and updates the account's cost basis and cash
    balances.

    Args:
        execute_date (str): The date the trades are executed (YYYY-MM-DD).
        fee_rate (float): The transaction cost percentage (e.g., 0.001 for 10bps).
        mongodb_collection_name (str, optional): Target collection for trade logs.
        minio_bucket_name (str, optional): Target bucket for holdings snapshots.

    Returns:
        bool: True if execution was attempted (success or partial),
              False if no pending trades or market data were found.
    """

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
        current_shares_df = pd.DataFrame(
            columns=["symbol", "currency", "current_shares"]
        )
    else:
        current_shares_df = current_holdings_df[
            ["symbol", "currency", "current_shares"]
        ]

    trade_df = pd.merge(
        trade_df, current_shares_df, on="symbol", how="outer", suffixes=("", "_old")
    )
    if "currency_old" in trade_df.columns:
        trade_df["currency"] = trade_df["currency"].fillna(trade_df["currency_old"])
        trade_df = trade_df.drop(columns=["currency_old"])
    trade_df["weight"] = trade_df["weight"].fillna(0.0)
    with pd.option_context("future.no_silent_downcasting", True):
        trade_df["current_shares"] = (
            trade_df["current_shares"].fillna(0).infer_objects(copy=False)
        )

    # Fetch and Merge Prices
    new_prices_data = postgres.get_ohlcv_data(
        trade_df["symbol"].tolist(), start_date=execute_date, end_date=execute_date
    )
    trade_df["new_price"] = np.nan
    if not new_prices_data.empty:
        new_prices_data = new_prices_data.rename(columns={"close_price": "new_price"})[
            ["symbol", "new_price"]
        ]
        trade_df = trade_df.drop(columns=["new_price"])
        trade_df = pd.merge(trade_df, new_prices_data, on="symbol", how="left")
        trade_df["exec_price"] = trade_df["exec_price"].combine_first(
            trade_df["new_price"]
        )
    else:
        print(f"No market data for {execute_date}")
        return False

    # Fetch and Merge FX
    lookback_start = (pd.to_datetime(execute_date) - timedelta(days=7)).strftime(
        "%Y-%m-%d"
    )
    new_fx_data = postgres.get_fx_data(start_date=lookback_start, end_date=execute_date)
    if new_fx_data is not None and not new_fx_data.empty:
        new_fx_data = new_fx_data.sort_values("price_date", ascending=False)
        new_fx_data = new_fx_data.drop_duplicates(subset="usd_to", keep="first")
        new_fx_data = new_fx_data.rename(
            columns={"usd_to": "currency", "close_price": "fx_rate"}
        )[["currency", "fx_rate"]]

        if "fx_rate" in trade_df.columns:
            trade_df = trade_df.drop(columns=["fx_rate"])

        trade_df = pd.merge(trade_df, new_fx_data, on="currency", how="left")

    gbp_lookup = new_fx_data.loc[new_fx_data["currency"] == "GBP", "fx_rate"]
    if not gbp_lookup.empty:
        trade_df.loc[trade_df["currency"] == "GBp", "fx_rate"] = (
            gbp_lookup.iloc[0] * 100
        )
    else:
        print("Warning: GBp stocks found but no GBP rate in database!")
    trade_df.loc[trade_df["currency"] == "USD", "fx_rate"] = 1.0
    trade_df["fx_rate"] = trade_df["fx_rate"].replace(0, np.nan).fillna(1.0)

    # Execution Logic
    capital = portfolio["capital"]
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
    just_executed_mask = to_execute_mask & trade_df["exec_shares"].notna()
    trade_df.loc[to_execute_mask, "investment"] = (
        trade_df["exec_shares"] * (trade_df["exec_price"] / trade_df["fx_rate"])
    ).round(4)
    trade_df.loc[to_execute_mask, "fees"] = (
        abs(trade_df["investment"]) * fee_rate
    ).round(4)

    # Update MongoDB Trading Info
    missing_symbols = trade_df.loc[trade_df["exec_price"].isna(), "symbol"].tolist()
    trade_info_df = trade_df.drop(
        columns=["new_price", "current_shares"], errors="ignore"
    )
    todays_trades = trade_df.loc[just_executed_mask]
    cash_flow = -(todays_trades["investment"].sum() + todays_trades["fees"].sum())

    portfolio.update(
        {
            "trades": trade_info_df.replace({np.nan: None}).to_dict("records"),
            "net_investment": trade_df["investment"].sum(),
            "total_flow": abs(trade_df["investment"]).sum(),
            "total_fee": trade_df["fees"].sum(),
            "status": "EXECUTED" if not missing_symbols else "PENDING",
        }
    )

    # trade_info_df.to_csv(f"output/{execute_date}_trading_test.csv")

    mongodb.update_trade_log(portfolio, collection_name=mongodb_collection_name)
    mongodb.check_pending(collection_name=mongodb_collection_name)

    # Update MinIO Holdings Snapshot and Perfomance
    holdings_change_df = trade_df.loc[
        just_executed_mask & trade_df["exec_shares"] != 0,
        ["symbol", "currency", "exec_shares", "exec_price", "fees", "fx_rate"],
    ]
    with pd.option_context("future.no_silent_downcasting", True):
        updated_holdings = pd.merge(
            current_holdings_df,
            holdings_change_df,
            on="symbol",
            how="outer",
            suffixes=("", "_new"),
        ).infer_objects(copy=False)
    updated_holdings["currency"] = updated_holdings["currency"].fillna(
        updated_holdings["currency_new"]
    )
    if "fx_rate_new" in updated_holdings.columns:
        updated_holdings["fx_rate"] = updated_holdings["fx_rate_new"].combine_first(
            updated_holdings["fx_rate"]
        )
    updated_holdings = updated_holdings.drop(
        columns=["currency_new", "fx_rate_new"], errors="ignore"
    ).fillna(0)
    updated_holdings["fx_rate"] = (
        updated_holdings["fx_rate"].replace(0, np.nan).fillna(1.0)
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
        cash_change=cash_flow,
        bucket_name=minio_bucket_name,
    )

    return True


def initiate_portfolio(
    init_date: str,
    minio_bucket_name: str = None,
    mongodb_collection_name: str = None,
    omit_factor: str = None,
):
    """
    Initializes the quantitative strategy's infrastructure and generates the starting portfolio.

    This is the "Genesis" function for a new backtest or production run. it creates
    the core performance tracking ledger in MinIO and triggers the first iteration of
    signal generation and capital allocation.

    Args:
        init_date (str): The starting date for the strategy (YYYY-MM-DD).
        minio_bucket_name (str, optional): Target bucket for performance files.
        mongodb_collection_name (str, optional): Target collection for trade logs.
        omit_factor (str, optional): Factor to exclude from the scoring model.

    Returns:
        None: Initializes storage and prints confirmation.
    """

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
    establish_portfolio(
        init_date,
        mongodb_collection_name=mongodb_collection_name,
        minio_bucket_name=minio_bucket_name,
        omit_factor=omit_factor,
    )
    print("Sucessfully Initiate Portfolio.")


def rebalance(
    rebalance_date: str,
    minio_bucket_name: str = None,
    mongodb_collection_name: str = None,
    omit_factor: str = None,
):
    """
    Triggers a scheduled portfolio re-alignment by generating new target weights.

    This function acts as the interface for periodic strategy updates (e.g., monthly).
    It invokes the full construction pipeline to refresh alpha signals,
    apply risk constraints, and queue the necessary buy/sell orders in MongoDB.

    Args:
        rebalance_date (str): The date the rebalance signal is generated (YYYY-MM-DD).
        minio_bucket_name (str, optional): Source for the latest capital figures.
        mongodb_collection_name (str, optional): Destination for the new trade log.
        omit_factor (str, optional): Factor to exclude for attribution testing.

    Returns:
        None: Updates the database state and prints confirmation.
    """

    establish_portfolio(
        rebalance_date,
        mongodb_collection_name=mongodb_collection_name,
        minio_bucket_name=minio_bucket_name,
        omit_factor=omit_factor,
    )
    print("Sucessfully Rebalance Portfolio.")
