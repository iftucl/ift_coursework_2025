"""Unit tests for Pipeline A MinIO writer module."""

import json
from unittest.mock import MagicMock, patch

from modules.minio_writer.minio_writer import MinioRawWriter


def _make_writer(mock_minio_cls, bucket_exists=True):
    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = bucket_exists
    mock_minio_cls.return_value = mock_client
    writer = MinioRawWriter("localhost:9000", "key", "secret", "csreport")
    return writer, mock_client


class TestMinioRawWriterInit:
    @patch("modules.minio_writer.minio_writer.Minio")
    def test_creates_bucket_when_not_exists(self, mock_minio_cls):
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = False
        mock_minio_cls.return_value = mock_client

        MinioRawWriter("localhost:9000", "key", "secret", "csreport")

        mock_client.make_bucket.assert_called_once_with("csreport")

    @patch("modules.minio_writer.minio_writer.Minio")
    def test_does_not_create_bucket_when_already_exists(self, mock_minio_cls):
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_minio_cls.return_value = mock_client

        MinioRawWriter("localhost:9000", "key", "secret", "csreport")

        mock_client.make_bucket.assert_not_called()


class TestMinioRawWriterWrite:
    @patch("modules.minio_writer.minio_writer.Minio")
    def test_write_returns_path_with_correct_prefix(self, mock_minio_cls):
        writer, _ = _make_writer(mock_minio_cls)
        path = writer.write("AAPL", "prices", {"price": 150.0})
        assert path.startswith("russell/prices/AAPL_")
        assert path.endswith(".json")

    @patch("modules.minio_writer.minio_writer.Minio")
    def test_write_strips_symbol_whitespace_in_path(self, mock_minio_cls):
        writer, _ = _make_writer(mock_minio_cls)
        path = writer.write("  AAPL  ", "prices", {"price": 150.0})
        assert "AAPL_" in path
        assert "  " not in path

    @patch("modules.minio_writer.minio_writer.Minio")
    def test_write_uses_json_content_type(self, mock_minio_cls):
        writer, mock_client = _make_writer(mock_minio_cls)
        writer.write("AAPL", "prices", {"price": 150.0})
        kwargs = mock_client.put_object.call_args[1]
        assert kwargs["content_type"] == "application/json"

    @patch("modules.minio_writer.minio_writer.Minio")
    def test_write_uploads_valid_json_content(self, mock_minio_cls):
        writer, mock_client = _make_writer(mock_minio_cls)
        data = {"symbol": "AAPL", "price": 150.0}
        writer.write("AAPL", "prices", data)
        args = mock_client.put_object.call_args[0]
        uploaded_bytes = args[2].read()
        decoded = json.loads(uploaded_bytes.decode("utf-8"))
        assert decoded == data

    @patch("modules.minio_writer.minio_writer.Minio")
    def test_write_includes_data_type_in_path(self, mock_minio_cls):
        writer, _ = _make_writer(mock_minio_cls)
        path = writer.write("AAPL", "balance_sheet", {})
        assert "balance_sheet" in path
