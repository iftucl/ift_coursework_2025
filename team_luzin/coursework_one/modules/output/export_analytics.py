"""
Export Analytics Module

Handles exporting analytics, portfolios, and signals to MinIO and local storage.
Supports multiple formats: Parquet, CSV, JSON.
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class ExportAnalytics:
    """Export analytics, portfolios, and signals to various formats."""

    @staticmethod
    def to_parquet(
        df: pd.DataFrame, filepath: str, compression: str = "snappy"
    ) -> bool:
        """
        Export DataFrame to Parquet format.

        Args:
            df: DataFrame to export
            filepath: Output file path
            compression: Compression method (snappy/gzip/brotli)

        Returns:
            True if successful
        """
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(filepath, compression=compression)
            logger.info(f"✓ Exported {len(df)} rows to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error exporting to Parquet: {e}")
            return False

    @staticmethod
    def to_csv(df: pd.DataFrame, filepath: str, index: bool = False) -> bool:
        """
        Export DataFrame to CSV format.

        Args:
            df: DataFrame to export
            filepath: Output file path
            index: Include index in CSV

        Returns:
            True if successful
        """
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(filepath, index=index)
            logger.info(f"✓ Exported {len(df)} rows to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            return False

    @staticmethod
    def to_json(df: pd.DataFrame, filepath: str, orient: str = "records") -> bool:
        """
        Export DataFrame to JSON format.

        Args:
            df: DataFrame to export
            filepath: Output file path
            orient: JSON orientation (records/split/index/columns/values)

        Returns:
            True if successful
        """
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            df.to_json(filepath, orient=orient)
            logger.info(f"✓ Exported {len(df)} rows to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error exporting to JSON: {e}")
            return False

    @staticmethod
    def create_export_path(
        base_path: str,
        subfolder: str,
        filename_pattern: str,
        extension: str = "parquet",
    ) -> str:
        """
        Create standardized export path with timestamp.

        Args:
            base_path: Base export directory
            subfolder: Subdirectory (portfolio/signals/analytics)
            filename_pattern: Pattern with {date} placeholder
            extension: File extension

        Returns:
            Full filepath
        """
        date_str = datetime.now().strftime("%Y%m%d")
        filename = filename_pattern.format(date=date_str)
        path = Path(base_path) / subfolder / f"{filename}.{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
