"""
Parquet Reader Coverage Tests
Tests for ParquetReader using tmp_path for file I/O.
"""
import logging
from io import BytesIO
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest


class TestParquetReaderInit:
    """Test ParquetReader initialization"""

    def test_init_with_minio_client(self):
        """Test initialization with MinIO client"""
        from modules.storage.parquet_reader import ParquetReader

        mock_client = MagicMock()
        reader = ParquetReader(mock_client, bucket="csreport")

        assert reader.client == mock_client
        assert reader.bucket == "csreport"

    def test_init_with_default_bucket(self):
        """Test initialization with default bucket"""
        from modules.storage.parquet_reader import ParquetReader

        mock_client = MagicMock()
        reader = ParquetReader(mock_client)

        assert reader.bucket == "csreport"


class TestParquetReaderReadParquet:
    """Test read_parquet functionality"""

    def test_read_parquet_success(self, tmp_path):
        """Test successful parquet file read"""
        from modules.storage.parquet_reader import ParquetReader

        # Create a real parquet file
        test_file = tmp_path / "test.parquet"
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "price": [150.0, 300.0],
                "volume": [1000000, 2000000],
            }
        )
        df.to_parquet(test_file, index=False)

        # Read it back with mocked client
        mock_client = MagicMock()
        with open(test_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_parquet("test.parquet")

        assert result is not None
        assert len(result) == 2
        assert list(result.columns) == ["symbol", "price", "volume"]
        assert result.iloc[0]["symbol"] == "AAPL"

    def test_read_parquet_file_not_found(self):
        """Test read_parquet with file not found"""
        from modules.storage.parquet_reader import ParquetReader

        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("File not found")

        reader = ParquetReader(mock_client)
        result = reader.read_parquet("nonexistent.parquet")

        assert result is None

    def test_read_parquet_corrupted_file(self):
        """Test read_parquet with corrupted parquet file"""
        from modules.storage.parquet_reader import ParquetReader

        mock_client = MagicMock()
        # Return corrupted data
        mock_client.get_object.return_value.read.return_value = b"corrupted data"

        reader = ParquetReader(mock_client)
        result = reader.read_parquet("corrupted.parquet")

        assert result is None

    def test_read_parquet_empty_file(self, tmp_path):
        """Test read_parquet with empty parquet file"""
        from modules.storage.parquet_reader import ParquetReader

        test_file = tmp_path / "empty.parquet"
        df = pd.DataFrame({"col1": [], "col2": []})
        df.to_parquet(test_file, index=False)

        mock_client = MagicMock()
        with open(test_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_parquet("empty.parquet")

        assert result is not None
        assert len(result) == 0
        assert list(result.columns) == ["col1", "col2"]


class TestParquetReaderReadUniverse:
    """Test read_universe functionality"""

    def test_read_universe_success(self, tmp_path):
        """Test reading company universe"""
        from modules.storage.parquet_reader import ParquetReader

        # Create universe parquet
        test_file = tmp_path / "universe.parquet"
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT", "GOOGL"],
                "sector": ["Tech", "Tech", "Tech"],
                "market_cap": [2800e9, 2200e9, 1800e9],
            }
        )
        df.to_parquet(test_file, index=False)

        mock_client = MagicMock()
        with open(test_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_universe(run_date="2026-02-19")

        assert result is not None
        assert len(result) == 3
        # Verify it called get_object with correct path
        mock_client.get_object.assert_called_once()
        call_args = mock_client.get_object.call_args
        assert "2026-02-19" in str(call_args)

    def test_read_universe_default_date(self, tmp_path):
        """Test reading universe with default date"""
        from modules.storage.parquet_reader import ParquetReader

        test_file = tmp_path / "universe.parquet"
        df = pd.DataFrame({"symbol": ["AAPL"]})
        df.to_parquet(test_file, index=False)

        mock_client = MagicMock()
        with open(test_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_universe()

        assert result is not None


class TestParquetReaderReadTickerPrices:
    """Test read_ticker_prices functionality"""

    def test_read_ticker_prices_success(self, tmp_path):
        """Test reading ticker prices"""
        from modules.storage.parquet_reader import ParquetReader

        test_file = tmp_path / "prices.parquet"
        df = pd.DataFrame(
            {
                "Date": pd.date_range("2021-01-01", periods=10),
                "Close": [100.0 + i for i in range(10)],
                "Volume": [1000000] * 10,
            }
        )
        df.to_parquet(test_file, index=False)

        mock_client = MagicMock()
        with open(test_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_ticker_prices("AAPL", 2021)

        assert result is not None
        assert len(result) == 10
        assert "Date" in result.columns or "Close" in result.columns

    def test_read_ticker_prices_not_found(self):
        """Test reading ticker prices when file not found"""
        from modules.storage.parquet_reader import ParquetReader

        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("Not found")

        reader = ParquetReader(mock_client)
        result = reader.read_ticker_prices("UNKNOWN", 2021)

        assert result is None


class TestParquetReaderReadFactorFeatures:
    """Test read_factor_features functionality"""

    def test_read_factor_features_success(self, tmp_path):
        """Test reading factor features"""
        from modules.storage.parquet_reader import ParquetReader

        test_file = tmp_path / "features.parquet"
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5),
                "momentum": [0.1, 0.15, 0.2, 0.18, 0.25],
                "volatility": [0.15, 0.16, 0.17, 0.16, 0.15],
            }
        )
        df.to_parquet(test_file, index=False)

        mock_client = MagicMock()
        with open(test_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_factor_features("momentum", "AAPL", 2021)

        assert result is not None
        assert len(result) == 5


class TestParquetReaderPreviewFile:
    """Test preview_file functionality if available"""

    def test_preview_file_if_exists(self, tmp_path):
        """Test preview_file method if it exists"""
        from modules.storage.parquet_reader import ParquetReader

        if not hasattr(ParquetReader, "preview_file"):
            pytest.skip("preview_file method not available")

        test_file = tmp_path / "test.parquet"
        df = pd.DataFrame({"col1": [1, 2, 3, 4, 5], "col2": ["a", "b", "c", "d", "e"]})
        df.to_parquet(test_file, index=False)

        mock_client = MagicMock()
        with open(test_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        # Should not raise exception
        reader.preview_file("test.parquet", n_rows=3)


class TestParquetReaderWithRealFiles:
    """Integration tests with real parquet files"""

    def test_roundtrip_write_read(self, tmp_path):
        """Test writing and reading parquet file"""
        from modules.storage.parquet_reader import ParquetReader

        # Write data
        write_file = tmp_path / "roundtrip.parquet"
        original_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT", "GOOGL"],
                "price": [150.0, 300.0, 100.0],
                "date": pd.date_range("2021-01-01", periods=3),
            }
        )
        original_df.to_parquet(write_file, index=False)

        # Read it back
        mock_client = MagicMock()
        with open(write_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        loaded_df = reader.read_parquet("roundtrip.parquet")

        assert loaded_df is not None
        assert len(loaded_df) == 3
        assert list(loaded_df["symbol"]) == ["AAPL", "MSFT", "GOOGL"]

    def test_read_large_parquet(self, tmp_path):
        """Test reading larger parquet file"""
        from modules.storage.parquet_reader import ParquetReader

        write_file = tmp_path / "large.parquet"
        df = pd.DataFrame(
            {
                "id": range(10000),
                "value": [i * 1.5 for i in range(10000)],
                "category": ["A", "B", "C"] * 3333 + ["A"],
            }
        )
        df.to_parquet(write_file, index=False)

        mock_client = MagicMock()
        with open(write_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_parquet("large.parquet")

        assert result is not None
        assert len(result) == 10000

    def test_read_parquet_with_nulls(self, tmp_path):
        """Test reading parquet with NULL values"""
        from modules.storage.parquet_reader import ParquetReader

        write_file = tmp_path / "nulls.parquet"
        df = pd.DataFrame(
            {
                "col1": [1.0, None, 3.0],
                "col2": ["a", "b", None],
                "col3": [True, False, None],
            }
        )
        df.to_parquet(write_file, index=False)

        mock_client = MagicMock()
        with open(write_file, "rb") as f:
            mock_client.get_object.return_value.read.return_value = f.read()

        reader = ParquetReader(mock_client)
        result = reader.read_parquet("nulls.parquet")

        assert result is not None
        assert result["col1"].isna().sum() == 1
        assert result["col2"].isna().sum() == 1
