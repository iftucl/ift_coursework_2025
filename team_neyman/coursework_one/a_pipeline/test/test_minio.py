from unittest.mock import MagicMock, mock_open, patch

import pandas as pd

from a_pipeline.modules.db_loader.inspect_parquet import peek_at_minio
from a_pipeline.modules.db_loader.minio_loader import (
    load_config,
    upload_dataframe_to_parquet,
)


@patch(
    "builtins.open",
    new_callable=mock_open,
    read_data="minio:\n  endpoint: 'localhost'\n  access_key: 'user'\n  secret_key: 'pass'\n  secure: false\n  bucket_name: 'test'",
)
@patch("yaml.safe_load")
def test_load_config(mock_yaml, mock_file):
    mock_yaml.return_value = {"minio": {"bucket_name": "test"}}
    config = load_config()
    assert config["bucket_name"] == "test"


@patch("a_pipeline.modules.db_loader.minio_loader.Minio")
@patch("a_pipeline.modules.db_loader.minio_loader.load_config")
def test_upload_to_minio_success(mock_load_cfg, mock_minio_client):

    mock_load_cfg.return_value = {
        "endpoint": "localhost",
        "access_key": "x",
        "secret_key": "x",
        "secure": False,
        "bucket_name": "portfolio",
    }
    mock_client = MagicMock()
    mock_minio_client.return_value = mock_client
    mock_client.bucket_exists.return_value = False

    df = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})

    upload_dataframe_to_parquet(df, "test.parquet")

    mock_client.make_bucket.assert_called_once_with("portfolio")
    mock_client.put_object.assert_called_once()
    assert mock_client.put_object.call_args[1]["bucket_name"] == "portfolio"


@patch("a_pipeline.modules.db_loader.inspect_parquet.Minio")
@patch("a_pipeline.modules.db_loader.inspect_parquet.load_config")
@patch("pandas.read_parquet")
def test_peek_at_minio_with_date(mock_read, mock_load_cfg, mock_minio_client):

    mock_load_cfg.return_value = {
        "bucket_name": "portfolio",
        "endpoint": "x",
        "access_key": "x",
        "secret_key": "x",
        "secure": False,
    }
    mock_client = MagicMock()
    mock_minio_client.return_value = mock_client

    mock_response = MagicMock()
    mock_response.read.return_value = b"fake_parquet_content"
    mock_client.get_object.return_value = mock_response

    mock_read.return_value = pd.DataFrame({"test": [1, 2, 3]})

    peek_at_minio(target_date="2026-03-17", export=False)

    mock_client.get_object.assert_called_with(
        "portfolio", "target_companies_2026-03-17.parquet"
    )


@patch("a_pipeline.modules.db_loader.inspect_parquet.Minio")
@patch("a_pipeline.modules.db_loader.inspect_parquet.load_config")
def test_peek_at_minio_no_files(mock_load_cfg, mock_minio_client):
    mock_load_cfg.return_value = {
        "bucket_name": "portfolio",
        "endpoint": "x",
        "access_key": "x",
        "secret_key": "x",
        "secure": False,
    }
    mock_client = MagicMock()
    mock_minio_client.return_value = mock_client
    mock_client.list_objects.return_value = []

    peek_at_minio(target_date=None, export=False)

    mock_client.get_object.assert_not_called()
