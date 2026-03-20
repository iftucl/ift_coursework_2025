"""
Output module for analytics and signals export.

This module handles:
- Exporting analytics to MinIO data lake
- Writing reports and summary files
- Data serialization (Parquet, CSV, JSON)
"""

from .export_analytics import ExportAnalytics

__all__ = ["ExportAnalytics"]
