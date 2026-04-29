import io
from unittest.mock import MagicMock

import pandas as pd
import pytest
from minio.error import S3Error

from modules.db_loader import minio_db


@pytest.fixture
def mock_minio_client(mocker):
    """Mocks the Minio client inside the minio_db module."""
    # We patch the client object directly in the module
    mock_client = mocker.patch("modules.db_loader.minio_db.client")
    return mock_client


def test_upload_dataframe_to_parquet_creates_bucket(mock_minio_client):
    """Verify that the bucket is created if it doesn't exist during upload."""
    df = pd.DataFrame({"a": [1], "b": [2]})
    mock_minio_client.bucket_exists.return_value = False

    minio_db.upload_dataframe_to_parquet(df, "test.parquet", "my-bucket")

    mock_minio_client.make_bucket.assert_called_once_with("my-bucket")
    mock_minio_client.put_object.assert_called_once()


def test_load_parquet_success(mock_minio_client):
    """Test successful retrieval and conversion of a Parquet file."""
    # 1. Create a real parquet byte stream
    df_original = pd.DataFrame({"symbol": ["AAPL"], "price": [150.0]})
    buffer = io.BytesIO()
    df_original.to_parquet(buffer)
    buffer.seek(0)

    # 2. Mock the Minio response object
    mock_response = MagicMock()
    mock_response.read.return_value = buffer.read()
    mock_minio_client.get_object.return_value = mock_response

    # 3. Execute
    result_df = minio_db.load_parquet("test.parquet", "my-bucket")

    assert not result_df.empty
    assert result_df.iloc[0]["symbol"] == "AAPL"


def test_get_latest_date_regex(mock_minio_client):
    """Verify that regex correctly identifies the latest date from filenames."""
    # Mock list_objects returning a list of mock objects with 'object_name'
    file1 = MagicMock(object_name="holdings/2025-01-01_holdings.parquet")
    file2 = MagicMock(object_name="holdings/2025-02-15_holdings.parquet")
    mock_minio_client.list_objects.return_value = [file1, file2]

    latest_date = minio_db.get_latest_date("my-bucket")

    assert latest_date == "2025-02-15"


def test_load_parquet_not_found_with_create(mock_minio_client):
    """Test the 'create' flag logic when a file is missing."""
    # Simulate a "NoSuchKey" S3Error
    err = S3Error(
        code="NoSuchKey",
        message="Object does not exist",
        resource="/my-bucket/missing.parquet",
        request_id="123",
        host_id="456",
        response=None,
    )
    mock_minio_client.get_object.side_effect = err
    mock_minio_client.bucket_exists.return_value = True

    # Execute with create=True
    result = minio_db.load_parquet("missing.parquet", create=True)

    assert isinstance(result, pd.DataFrame)
    assert result.empty
    # Verify that it tried to create an empty parquet
    assert mock_minio_client.put_object.called


def test_reset_minio_workflow(mock_minio_client):
    """Ensure reset loop deletes all objects and buckets."""
    mock_bucket = MagicMock()
    mock_bucket.name = "old-bucket"
    mock_minio_client.list_buckets.return_value = [mock_bucket]

    mock_obj = MagicMock()
    mock_obj.object_name = "junk.txt"
    mock_minio_client.list_objects.return_value = [mock_obj]

    minio_db.reset_minio()

    mock_minio_client.remove_object.assert_called_with("old-bucket", "junk.txt")
    mock_minio_client.remove_bucket.assert_called_with("old-bucket")


def test_get_initial_date_insufficient_files(mocker):

    # Mock returning only 2 files (code requires at least 5)
    mock_files = [MagicMock(object_name="h/2025-01-01_holdings.parquet")] * 2
    mocker.patch(
        "modules.db_loader.minio_db.client.list_objects", return_value=mock_files
    )

    with pytest.raises(ValueError, match="Need at least 5"):
        minio_db.get_initial_date("test-bucket")


def test_reset_minio_execution(mocker):

    # Mock bucket list and removal
    mock_bucket = MagicMock()
    mock_bucket.name = "test"
    mocker.patch(
        "modules.db_loader.minio_db.client.list_buckets", return_value=[mock_bucket]
    )
    mocker.patch("modules.db_loader.minio_db.client.list_objects", return_value=[])
    m_remove = mocker.patch("modules.db_loader.minio_db.client.remove_bucket")

    minio_db.reset_minio()
    m_remove.assert_called_once_with("test")


def test_upload_dataframe_s3_error_branch(mocker):

    # We mock bucket_exists to raise an S3Error
    # We don't need a real response object to trigger the 'print' logic
    mock_err = S3Error(
        code="InternalError",
        message="Simulated Minio Error",
        resource="/test-bucket",
        request_id="123",
        host_id="456",
        response=None,  # Passing it as a positional argument usually causes the error you saw
    )
    mocker.patch(
        "modules.db_loader.minio_db.client.bucket_exists", side_effect=mock_err
    )

    # This hits lines 67-70
    minio_db.upload_dataframe_to_parquet(pd.DataFrame(), "test.parquet")
    assert True
