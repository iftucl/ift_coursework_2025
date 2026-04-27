import yaml
import sys
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from modules.investment import trading


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["trading"]


def backtest(start_date: str, end_date: str, fee_rate: float, suffix: str = ""):
    fee_bps_str = f"{fee_rate * 10000:g}".replace(".", "")
    portfolio_name = f"backtest{fee_bps_str}bps{suffix}"

    date_range = pd.date_range(start=start_date, end=end_date, freq="B")

    last_month = None

    for i, current_ts in enumerate(date_range):
        run_date = current_ts.strftime("%Y-%m-%d")
        current_month = current_ts.month
        print(f"\n [BACKTEST] Processing Date: {run_date}")

        try:
            if i == 0:
                print(f"Initializing strategy on {run_date}")
                trading.initiate_portfolio(
                    run_date,
                    minio_bucket_name=portfolio_name,
                    mongodb_collection_name=portfolio_name,
                )
                last_month = current_month
            else:
                trade_execution = trading.execute_trade(
                    execute_date=run_date,
                    fee_rate=fee_rate,
                    mongodb_collection_name=portfolio_name,
                    minio_bucket_name=portfolio_name,
                )
                # Update is handled within the trade_execution function.
                if not trade_execution:
                    trading.update_holdings(run_date, bucket_name=portfolio_name)
                    trading.update_performance_data(
                        run_date, bucket_name=portfolio_name
                    )
                if current_month != last_month:
                    print(
                        f"Month changed ({last_month} -> {current_month}). Rebalancing..."
                    )
                    trading.rebalance(
                        run_date,
                        minio_bucket_name=portfolio_name,
                        mongodb_collection_name=portfolio_name,
                    )
                last_month = current_month

        except Exception as e:
            print(f"Error on {run_date}: {e}")
            # continue
            sys.exit(1)

    print("\n Backtest Complete.")


def backtest_with_omit_factor(
    start_date: str, end_date: str, fee_rate: float, omit_factor: str
):
    fee_bps_str = f"{fee_rate * 10000:g}".replace(".", "")
    minio_bucket_name = f"backtest{fee_bps_str}bpsomit{omit_factor}"
    mongodb_collection_name = f"backtest{fee_bps_str}bpsOmit{omit_factor}"

    date_range = pd.date_range(start=start_date, end=end_date, freq="B")

    last_month = None

    for i, current_ts in enumerate(date_range):
        run_date = current_ts.strftime("%Y-%m-%d")
        current_month = current_ts.month
        print(f"\n [BACKTEST] Processing Date: {run_date}")

        try:
            if i == 0:
                print(f"Initializing strategy on {run_date}")
                trading.initiate_portfolio(
                    run_date,
                    minio_bucket_name=minio_bucket_name,
                    mongodb_collection_name=mongodb_collection_name,
                    omit_factor=omit_factor,
                )
                last_month = current_month
            else:
                trade_execution = trading.execute_trade(
                    execute_date=run_date,
                    fee_rate=fee_rate,
                    mongodb_collection_name=mongodb_collection_name,
                    minio_bucket_name=minio_bucket_name,
                )
                # Update is handled within the trade_execution function.
                if not trade_execution:
                    trading.update_holdings(run_date, bucket_name=minio_bucket_name)
                    trading.update_performance_data(
                        run_date, bucket_name=minio_bucket_name
                    )
                if current_month != last_month:
                    print(
                        f"Month changed ({last_month} -> {current_month}). Rebalancing..."
                    )
                    trading.rebalance(
                        run_date,
                        minio_bucket_name=minio_bucket_name,
                        mongodb_collection_name=mongodb_collection_name,
                        omit_factor=omit_factor,
                    )
                last_month = current_month

        except Exception as e:
            print(f"Error on {run_date}: {e}")
            # continue
            sys.exit(1)

    print("\n Backtest Complete.")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Backtesting Portfolio Strategy")

    parser.add_argument(
        "--start_date",
        type=str,
        help="The specific date to start backtest (YYYY-MM-DD).",
    )

    parser.add_argument(
        "--end_date",
        type=str,
        help="The specific date to end backtest (YYYY-MM-DD). Defaults to yesterday",
    )

    parser.add_argument(
        "--fee",
        type=float,
        help="Transaction fee apply to trading. Defaults to 0.01",
    )

    parser.add_argument(
        "--omit_factor",
        type=str,
        choices=["momentum", "fey", "trend", "risk", "liquidity"],
        help="Backtesting without a specific factor. Default to None",
    )

    parser.add_argument(
        "--suffix",
        type=str,
        help="The suffix of portfolio name to identify clearly.",
    )

    args = parser.parse_args()

    end_date = (
        args.end_date
        if args.end_date
        else (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    )

    fee_rate = args.fee if args.fee else load_config()["transaction_fee"]
    suffix = args.suffix if args.suffix else ""

    if args.omit_factor:
        backtest_with_omit_factor(args.start_date, end_date, fee_rate, args.omit_factor)
    else:
        backtest(args.start_date, end_date, fee_rate, suffix)
