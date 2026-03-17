import io
from pathlib import Path

import pandas as pd
import yaml
from minio import Minio
from minio.error import S3Error

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "conf.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["minio"]


def upload_dataframe_to_parquet(df: pd.DataFrame, object_name: str):
    """
    Serializes a Pandas DataFrame to Parquet format and uploads it to MinIO object storage.

    This function facilitates the transition from relational processing to analytical
    storage by converting filtered factor results into an immutable, compressed
    Parquet format—the industry standard for high-performance data lakes.

    Args:
        df (pd.DataFrame): The final processed DataFrame containing factor signals.
        object_name (str): The destination path/filename within the MinIO bucket
            (e.g., 'outputs/final_signals_2026-03-15.parquet').

    Returns:
        None: Performs an in-memory conversion and remote write to the MinIO cluster.

    Note:
        Uses an in-memory BytesIO buffer for the Parquet conversion to avoid
        unnecessary disk I/O operations within the container.
    """
    config = load_config()
    client = Minio(
        config["endpoint"],
        access_key=config["access_key"],
        secret_key=config["secret_key"],
        secure=config["secure"],
    )

    try:
        bucket_name = config["bucket_name"]
        if not client.bucket_exists(bucket_name):
            print(f"Bucket '{bucket_name}' not found. Creating it...")
            client.make_bucket(bucket_name)
        parquet_buffer = io.BytesIO()
        df.to_parquet(parquet_buffer, index=False, engine="pyarrow")
        parquet_buffer.seek(0)
        client.put_object(
            bucket_name=bucket_name,
            object_name=object_name,
            data=parquet_buffer,
            length=parquet_buffer.getbuffer().nbytes,
            content_type="application/octet-stream",
        )
        print(f"Successfully uploaded {object_name} to MinIO bucket '{bucket_name}'.")
    except S3Error as e:
        print(f"MinIO S3 Error: {e}")
    except Exception as e:
        print(f"MinIO Upload Error: {e}")
