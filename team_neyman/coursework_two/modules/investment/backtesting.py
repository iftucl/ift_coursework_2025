import yaml
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


def backtest(start_date: str, end_date: str, fee_rate: float):
    minio_bucket_name = "backtest"
    mongodb_collection_name = "backtest"

    date_range = pd.date_range(start=start_date, end=end_date, freq="B")

    for i, current_ts in enumerate(date_range):
        run_date = current_ts.strftime("%Y-%m-%d")
        print(f"\n [BACKTEST] Processing Date: {run_date}")

        try:
            if i == 0:
                print(f"Initializing strategy on {run_date}")
                trading.initiate_portfolio(
                    run_date,
                    minio_bucket_name=minio_bucket_name,
                    mongodb_collection_name=mongodb_collection_name,
                )
            elif current_ts.is_month_start:
                trading.rebalance(
                    run_date, mongodb_collection_name=mongodb_collection_name
                )
            else:
                trade_execution = trading.execute_trade(
                    fee_rate,
                    run_date,
                    mongodb_collection_name=mongodb_collection_name,
                    minio_bucket_name=minio_bucket_name,
                )
                if not trade_execution:
                    trading.update_holdings(run_date, bucket_name=minio_bucket_name)
                    trading.update_performance_data(
                        run_date, bucket_name=minio_bucket_name
                    )

        except Exception as e:
            print(f"Error on {run_date}: {e}")
            continue

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
        help="Transaction fee apply to trading. Defaults to 0.03",
    )

    args = parser.parse_args()

    end_date = (
        args.end_date
        if args.end_date
        else (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    )

    fee_rate = args.fee if args.fee else load_config()["transaction_fee"]

    backtest(args.start_date, end_date, fee_rate)
