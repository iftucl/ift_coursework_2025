"""
MinIO data storage module
Handles uploading metrics and data to MinIO object storage
"""

import io
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class MinIOStorage:
    """Store data in MinIO object storage."""

    def __init__(self, config: Dict):
        """
        Initialize MinIO connection.

        Args:
            config (dict): MinIO configuration with keys:
                - endpoint: MinIO endpoint (e.g., 'localhost:9000')
                - access_key: Access key ID
                - secret_key: Secret access key
                - bucket: Bucket name (e.g., 'csreport')
                - use_ssl: Whether to use SSL (default: False)
        """
        self.config = config
        self.endpoint = config.get("endpoint", "localhost:9000")
        self.access_key = config.get("access_key", "")
        self.secret_key = config.get("secret_key", "")
        self.bucket = config.get("bucket", "csreport")
        self.use_ssl = config.get("use_ssl", False)

        # Initialize MinIO client
        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.use_ssl,
        )

        logger.info(f"MinIO client initialized: {self.endpoint}")
        self.test_connection()

    def test_connection(self):
        """Test MinIO connection."""
        try:
            # List buckets to test connection
            self.client.list_buckets()
            logger.info("✓ Successfully connected to MinIO")
        except S3Error as e:
            logger.error(f"Failed to connect to MinIO: {e}")
            raise

    def upload_json(self, data: List[Dict], object_name: str) -> bool:
        """
        Upload data as JSON to MinIO.

        Args:
            data (List[Dict]): Data to upload
            object_name (str): Object path (e.g., 'momentum/2026-02-19/metrics.json')

        Returns:
            bool: True if successful
        """
        try:
            # Convert to JSON
            json_data = json.dumps(data, indent=2, default=str)
            json_bytes = json_data.encode("utf-8")

            # Upload to MinIO
            self.client.put_object(
                self.bucket,
                object_name,
                io.BytesIO(json_bytes),
                length=len(json_bytes),
                content_type="application/json",
            )

            logger.info(f"✓ Uploaded JSON to MinIO: s3://{self.bucket}/{object_name}")
            return True

        except S3Error as e:
            logger.error(f"Error uploading JSON to MinIO: {e}")
            return False

    def upload_csv(self, data: List[Dict], object_name: str) -> bool:
        """
        Upload data as CSV to MinIO.

        Args:
            data (List[Dict]): Data to upload
            object_name (str): Object path (e.g., 'momentum/2026-02-19/metrics.csv')

        Returns:
            bool: True if successful
        """
        try:
            # Convert to DataFrame and then CSV
            df = pd.DataFrame(data)
            csv_data = df.to_csv(index=False)
            csv_bytes = csv_data.encode("utf-8")

            # Upload to MinIO
            self.client.put_object(
                self.bucket,
                object_name,
                io.BytesIO(csv_bytes),
                length=len(csv_bytes),
                content_type="text/csv",
            )

            logger.info(f"✓ Uploaded CSV to MinIO: s3://{self.bucket}/{object_name}")
            return True

        except S3Error as e:
            logger.error(f"Error uploading CSV to MinIO: {e}")
            return False

    def upload_parquet(self, data: List[Dict], object_name: str) -> bool:
        """
        Upload data as Parquet to MinIO.

        Args:
            data (List[Dict]): Data to upload
            object_name (str): Object path (e.g., 'momentum/2026-02-19/metrics.parquet')

        Returns:
            bool: True if successful
        """
        try:
            # Convert to DataFrame and then Parquet
            df = pd.DataFrame(data)
            parquet_buffer = io.BytesIO()
            df.to_parquet(parquet_buffer, index=False)
            parquet_bytes = parquet_buffer.getvalue()

            # Upload to MinIO
            self.client.put_object(
                self.bucket,
                object_name,
                io.BytesIO(parquet_bytes),
                length=len(parquet_bytes),
                content_type="application/octet-stream",
            )

            logger.info(
                f"✓ Uploaded Parquet to MinIO: s3://{self.bucket}/{object_name}"
            )
            return True

        except S3Error as e:
            logger.error(f"Error uploading Parquet to MinIO: {e}")
            return False

    def save_momentum_metrics(
        self, metrics: List[Dict], run_date: Optional[str] = None
    ) -> bool:
        """
        Save momentum metrics in multiple formats.

        Args:
            metrics (List[Dict]): Momentum metrics to save
            run_date (str): Date string (default: today's date in YYYY-MM-DD format)

        Returns:
            bool: True if all uploads successful
        """
        if run_date is None:
            run_date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"\n📦 Saving {len(metrics)} momentum metrics to MinIO...")

        # Create consistent object paths
        base_path = f"momentum/{run_date}"

        results = []

        # Upload as JSON
        json_path = f"{base_path}/metrics.json"
        results.append(self.upload_json(metrics, json_path))

        # Upload as CSV
        csv_path = f"{base_path}/metrics.csv"
        results.append(self.upload_csv(metrics, csv_path))

        # Try Parquet (optional - may fail due to NumPy compatibility)
        parquet_path = f"{base_path}/metrics.parquet"
        try:
            results.append(self.upload_parquet(metrics, parquet_path))
        except Exception as e:
            logger.warning(f"Parquet upload skipped (optional): {e}")
            results.append(True)  # Don't fail the whole pipeline

        if all(results):
            logger.info("✓ Successfully saved momentum metrics to MinIO\n")
            return True
        else:
            logger.warning("⚠️ Some uploads failed\n")
            return False

    def save_by_industry(
        self, metrics_by_industry: Dict[str, List[Dict]], run_date: Optional[str] = None
    ) -> bool:
        """
        Save metrics organized by industry.

        Args:
            metrics_by_industry (Dict): Dictionary mapping industry names to metrics
            run_date (str): Date string (default: today's date)

        Returns:
            bool: True if all uploads successful
        """
        if run_date is None:
            run_date = datetime.now().strftime("%Y-%m-%d")

        logger.info("\n📦 Saving metrics by industry to MinIO...")

        all_successful = True

        for industry, metrics in metrics_by_industry.items():
            # Sanitize industry name for file path
            industry_safe = industry.replace(" ", "_").replace("&", "and").lower()
            base_path = f"momentum/{run_date}/by_industry/{industry_safe}"

            # Save in multiple formats
            json_path = f"{base_path}/metrics.json"
            csv_path = f"{base_path}/metrics.csv"

            success = self.upload_json(metrics, json_path)
            success = self.upload_csv(metrics, csv_path) and success

            all_successful = all_successful and success

        if all_successful:
            logger.info("✓ Successfully saved metrics by industry\n")

        return all_successful

    def list_objects(self, prefix: str = "momentum") -> List[str]:
        """
        List objects in the bucket.

        Args:
            prefix (str): Prefix to filter objects (default: 'momentum')

        Returns:
            List of object names
        """
        try:
            objects = self.client.list_objects(
                self.bucket, prefix=prefix, recursive=True
            )
            object_list = [obj.object_name for obj in objects]
            logger.info(f"Found {len(object_list)} objects with prefix '{prefix}'")
            return object_list

        except S3Error as e:
            logger.error(f"Error listing objects: {e}")
            return []
