import argparse
import io
import os

import pandas as pd
from minio import Minio

from a_pipeline.modules.db_loader.minio_loader import load_config


def peek_at_minio(target_date=None, export=False):
    config = load_config()
    client = Minio(
        config["endpoint"],
        access_key=config["access_key"],
        secret_key=config["secret_key"],
        secure=config["secure"],
    )

    bucket = config["bucket_name"]
    if target_date:
        object_name = f"target_companies_{target_date}.parquet"
    else:
        objects = client.list_objects(bucket)
        object_names = [obj.object_name for obj in objects]
        if not object_names:
            print(f"No files found in bucket '{bucket}'.")
            return
        object_name = sorted(object_names)[-1]

    print(f"Attempting to read: {object_name} from bucket: {bucket}")

    try:
        response = client.get_object(bucket, object_name)
        df = pd.read_parquet(io.BytesIO(response.read()))
        if export:
            os.makedirs("outputs", exist_ok=True)
            export_name = os.path.join(
                "outputs", object_name.replace(".parquet", ".csv")
            )
            df.to_csv(export_name, index=False)
            print(f"Successfully exported to {export_name}")
        else:
            print("\n--- Data Preview ---")
            print(df.head())
    except Exception as e:
        print(f"Error: Could not find or read file '{object_name}'. {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect MinIO Parquet files.")
    parser.add_argument("--date", type=str, help="Target date in YYYY-MM-DD format")
    parser.add_argument(
        "--export", action="store_true", help="Save the data as a local CSV"
    )
    args = parser.parse_args()

    peek_at_minio(target_date=args.date, export=args.export)
