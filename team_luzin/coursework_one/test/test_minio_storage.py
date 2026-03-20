"""
MinIOStorage comprehensive tests targeting all code paths
"""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from minio.error import S3Error


class TestMinIOStorageCodePaths:
    """Comprehensive MinIOStorage tests for all code paths"""

    @patch("modules.storage.minio_storage.Minio")
    def test_init_defaults(self, mock_minio_class):
        """Test initialization with defaults"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_minio_class.return_value = mock_client

        config = {
            "endpoint": "localhost:9000",
            "access_key": "key",
            "secret_key": "secret",
        }
        storage = MinIOStorage(config)
        assert storage.bucket == "csreport"
        assert storage.use_ssl is False

    @patch("modules.storage.minio_storage.Minio")
    def test_init_custom(self, mock_minio_class):
        """Test initialization with custom config"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_minio_class.return_value = mock_client

        config = {
            "endpoint": "minio.example.com",
            "access_key": "key",
            "secret_key": "secret",
            "bucket": "custom",
            "use_ssl": True,
        }
        storage = MinIOStorage(config)
        assert storage.bucket == "custom"
        assert storage.use_ssl is True

    @patch("modules.storage.minio_storage.Minio")
    def test_upload_json(self, mock_minio_class):
        """Test JSON upload"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.upload_json([{"a": 1}], "test.json")
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_upload_csv(self, mock_minio_class):
        """Test CSV upload"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.upload_csv([{"a": 1}, {"a": 2}], "test.csv")
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_upload_parquet(self, mock_minio_class):
        """Test Parquet upload"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.upload_parquet([{"a": 1}], "test.parquet")
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_save_momentum_metrics_default_date(self, mock_minio_class):
        """Test save_momentum_metrics uses default date"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.save_momentum_metrics(
            [{"symbol": "AAPL", "momentum_12m": 0.5}]
        )
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_save_momentum_metrics_custom_date(self, mock_minio_class):
        """Test save_momentum_metrics uses custom date"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.save_momentum_metrics([{"symbol": "AAPL"}], "2026-02-19")
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_save_momentum_metrics_parquet_optional(self, mock_minio_class):
        """Test save_momentum_metrics handles parquet errors gracefully"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if "parquet" in args[1]:
                raise Exception("Parquet error")
            return MagicMock()

        mock_client.put_object.side_effect = side_effect
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.save_momentum_metrics([{"symbol": "AAPL"}])
        # Should succeed even with parquet error
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_save_by_industry_single(self, mock_minio_class):
        """Test save_by_industry with single industry"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        data = {"Software": [{"symbol": "AAPL"}]}
        result = storage.save_by_industry(data)
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_save_by_industry_multiple(self, mock_minio_class):
        """Test save_by_industry with multiple industries"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        data = {
            "Software": [{"symbol": "AAPL"}],
            "Semiconductors": [{"symbol": "NVDA"}],
            "Hardware & Equipment": [{"symbol": "CAT"}],
        }
        result = storage.save_by_industry(data)
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_save_by_industry_sanitizes_names(self, mock_minio_class):
        """Test save_by_industry sanitizes industry names"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        data = {"Hardware & Equipment": [{"symbol": "CAT"}]}
        result = storage.save_by_industry(data)

        # Check that sanitized name was used
        calls = mock_client.put_object.call_args_list
        assert any("hardware_and_equipment" in str(call) for call in calls)

    @patch("modules.storage.minio_storage.Minio")
    def test_save_by_industry_custom_date(self, mock_minio_class):
        """Test save_by_industry with custom date"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.put_object.return_value = MagicMock()
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        data = {"Software": [{"symbol": "AAPL"}]}
        result = storage.save_by_industry(data, "2026-02-20")
        assert result is True

    @patch("modules.storage.minio_storage.Minio")
    def test_list_objects_default_prefix(self, mock_minio_class):
        """Test list_objects with default prefix"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []

        mock_obj = MagicMock()
        mock_obj.object_name = "momentum/2026-02-19/metrics.json"
        mock_client.list_objects.return_value = [mock_obj]
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.list_objects()
        assert len(result) == 1
        assert result[0] == "momentum/2026-02-19/metrics.json"

    @patch("modules.storage.minio_storage.Minio")
    def test_list_objects_custom_prefix(self, mock_minio_class):
        """Test list_objects with custom prefix"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []

        mock_obj = MagicMock()
        mock_obj.object_name = "custom/file.txt"
        mock_client.list_objects.return_value = [mock_obj]
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.list_objects(prefix="custom")
        assert len(result) == 1

    @patch("modules.storage.minio_storage.Minio")
    def test_list_objects_empty(self, mock_minio_class):
        """Test list_objects with no results"""
        from modules.storage.minio_storage import MinIOStorage

        mock_client = MagicMock()
        mock_client.list_buckets.return_value = []
        mock_client.list_objects.return_value = []
        mock_minio_class.return_value = mock_client

        config = {"endpoint": "localhost:9000", "access_key": "k", "secret_key": "s"}
        storage = MinIOStorage(config)

        result = storage.list_objects()
        assert result == []
