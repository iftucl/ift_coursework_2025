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


config = load_config()
client = Minio(
    config["endpoint"],
    access_key=config["access_key"],
    secret_key=config["secret_key"],
    secure=config["secure"],
)
bucket_name = config["bucket_name"]


def upload_dataframe_to_parquet(
    df: pd.DataFrame, object_name: str, bucket_name: str = bucket_name
):
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

    try:
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


def create_empty_parquet(
    object_name: str, bucket_name: str = bucket_name, columns: list = None
):
    df_empty = pd.DataFrame(columns=columns)

    parquet_buffer = io.BytesIO()
    df_empty.to_parquet(parquet_buffer, index=False)
    parquet_buffer.seek(0)

    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)

    client.put_object(
        bucket_name,
        object_name,
        data=parquet_buffer,
        length=parquet_buffer.getbuffer().nbytes,
        content_type="application/octet-stream",
    )
    print(f"Created empty parquet: {object_name} in {bucket_name}")


def load_parquet(
    object_name: str, bucket_name: str = bucket_name, create: bool = False
):
    try:
        print(f"Attempting to read: {object_name} from bucket: {bucket_name}")
        response = client.get_object(bucket_name, object_name)
        df = pd.read_parquet(io.BytesIO(response.read()))
        return df
    except S3Error as e:
        if e.code == "NoSuchKey" and create:
            print(
                f"File '{object_name}' not found. Creating a new empty Parquet file..."
            )
            create_empty_parquet(bucket_name, object_name)
            return pd.DataFrame()
        else:
            print(f"Error: Could not find or read file '{object_name}'. {e}")
            return None


def load_current_holdings(bucket_name: str = bucket_name):
    objects = client.list_objects(bucket_name, prefix="holdings/", recursive=True)
    holdings_files = [
        obj.object_name for obj in objects if obj.object_name.endswith(".parquet")
    ]

    if not holdings_files:
        print("No holdings files found in MinIO. Returning empty DataFrame.")
        return None

    holdings_files.sort()
    latest_file = holdings_files[-1]

    print(f"Loading newest holdings: {latest_file}")
    df = load_parquet(latest_file, bucket_name=bucket_name)
    return df


def reset_minio():

    buckets = client.list_buckets()

    for bucket in buckets:
        print(f"Clearing bucket: {bucket.name}...")
        objects = client.list_objects(bucket.name, recursive=True)
        for obj in objects:
            client.remove_object(bucket.name, obj.object_name)
        client.remove_bucket(bucket.name)

    print("MinIO reset complete.")
