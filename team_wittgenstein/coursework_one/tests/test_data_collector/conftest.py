"""Shared fixtures for data_collector tests."""

import pytest

from modules.input.data_collector import DataFetcher


@pytest.fixture
def fetcher(mock_minio_conn):
    """DataFetcher with mocked MinIO."""
    return DataFetcher(mock_minio_conn)
