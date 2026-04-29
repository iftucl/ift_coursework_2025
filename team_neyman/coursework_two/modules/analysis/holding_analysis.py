import argparse

import pandas as pd

from modules.db_loader import mongodb


def generate_sector_weights(
    collection_name: str, start_date_str: str = None, end_date_str: str = None
):
    """
    Generates a monthly time-series of GICS sector allocations from MongoDB trade logs.

    The function pivots trade data into an analysis-ready DataFrame indexed by 'YYYY-MM'.
    It automatically resolves date boundaries, fills gaps for unheld sectors with 0.0,
    and reindexes columns alphabetically to ensure stable visualizations (e.g., area charts).

    Args:
        collection_name (str): MongoDB collection containing trade logs.
        start_date_str (str, optional): Start boundary. Defaults to inception.
        end_date_str (str, optional): End boundary. Defaults to latest record.

    Returns:
        pd.DataFrame: Monthly sector weights (0.0~1.0). Returns empty if no data.
    """

    if not start_date_str:
        start_date_str = mongodb.get_initial_date(collection_name)
    if not end_date_str:
        end_date_str = mongodb.get_latest_date(collection_name)

    if not start_date_str or not end_date_str:
        print("No data found in collection.")
        return pd.DataFrame()

    start_date = pd.to_datetime(start_date_str)
    end_date = pd.to_datetime(end_date_str)

    month_range = pd.date_range(start=start_date, end=end_date, freq="MS")
    all_monthly_data = []

    for date_obj in month_range:
        year = str(date_obj.year)
        month = str(date_obj.month)
        sector_series = mongodb.get_sector_weights(
            year, month, collection_name=collection_name
        )
        if not sector_series.empty:
            row = sector_series.to_dict()
            row["date"] = date_obj.strftime("%Y-%m")
            all_monthly_data.append(row)

    df = pd.DataFrame(all_monthly_data)
    if df.empty:
        return df

    df = df.set_index("date")
    df = df.fillna(0.0)
    df = df.reindex(sorted(df.columns), axis=1)

    return df


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Analyse Portfolio Holdings")

    parser.add_argument(
        "--collection",
        type=str,
        required=True,
        help="The MongoDB collection name stroing portfolio trading data",
    )

    parser.add_argument(
        "--start_date",
        type=str,
        help="The specific starting date to calculating weights (YYYY-MM-DD). Default to initial date.",
    )

    parser.add_argument(
        "--end_date",
        type=str,
        help="The specific ending date for calculating weights (YYYY-MM-DD). Default to latest date.",
    )

    args = parser.parse_args()

    start_date = args.start_date if args.start_date else None
    end_date = args.end_date if args.end_date else None

    weights_df = generate_sector_weights(args.collection, start_date, end_date)
    if not weights_df.empty:
        output_file = f"output/{args.collection}_sector_weights.csv"
        weights_df.to_csv(output_file)
        print(f"Sector weights saved to {output_file}")
    else:
        print("No data was generated. Check your collection name and date range.")
