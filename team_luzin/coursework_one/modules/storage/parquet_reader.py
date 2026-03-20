"""
Parquet Reader Utility
Read and inspect Parquet files stored in MinIO data lake.
"""

import io
import logging

import pandas as pd
from minio import Minio

logger = logging.getLogger(__name__)


class ParquetReader:
    """Read Parquet files from MinIO data lake."""

    def __init__(self, minio_client: Minio, bucket: str = "csreport"):
        """
        Initialize Parquet reader.

        Args:
            minio_client: Initialized Minio client
            bucket: Target bucket name
        """
        self.client = minio_client
        self.bucket = bucket

    def read_parquet(self, object_name: str):
        """
        Read a Parquet file from MinIO and return as DataFrame.

        Args:
            object_name: Full path to parquet file (e.g., datalake/prices/ticker=AAPL/year=2021/part-000.parquet)

        Returns:
            DataFrame or None if read fails
        """
        try:
            # Download from MinIO
            response = self.client.get_object(self.bucket, object_name)
            data = response.read()

            # Read into DataFrame
            df = pd.read_parquet(io.BytesIO(data))

            logger.info(
                f"✓ Read {object_name}: {len(df)} rows, {len(df.columns)} columns"
            )
            logger.info(f"  Columns: {list(df.columns)}")
            logger.info(f"  Shape: {df.shape}")

            return df

        except Exception as e:
            logger.error(f"Failed to read {object_name}: {e}")
            return None

    def read_universe(self, run_date: str = "2026-02-20"):
        """
        Read company universe for a specific run date.

        Args:
            run_date: Date string (YYYY-MM-DD)

        Returns:
            DataFrame with universe data
        """
        object_name = f"datalake/universe/run_date={run_date}/universe.parquet"
        return self.read_parquet(object_name)

    def read_ticker_prices(self, ticker: str, year: int):
        """
        Read price data for a specific ticker and year.

        Args:
            ticker: Stock ticker (e.g., 'AAPL')
            year: Year (e.g., 2021)

        Returns:
            DataFrame with price data
        """
        object_name = f"datalake/prices/ticker={ticker}/year={year}/part-000.parquet"
        return self.read_parquet(object_name)

    def read_factor_features(self, factor: str, ticker: str, year: int):
        """
        Read factor features for a specific ticker and year.

        Args:
            factor: Factor name (e.g., 'momentum')
            ticker: Stock ticker (e.g., 'AAPL')
            year: Year (e.g., 2021)

        Returns:
            DataFrame with feature data
        """
        object_name = f"datalake/features/factor={factor}/ticker={ticker}/year={year}/part-000.parquet"
        return self.read_parquet(object_name)

    def preview_file(self, object_name: str, n_rows: int = 5) -> None:
        """
        Preview a Parquet file (display first n rows).

        Args:
            object_name: Full path to parquet file
            n_rows: Number of rows to display
        """
        df = self.read_parquet(object_name)
        if df is not None:
            logger.info(f"\n📋 Preview of {object_name}:")
            logger.info(f"\n{df.head(n_rows).to_string()}")
            logger.info(f"\nData types:\n{df.dtypes}")

    def get_file_info(self, object_name: str) -> dict:
        """
        Get metadata about a Parquet file.

        Args:
            object_name: Full path to parquet file

        Returns:
            Dictionary with file information
        """
        try:
            df = self.read_parquet(object_name)
            if df is not None:
                info = {
                    "object_name": object_name,
                    "rows": len(df),
                    "columns": len(df.columns),
                    "column_names": list(df.columns),
                    "dtypes": dict(df.dtypes),
                    "memory_usage": df.memory_usage(deep=True).sum() / 1024**2,  # MB
                }
                return info
        except Exception as e:
            logger.error(f"Failed to get info: {e}")

        return {}
