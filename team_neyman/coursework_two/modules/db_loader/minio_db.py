import io
import re
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
BUCKET_NAME = config["bucket_name"]


def upload_dataframe_to_parquet(
    df: pd.DataFrame, object_name: str, bucket_name: str = BUCKET_NAME
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
    object_name: str, bucket_name: str = BUCKET_NAME, columns: list = None
):
    """
    Initializes a structured but empty Parquet file in MinIO as a pipeline placeholder.

    Automatically creates the target bucket if it does not exist and uploads an empty DataFrame with the specified column schema via an in-memory BytesIO buffer.

    Args:
        object_name (str): Destination path within the bucket.
        bucket_name (str, optional): Target MinIO bucket. Defaults to BUCKET_NAME.
        columns (list, optional): List of column headers to define the Parquet schema.

    Returns:
        None: Uploads the file directly to MinIO.
    """

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
    object_name: str, bucket_name: str = BUCKET_NAME, create: bool = False
):
    """
    Retrieves a Parquet file from MinIO and converts it into a pandas DataFrame.

    If the specified object is missing and the 'create' flag is enabled, the function
    automatically initializes a new empty Parquet file via 'create_empty_parquet'
    to prevent downstream pipeline crashes.

    Args:
        object_name (str): The destination path of the Parquet file.
        bucket_name (str, optional): Target MinIO bucket. Defaults to BUCKET_NAME.
        create (bool): If True, initializes a new file if the key does not exist.

    Returns:
        pd.DataFrame: The loaded data, an empty DataFrame if a new file was created,
                      or None if a retrieval error occurs.
    """

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


def load_current_holdings(bucket_name: str = BUCKET_NAME):
    """
    Retrieves the most recent portfolio snapshot from the 'holdings/' directory in MinIO.

    The function filters for Parquet files and utilizes chronological file-naming conventions to identify and load the latest state. It provides a clean fallback if no historical snapshots are detected.

    Args:
        bucket_name (str, optional): Target MinIO bucket. Defaults to BUCKET_NAME.

    Returns:
        pd.DataFrame: The latest holdings data or None if no files exist.
    """

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


def get_initial_date(bucket_name: str = BUCKET_NAME):
    """
    Identifies the baseline start date from archived holdings files in MinIO.

    Parses filenames using regex to extract 'YYYY-MM-DD' patterns and requires a minimum of five records to establish a stabilized backtest window. Returns the fifth chronological date to skip the initial warm-up period.

    Args:
        bucket_name (str, optional): Target MinIO bucket. Defaults to BUCKET_NAME.

    Returns:
        str: The 5th chronological date (YYYY-MM-DD) found in the bucket.
    """

    all_files = client.list_objects(bucket_name, prefix="holdings/", recursive=True)
    file_names = [obj.object_name for obj in all_files]
    dates = sorted(
        [
            re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
            for f in file_names
            if "_holdings.parquet" in f
        ]
    )
    if len(dates) < 5:
        raise ValueError(
            f"Found only {len(dates)} files. Need at least 5 to use the default start_date logic."
        )
    return dates[4]


def get_latest_date(bucket_name: str = BUCKET_NAME):
    """
    Identifies the most recent holdings date available in MinIO.

    Scans the 'holdings/' directory and uses regex to extract the latest 'YYYY-MM-DD' timestamp from archived Parquet files.

    Args:
        bucket_name (str, optional): Target MinIO bucket. Defaults to BUCKET_NAME.

    Returns:
        str: The latest chronological date string.
    """

    all_files = client.list_objects(bucket_name, prefix="holdings/", recursive=True)
    file_names = [obj.object_name for obj in all_files]
    dates = sorted(
        [
            re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
            for f in file_names
            if "_holdings.parquet" in f
        ]
    )
    return dates[-1]


def del_bucket(bucket_name: str):
    """
    Surgically removes a specific MinIO bucket and all nested objects.

    Recursively identifies and deletes all archived Parquet files and directories
    within the target bucket to satisfy the S3 requirement that a bucket must
    be empty before deletion.

    Args:
        bucket_name (str): The target MinIO bucket name to be removed.

    Returns:
        None
    """

    try:
        if not client.bucket_exists(bucket_name):
            print(f"Warning: Bucket '{bucket_name}' does not exist.")
            return

        objects_to_delete = client.list_objects(bucket_name, recursive=True)
        for obj in objects_to_delete:
            client.remove_object(bucket_name, obj.object_name)

        client.remove_bucket(bucket_name)
        print(f"Bucket '{bucket_name}' and all contents successfully deleted.")

    except Exception as e:
        print(f"Error deleting bucket '{bucket_name}': {e}")


def reset_minio():
    """
    Wipes the entire MinIO instance by recursively deleting all objects and their parent buckets.

    Iterates through every accessible bucket, clears all nested data to satisfy S3 deletion requirements, and removes the empty buckets. Used to ensure a clean state for fresh backtest cycles.

    Returns:
        None: Prints reset status to the console.
    """

    buckets = client.list_buckets()

    for bucket in buckets:
        print(f"Clearing bucket: {bucket.name}...")
        objects = client.list_objects(bucket.name, recursive=True)
        for obj in objects:
            client.remove_object(bucket.name, obj.object_name)
        client.remove_bucket(bucket.name)

    print("MinIO reset complete.")
