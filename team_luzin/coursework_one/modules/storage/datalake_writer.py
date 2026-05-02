"""
Data Lake Writer Module

Handles partitioned storage of company universe, prices, and features
using Hive-style partitioning in MinIO.

Structure:
  datalake/
    universe/
      run_date=YYYY-MM-DD/
        universe.parquet
    
    prices/
      ticker=<TICKER>/
        year=YYYY/
          part-000.parquet
    
    features/
      factor=<FACTOR>/
        ticker=<TICKER>/
          year=YYYY/
            part-000.parquet
"""

import io
import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from minio import Minio

logger = logging.getLogger(__name__)


class DataLakeWriter:
    """Write data to MinIO data lake with Hive-style partitioning."""

    def __init__(self, minio_client: Minio, bucket: str = "csreport"):
        """
        Initialize data lake writer.

        Args:
            minio_client: Initialized Minio client
            bucket: Target bucket name (default: csreport)
        """
        self.client = minio_client
        self.bucket = bucket
        logger.info(f"DataLakeWriter initialized for bucket: {bucket}")

    def write_universe(
        self, companies_df: pd.DataFrame, run_date: Optional[str] = None
    ) -> bool:
        """
        Write company universe to datalake/universe/run_date=YYYY-MM-DD/universe.parquet

        Args:
            companies_df: DataFrame with company information
            run_date: Date string (default: today's date)

        Returns:
            bool: True if successful
        """
        if run_date is None:
            run_date = datetime.now().strftime("%Y-%m-%d")

        try:
            # Create partitioned path
            object_name = f"datalake/universe/run_date={run_date}/universe.parquet"

            # Convert to parquet in memory
            buffer = io.BytesIO()
            companies_df.to_parquet(buffer, index=False, engine="pyarrow")
            buffer.seek(0)

            # Upload to MinIO
            self.client.put_object(
                self.bucket,
                object_name,
                buffer,
                len(buffer.getvalue()),
                content_type="application/octet-stream",
            )

            logger.info(
                f"✓ Uploaded company universe to MinIO: s3://{self.bucket}/{object_name}"
            )
            logger.info(f"  Companies stored: {len(companies_df)}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to write universe: {e}")
            return False

    def write_prices(
        self, prices_by_ticker: Dict[str, pd.DataFrame], run_date: Optional[str] = None
    ) -> bool:
        """
        Write price data to datalake/prices/ticker=<TICKER>/year=YYYY/part-000.parquet

        Args:
            prices_by_ticker: Dict mapping ticker -> DataFrame with price data (must have 'Date' column)
            run_date: Date string (default: today's date)

        Returns:
            bool: True if all uploads successful
        """
        if run_date is None:
            run_date = datetime.now().strftime("%Y-%m-%d")

        results = []

        for ticker, df in prices_by_ticker.items():
            try:
                # Make a copy and ensure Date is in columns
                df_copy = df.copy()

                # If Date is in index, reset it to column
                if df_copy.index.name == "Date" or isinstance(
                    df_copy.index, pd.DatetimeIndex
                ):
                    df_copy = df_copy.reset_index()

                # Ensure Date column exists and is datetime
                if "Date" not in df_copy.columns:
                    # Try to find date column
                    date_cols = [
                        col for col in df_copy.columns if "date" in col.lower()
                    ]
                    if date_cols:
                        df_copy.rename(columns={date_cols[0]: "Date"}, inplace=True)

                if "Date" in df_copy.columns:
                    df_copy["Date"] = pd.to_datetime(df_copy["Date"])
                    years = df_copy["Date"].dt.year.unique()
                else:
                    # No date found, treat all as single year
                    years = [datetime.now().year]

                # Write each year partition
                for year in sorted(years):
                    if "Date" in df_copy.columns:
                        year_df = df_copy[df_copy["Date"].dt.year == year].copy()
                    else:
                        year_df = df_copy.copy()

                    if len(year_df) == 0:
                        continue

                    # Create partitioned path
                    object_name = (
                        f"datalake/prices/ticker={ticker}/year={year}/part-000.parquet"
                    )

                    # Convert to parquet in memory
                    buffer = io.BytesIO()
                    year_df.to_parquet(buffer, index=False, engine="pyarrow")
                    buffer.seek(0)

                    # Upload to MinIO
                    self.client.put_object(
                        self.bucket,
                        object_name,
                        buffer,
                        len(buffer.getvalue()),
                        content_type="application/octet-stream",
                    )

                    logger.info(
                        f"✓ Uploaded {ticker} {year} prices: s3://{self.bucket}/{object_name}"
                    )
                    logger.info(f"  Records: {len(year_df)}")
                    results.append(True)

            except Exception as e:
                logger.error(f"❌ Failed to write prices for {ticker}: {e}")
                results.append(False)

        if all(results):
            logger.info(
                f"✓ Successfully wrote price data for {len(prices_by_ticker)} tickers"
            )
            return True
        else:
            logger.warning("⚠️ Some price uploads failed")
            return False

    def write_features(
        self,
        metrics_by_ticker_year: Dict[str, Dict[int, pd.DataFrame]],
        factor_name: str = "momentum",
        run_date: Optional[str] = None,
    ) -> bool:
        """
        Write feature data to datalake/features/factor=<FACTOR>/ticker=<TICKER>/year=YYYY/part-000.parquet

        Args:
            metrics_by_ticker_year: Dict mapping ticker -> {year -> DataFrame of metrics}
            factor_name: Feature name (e.g., 'momentum', 'volatility')
            run_date: Date string (default: today's date)

        Returns:
            bool: True if all uploads successful
        """
        if run_date is None:
            run_date = datetime.now().strftime("%Y-%m-%d")

        results = []

        for ticker, year_dict in metrics_by_ticker_year.items():
            for year, df in year_dict.items():
                try:
                    # Create partitioned path
                    object_name = f"datalake/features/factor={factor_name}/ticker={ticker}/year={year}/part-000.parquet"

                    # Convert to parquet in memory
                    buffer = io.BytesIO()
                    df.to_parquet(buffer, index=False, engine="pyarrow")
                    buffer.seek(0)

                    # Upload to MinIO
                    self.client.put_object(
                        self.bucket,
                        object_name,
                        buffer,
                        len(buffer.getvalue()),
                        content_type="application/octet-stream",
                    )

                    logger.info(
                        f"✓ Uploaded {factor_name} {ticker} {year}: s3://{self.bucket}/{object_name}"
                    )
                    logger.info(f"  Records: {len(df)}")
                    results.append(True)

                except Exception as e:
                    logger.error(
                        f"❌ Failed to write {factor_name} for {ticker} {year}: {e}"
                    )
                    results.append(False)

        if all(results):
            logger.info(f"✓ Successfully wrote {factor_name} features")
            return True
        else:
            logger.warning("⚠️ Some feature uploads failed")
            return False

    def list_datalake_objects(self, prefix: str = "datalake/") -> List[str]:
        """
        List all objects in data lake.

        Args:
            prefix: Object prefix to search under

        Returns:
            List of object names
        """
        try:
            objects = self.client.list_objects(
                self.bucket, prefix=prefix, recursive=True
            )
            object_list = [obj.object_name for obj in objects]
            logger.info(f"Found {len(object_list)} objects in {prefix}")
            return object_list
        except Exception as e:
            logger.error(f"Failed to list objects: {e}")
            return []
