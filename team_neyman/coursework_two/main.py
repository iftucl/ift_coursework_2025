import argparse
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from modules.db_loader import postgres, minio_db
from modules.factors import fetch_factors
from modules.investment import trading


def main():
    parser = argparse.ArgumentParser(description="IFT Coursework Team Neyman")

    parser.add_argument(
        "--date",
        type=str,
        help="The specific date to run (YYYY-MM-DD). Defaults to yesterday.",
    )

    parser.add_argument(
        "--action",
        choices=["update", "initiate", "rebalance", "trade"],
        default="update",
        help="The action executing. Defaults to update.",
    )

    args = parser.parse_args()

    run_date = (
        args.date
        if args.date
        else (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    )

    print(f"Starting {args.action} for date: {run_date}")

    try:
        if args.action == "initiate":
            trading.initiate_portfolio(run_date)
        elif args.action == "rebalance":
            trading.rebalance(run_date)
        elif args.action == "trade":
            trading.execute_trade(run_date)
        else:
            trading.update_holdings(run_date)
            trading.update_performance_data(run_date)
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
