"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : MinIO S3-compatible object storage (data lake)
Project : CW1 - Value + News Sentiment Strategy

Stores raw downloaded data (financial JSON, price CSV, news JSON)
in the MinIO data lake, preserving original API responses for
full lineage and reproducibility.

Bucket layout::

    iftbigdata/
    └── raw-data/
        ├── financial/{year}/{ticker}/
        │   ├── income_statement.json
        │   ├── balance_sheet.json
        │   └── cash_flow.json
        ├── prices/{year}/{ticker}/daily_prices.csv
        ├── news/{date}/{ticker}/articles.json
        └── company_info/{ticker}/info.json

Uses ``ift_global.MinioFileSystemRepo`` from the UCL IFT library.
"""

import json
import os

import pandas as pd

from modules.utils.logger import pipeline_logger

try:
    from ift_global import MinioFileSystemRepo

    MINIO_AVAILABLE = True
except ImportError:
    MinioFileSystemRepo = None
    MINIO_AVAILABLE = False


def _safe_serialise(obj):
    """Recursively convert non-JSON-serialisable objects to strings.

    :param obj: Object to sanitise
    :return: JSON-safe version
    """
    if isinstance(obj, dict):
        return {str(k): _safe_serialise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_serialise(item) for item in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (pd.Series, pd.DataFrame)):
        return str(obj)
    return obj


class MinioClient:
    """MinIO data lake client for raw file storage.

    Uses ift_global.MinioFileSystemRepo for S3-compatible operations.
    Degrades gracefully if MinIO is unavailable — the pipeline continues
    without raw storage.

    :param bucket_name: Target MinIO bucket
    :type bucket_name: str
    :param raw_data_path: Base path prefix for raw data
    :type raw_data_path: str
    """

    def __init__(self, bucket_name: str = "iftbigdata", raw_data_path: str = "raw-data"):
        self.bucket_name = bucket_name
        self.raw_data_path = raw_data_path
        self._repo = None

    @property
    def repo(self):
        """Lazy-initialise the MinIO repository client.

        :return: MinioFileSystemRepo or None
        """
        if self._repo is None:
            if not MINIO_AVAILABLE:
                pipeline_logger.warning("ift_global MinIO not available — raw storage disabled")
                return None
            try:
                self._repo = MinioFileSystemRepo(
                    bucket_name=self.bucket_name,
                    user=os.environ.get("MINIO_USER", "ift_bigdata"),
                    password=os.environ.get("MINIO_PASSWORD", "minio_password"),
                    endpoint_url=os.environ.get("MINIO_URL", "http://localhost:9000"),
                )
                pipeline_logger.info("Connected to MinIO bucket: %s", self.bucket_name)
            except Exception as e:
                pipeline_logger.warning("Could not connect to MinIO: %s", e)
                self._repo = None
        return self._repo

    def upload_json(self, data_dict: dict, category: str, identifier: str, filename: str):
        """Upload a JSON object to MinIO.

        :param data_dict: Data to serialise as JSON
        :type data_dict: dict
        :param category: Subfolder category (financial, news, company_info)
        :type category: str
        :param identifier: Company ticker or date string
        :type identifier: str
        :param filename: Target filename (e.g. income_statement.json)
        :type filename: str
        """
        if self.repo is None:
            return
        path = f"{self.raw_data_path}/{category}/{identifier}/{filename}"
        try:
            safe_data = _safe_serialise(data_dict)
            json_bytes = json.dumps(safe_data, default=str, indent=2).encode("utf-8")
            self.repo.get_client.put_object(
                Bucket=self.bucket_name,
                Key=path,
                Body=json_bytes,
                ContentType="application/json",
            )
            pipeline_logger.info("Stored JSON: %s", path)
        except Exception as e:
            pipeline_logger.warning("Failed to store %s in MinIO: %s", path, e)

    def upload_csv(self, df: pd.DataFrame, category: str, identifier: str, filename: str):
        """Upload a DataFrame as CSV to MinIO.

        :param df: Data to store
        :type df: pd.DataFrame
        :param category: Subfolder category (prices, fx)
        :type category: str
        :param identifier: Company ticker or pair identifier
        :type identifier: str
        :param filename: Target filename (e.g. daily_prices.csv)
        :type filename: str
        """
        if self.repo is None:
            return
        path = f"{self.raw_data_path}/{category}/{identifier}/{filename}"
        try:
            csv_bytes = df.to_csv(index=True).encode("utf-8")
            self.repo.get_client.put_object(
                Bucket=self.bucket_name,
                Key=path,
                Body=csv_bytes,
                ContentType="text/csv",
            )
            pipeline_logger.info("Stored CSV: %s", path)
        except Exception as e:
            pipeline_logger.warning("Failed to store %s in MinIO: %s", path, e)

    def download_json(self, category: str, identifier: str, filename: str) -> dict:
        """Download a JSON file from MinIO.

        :param category: Subfolder category
        :type category: str
        :param identifier: Company ticker or date
        :type identifier: str
        :param filename: Target filename
        :type filename: str
        :return: Parsed JSON dict or empty dict
        :rtype: dict
        """
        if self.repo is None:
            return {}
        path = f"{self.raw_data_path}/{category}/{identifier}/{filename}"
        try:
            response = self.repo.get_client.get_object(Bucket=self.bucket_name, Key=path)
            return json.loads(response["Body"].read().decode("utf-8"))
        except Exception as e:
            pipeline_logger.warning("Failed to download %s: %s", path, e)
            return {}

    def list_objects(self, prefix: str) -> list[str]:
        """List object keys under a prefix.

        :param prefix: S3 key prefix to search
        :type prefix: str
        :return: List of object keys
        :rtype: list[str]
        """
        if self.repo is None:
            return []
        full_prefix = f"{self.raw_data_path}/{prefix}"
        try:
            response = self.repo.get_client.list_objects_v2(Bucket=self.bucket_name, Prefix=full_prefix)
            return [obj["Key"] for obj in response.get("Contents", [])]
        except Exception as e:
            pipeline_logger.warning("Failed to list objects under %s: %s", full_prefix, e)
            return []


def get_minio_client(minio_config: dict = None) -> MinioClient:
    """Factory function to create a MinioClient from config.

    :param minio_config: MinIO config section from conf.yaml
    :type minio_config: dict or None
    :return: Configured MinioClient
    :rtype: MinioClient
    """
    if minio_config:
        return MinioClient(
            bucket_name=minio_config.get("BucketName", "iftbigdata"),
            raw_data_path=minio_config.get("RawDataPath", "raw-data"),
        )
    return MinioClient()
