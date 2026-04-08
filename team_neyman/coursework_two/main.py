import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from modules.db_loader import postgres, minio_db
from modules.factors import fetch_factors


def main():
    parser = argparse.ArgumentParser(description="IFT Coursework Team Neyman")

    parser.add_argument(
        "--date",
        type=str,
        help="The specific date to run (YYYY-MM-DD). Defaults to yesterday.",
    )

    args = parser.parse_args()

    run_date = (
        args.date if args.date else (datetime.now() - timedelta(1)).strftime("%Y-%m-%d")
    )

    print(f"Starting run for date: {run_date}")

    try:
        target_df = fetch_factors.get_target_factors(run_date)
        if not target_df.empty:
            filtered_df = fetch_factors.apply_filter(target_df)
            final_df = fetch_factors.apply_scoring(filtered_df)

            filename = f"target_companies_{run_date}.parquet"
            minio_db.upload_dataframe_to_parquet(final_df, filename)
            print(f"SUCCESS: Results stored as {filename}")
        else:
            print("No companies passed the filters today.")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
