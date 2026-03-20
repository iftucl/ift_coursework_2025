"""
Tests for database connections, loading, and Kafka modules.
"""

from unittest.mock import MagicMock, PropertyMock, patch


class TestDatabaseClient:
    """Tests for PostgreSQL DatabaseClient."""

    def test_get_db_client_from_config(self):
        from modules.db.postgres_connection import get_db_client

        config = {"Username": "user", "Password": "pass", "Host": "localhost", "Port": "5432", "Database": "testdb"}
        client = get_db_client(config)
        assert client is not None
        assert client._config.username == "user"
        client.close()

    def test_get_db_client_from_kwargs(self):
        from modules.db.postgres_connection import get_db_client

        client = get_db_client(username="user", password="pass", host="localhost", port="5432", database="testdb")
        assert client._config.host == "localhost"
        client.close()


class TestMongoDBClient:
    """Tests for MongoDB client."""

    def test_init_defaults(self):
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        assert client.host == "localhost"
        assert client.database_name == "ift_cw1_sentiment"

    def test_init_custom(self):
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient(host="myhost", port=27018, database="mydb")
        assert client.host == "myhost"
        assert client.port == 27018
        assert client.database_name == "mydb"

    @patch("modules.db.mongo_connection.PYMONGO_AVAILABLE", False)
    def test_insert_documents_no_connection(self):
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient(host="nonexistent")
        client._client = None
        result = client.insert_documents("test", [{"a": 1}])
        assert result == 0

    @patch("modules.db.mongo_connection.PYMONGO_AVAILABLE", False)
    def test_query_documents_no_connection(self):
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient(host="nonexistent")
        client._client = None
        result = client.query_documents("test", {})
        assert result == []

    def test_factory_function(self):
        from modules.db.mongo_connection import get_mongo_client

        client = get_mongo_client({"Host": "myhost", "Port": 27018, "Database": "mydb"})
        assert client.host == "myhost"

    def test_factory_function_no_config(self):
        """Test get_mongo_client with no config returns defaults."""
        from modules.db.mongo_connection import get_mongo_client

        client = get_mongo_client(None)
        assert client.host == "localhost"
        assert client.database_name == "ift_cw1_sentiment"

    @patch("modules.db.mongo_connection.PYMONGO_AVAILABLE", True)
    @patch("modules.db.mongo_connection.MongoClient")
    def test_client_property_success(self, mock_mongo_cls):
        """Test successful MongoDB client lazy initialization."""
        from modules.db.mongo_connection import MongoDBClient

        mock_client_instance = MagicMock()
        mock_mongo_cls.return_value = mock_client_instance
        client = MongoDBClient(host="testhost", port=27017)
        result = client.client
        assert result is mock_client_instance
        mock_client_instance.admin.command.assert_called_once_with("ping")

    @patch("modules.db.mongo_connection.PYMONGO_AVAILABLE", True)
    @patch("modules.db.mongo_connection.MongoClient")
    def test_client_property_connection_failure(self, mock_mongo_cls):
        """Test MongoDB client when connection fails."""
        from modules.db.mongo_connection import MongoDBClient

        mock_mongo_cls.side_effect = Exception("Connection refused")
        client = MongoDBClient(host="badhost")
        result = client.client
        assert result is None

    @patch("modules.db.mongo_connection.PYMONGO_AVAILABLE", False)
    def test_client_property_pymongo_unavailable(self):
        """Test MongoDB client when pymongo is not installed."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        result = client.client
        assert result is None

    def test_db_property_when_client_none(self):
        """Test db property returns None when client is unavailable."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        client._client = None
        with patch.object(type(client), "client", new_callable=PropertyMock, return_value=None):
            assert client.db is None

    def test_db_property_when_client_available(self):
        """Test db property returns the database when client is connected."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_client = MagicMock()
        mock_db = MagicMock()
        client._client = mock_client
        client._db = mock_db
        result = client.db
        assert result is mock_db

    def test_get_collection_when_db_none(self):
        """Test get_collection returns None when db is unavailable."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        client._client = None
        with patch.object(type(client), "client", new_callable=PropertyMock, return_value=None):
            result = client.get_collection("test_collection")
            assert result is None

    def test_get_collection_success(self):
        """Test get_collection returns the collection when db is available."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        result = client.get_collection("test_collection")
        assert result is mock_collection

    def test_insert_documents_success(self):
        """Test successful batch insert of documents."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.inserted_ids = ["id1", "id2"]
        mock_collection.insert_many.return_value = mock_result
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        docs = [{"title": "Doc1"}, {"title": "Doc2"}]
        count = client.insert_documents("test_col", docs)
        assert count == 2

    def test_insert_documents_empty_list(self):
        """Test insert_documents with empty list returns 0."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        client._client = MagicMock()
        client._db = MagicMock()
        count = client.insert_documents("test_col", [])
        assert count == 0

    def test_insert_documents_exception(self):
        """Test insert_documents returns 0 on exception."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.insert_many.side_effect = Exception("Insert failed")
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        count = client.insert_documents("test_col", [{"title": "Doc1"}])
        assert count == 0

    def test_insert_one_success(self):
        """Test successful single document insert."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.inserted_id = "abc123"
        mock_collection.insert_one.return_value = mock_result
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        result = client.insert_one("test_col", {"title": "Doc1"})
        assert result == "abc123"

    def test_insert_one_when_db_none(self):
        """Test insert_one returns None when db is unavailable."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        client._client = None
        with patch.object(type(client), "client", new_callable=PropertyMock, return_value=None):
            result = client.insert_one("test_col", {"title": "Doc1"})
            assert result is None

    def test_insert_one_exception(self):
        """Test insert_one returns None on exception."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.insert_one.side_effect = Exception("Insert failed")
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        result = client.insert_one("test_col", {"title": "Doc1"})
        assert result is None

    def test_query_documents_success(self):
        """Test successful document query."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.limit.return_value = [{"title": "Doc1"}]
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        result = client.query_documents("test_col", {"title": "Doc1"}, limit=10)
        assert result == [{"title": "Doc1"}]

    def test_query_documents_exception(self):
        """Test query_documents returns empty list on exception."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find.side_effect = Exception("Query failed")
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        result = client.query_documents("test_col", {})
        assert result == []

    def test_update_document_success(self):
        """Test successful document update."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.modified_count = 3
        mock_collection.update_many.return_value = mock_result
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        count = client.update_document("test_col", {"status": "old"}, {"$set": {"status": "new"}})
        assert count == 3

    def test_update_document_when_db_none(self):
        """Test update_document returns 0 when db is unavailable."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        client._client = None
        with patch.object(type(client), "client", new_callable=PropertyMock, return_value=None):
            count = client.update_document("test_col", {}, {"$set": {"x": 1}})
            assert count == 0

    def test_update_document_exception(self):
        """Test update_document returns 0 on exception."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.update_many.side_effect = Exception("Update failed")
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        client._client = MagicMock()
        client._db = mock_db
        count = client.update_document("test_col", {}, {"$set": {"x": 1}})
        assert count == 0

    def test_close(self):
        """Test close method properly cleans up client."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        mock_pymongo = MagicMock()
        client._client = mock_pymongo
        client._db = MagicMock()
        client.close()
        mock_pymongo.close.assert_called_once()
        assert client._client is None
        assert client._db is None

    def test_close_when_not_connected(self):
        """Test close is safe when not connected."""
        from modules.db.mongo_connection import MongoDBClient

        client = MongoDBClient()
        client._client = None
        client.close()  # Should not raise


class TestMinioClient:
    """Tests for MinIO client."""

    def test_init_defaults(self):
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        assert client.bucket_name == "iftbigdata"
        assert client.raw_data_path == "raw-data"

    def test_factory_function(self):
        from modules.db.minio_connection import get_minio_client

        client = get_minio_client({"BucketName": "mybucket", "RawDataPath": "data"})
        assert client.bucket_name == "mybucket"
        assert client.raw_data_path == "data"

    def test_factory_function_no_config(self):
        """Test get_minio_client with no config returns defaults."""
        from modules.db.minio_connection import get_minio_client

        client = get_minio_client(None)
        assert client.bucket_name == "iftbigdata"
        assert client.raw_data_path == "raw-data"

    @patch("modules.db.minio_connection.MINIO_AVAILABLE", False)
    def test_repo_property_minio_unavailable(self):
        """Test repo returns None when ift_global is not installed."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        assert client.repo is None

    @patch("modules.db.minio_connection.MINIO_AVAILABLE", True)
    @patch("modules.db.minio_connection.MinioFileSystemRepo")
    def test_repo_property_success(self, mock_repo_cls):
        """Test repo property successfully initializes MinIO repo."""
        from modules.db.minio_connection import MinioClient

        mock_repo_instance = MagicMock()
        mock_repo_cls.return_value = mock_repo_instance
        client = MinioClient(bucket_name="testbucket")
        result = client.repo
        assert result is mock_repo_instance

    @patch("modules.db.minio_connection.MINIO_AVAILABLE", True)
    @patch("modules.db.minio_connection.MinioFileSystemRepo")
    def test_repo_property_connection_failure(self, mock_repo_cls):
        """Test repo returns None when connection fails."""
        from modules.db.minio_connection import MinioClient

        mock_repo_cls.side_effect = Exception("Connection refused")
        client = MinioClient()
        result = client.repo
        assert result is None

    def test_upload_json_when_repo_none(self):
        """Test upload_json returns early when repo is None."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        client._repo = None
        with patch.object(type(client), "repo", new_callable=PropertyMock, return_value=None):
            client.upload_json({"key": "val"}, "financial", "AAPL", "income.json")
            # No exception means it gracefully returned

    def test_upload_json_success(self):
        """Test successful JSON upload to MinIO."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        client._repo = mock_repo
        client.upload_json({"key": "value"}, "financial", "AAPL", "data.json")
        mock_repo.get_client.put_object.assert_called_once()

    def test_upload_json_exception(self):
        """Test upload_json handles exceptions gracefully."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        mock_repo.get_client.put_object.side_effect = Exception("Upload failed")
        client._repo = mock_repo
        # Should not raise
        client.upload_json({"key": "value"}, "financial", "AAPL", "data.json")

    def test_upload_csv_when_repo_none(self):
        """Test upload_csv returns early when repo is None."""
        import pandas as pd

        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        client._repo = None
        with patch.object(type(client), "repo", new_callable=PropertyMock, return_value=None):
            client.upload_csv(pd.DataFrame({"a": [1]}), "prices", "AAPL", "prices.csv")

    def test_upload_csv_success(self):
        """Test successful CSV upload to MinIO."""
        import pandas as pd

        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        client._repo = mock_repo
        df = pd.DataFrame({"Close": [150.0]}, index=pd.to_datetime(["2024-01-01"]))
        client.upload_csv(df, "prices", "AAPL", "daily_prices.csv")
        mock_repo.get_client.put_object.assert_called_once()

    def test_upload_csv_exception(self):
        """Test upload_csv handles exceptions gracefully."""
        import pandas as pd

        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        mock_repo.get_client.put_object.side_effect = Exception("Upload failed")
        client._repo = mock_repo
        client.upload_csv(pd.DataFrame({"a": [1]}), "prices", "AAPL", "prices.csv")

    def test_download_json_when_repo_none(self):
        """Test download_json returns empty dict when repo is None."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        client._repo = None
        with patch.object(type(client), "repo", new_callable=PropertyMock, return_value=None):
            result = client.download_json("financial", "AAPL", "data.json")
            assert result == {}

    def test_download_json_success(self):
        """Test successful JSON download from MinIO."""
        import json

        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        body_content = json.dumps({"key": "value"}).encode("utf-8")
        mock_body = MagicMock()
        mock_body.read.return_value = body_content
        mock_repo.get_client.get_object.return_value = {"Body": mock_body}
        client._repo = mock_repo
        result = client.download_json("financial", "AAPL", "data.json")
        assert result == {"key": "value"}

    def test_download_json_exception(self):
        """Test download_json returns empty dict on exception."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        mock_repo.get_client.get_object.side_effect = Exception("Not found")
        client._repo = mock_repo
        result = client.download_json("financial", "AAPL", "data.json")
        assert result == {}

    def test_list_objects_when_repo_none(self):
        """Test list_objects returns empty list when repo is None."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        client._repo = None
        with patch.object(type(client), "repo", new_callable=PropertyMock, return_value=None):
            result = client.list_objects("financial/AAPL")
            assert result == []

    def test_list_objects_success(self):
        """Test successful listing of objects from MinIO."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        mock_repo.get_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "raw-data/financial/AAPL/income.json"},
                {"Key": "raw-data/financial/AAPL/balance.json"},
            ]
        }
        client._repo = mock_repo
        result = client.list_objects("financial/AAPL")
        assert len(result) == 2
        assert "raw-data/financial/AAPL/income.json" in result

    def test_list_objects_empty_contents(self):
        """Test list_objects with no contents returns empty list."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        mock_repo.get_client.list_objects_v2.return_value = {}
        client._repo = mock_repo
        result = client.list_objects("financial/AAPL")
        assert result == []

    def test_list_objects_exception(self):
        """Test list_objects returns empty list on exception."""
        from modules.db.minio_connection import MinioClient

        client = MinioClient()
        mock_repo = MagicMock()
        mock_repo.get_client.list_objects_v2.side_effect = Exception("Error")
        client._repo = mock_repo
        result = client.list_objects("financial/AAPL")
        assert result == []


class TestSafeSerialise:
    """Tests for _safe_serialise helper function."""

    def test_dict_serialise(self):
        from modules.db.minio_connection import _safe_serialise

        result = _safe_serialise({"key": "value", "nested": {"a": 1}})
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_list_serialise(self):
        from modules.db.minio_connection import _safe_serialise

        result = _safe_serialise([1, "two", {"three": 3}])
        assert result == [1, "two", {"three": 3}]

    def test_timestamp_serialise(self):
        import pandas as pd

        from modules.db.minio_connection import _safe_serialise

        ts = pd.Timestamp("2024-01-01")
        result = _safe_serialise(ts)
        assert isinstance(result, str)
        assert "2024" in result

    def test_series_serialise(self):
        import pandas as pd

        from modules.db.minio_connection import _safe_serialise

        s = pd.Series([1, 2, 3])
        result = _safe_serialise(s)
        assert isinstance(result, str)

    def test_dataframe_serialise(self):
        import pandas as pd

        from modules.db.minio_connection import _safe_serialise

        df = pd.DataFrame({"a": [1, 2]})
        result = _safe_serialise(df)
        assert isinstance(result, str)

    def test_plain_value_passthrough(self):
        from modules.db.minio_connection import _safe_serialise

        assert _safe_serialise(42) == 42
        assert _safe_serialise("hello") == "hello"
        assert _safe_serialise(None) is None


class TestPostgresLoader:
    """Tests for PostgreSQL upsert operations."""

    def test_upsert_prices_empty(self, mock_db_client):
        from modules.loading.postgres_loader import upsert_daily_prices

        result = upsert_daily_prices(mock_db_client, [])
        assert result == 0

    def test_upsert_value_empty(self, mock_db_client):
        from modules.loading.postgres_loader import upsert_value_metrics

        result = upsert_value_metrics(mock_db_client, [])
        assert result == 0

    def test_upsert_sentiment_empty(self, mock_db_client):
        from modules.loading.postgres_loader import upsert_sentiment_scores

        result = upsert_sentiment_scores(mock_db_client, [])
        assert result == 0

    def test_upsert_composite_empty(self, mock_db_client):
        from modules.loading.postgres_loader import upsert_composite_rankings

        result = upsert_composite_rankings(mock_db_client, [])
        assert result == 0

    def test_upsert_fx_empty(self, mock_db_client):
        from modules.loading.postgres_loader import upsert_fx_rates

        result = upsert_fx_rates(mock_db_client, [])
        assert result == 0

    def test_upsert_prices_with_data(self, mock_db_client):
        from modules.loading.postgres_loader import upsert_daily_prices

        records = [
            {
                "symbol": "AAPL",
                "cob_date": "2024-01-02",
                "open_price": 150.0,
                "high_price": 152.0,
                "low_price": 149.0,
                "close_price": 151.0,
                "adj_close_price": 150.5,
                "volume": 1000000,
                "currency": "USD",
            }
        ]
        result = upsert_daily_prices(mock_db_client, records)
        assert result == 1

    def test_upsert_value_metrics_with_data(self, mock_db_client):
        """Test upsert_value_metrics with actual records."""
        from modules.loading.postgres_loader import upsert_value_metrics

        records = [
            {
                "company_id": "AAPL",
                "date": "2024-01-02",
                "pe_ratio": 28.5,
                "pb_ratio": 40.1,
                "ev_ebitda": 22.0,
                "dividend_yield": 0.005,
                "debt_equity": 1.5,
                "value_score": 65.0,
            }
        ]
        result = upsert_value_metrics(mock_db_client, records)
        assert result == 1
        mock_db_client.session.execute.assert_called()
        mock_db_client.session.commit.assert_called_once()

    def test_upsert_sentiment_scores_with_data(self, mock_db_client):
        """Test upsert_sentiment_scores with actual records."""
        from modules.loading.postgres_loader import upsert_sentiment_scores

        records = [
            {
                "company_id": "AAPL",
                "date": "2024-01-02",
                "avg_sentiment": 0.15,
                "positive_count": 5,
                "negative_count": 2,
                "neutral_count": 3,
                "total_articles": 10,
                "positive_ratio": 0.5,
                "sentiment_score": 72.0,
            }
        ]
        result = upsert_sentiment_scores(mock_db_client, records)
        assert result == 1

    def test_upsert_composite_rankings_with_data(self, mock_db_client):
        """Test upsert_composite_rankings with actual records."""
        from modules.loading.postgres_loader import upsert_composite_rankings

        records = [
            {
                "company_id": "AAPL",
                "date": "2024-01-02",
                "value_score": 65.0,
                "sentiment_score": 72.0,
                "composite_score": 68.5,
                "rank": 1,
                "invest_decision": "BUY",
            }
        ]
        result = upsert_composite_rankings(mock_db_client, records)
        assert result == 1

    def test_upsert_fx_rates_with_data(self, mock_db_client):
        """Test upsert_fx_rates with actual records."""
        from modules.loading.postgres_loader import upsert_fx_rates

        records = [
            {
                "currency_pair": "GBPUSD",
                "cob_date": "2024-01-02",
                "open_rate": 1.27,
                "high_rate": 1.28,
                "low_rate": 1.26,
                "close_rate": 1.275,
            }
        ]
        result = upsert_fx_rates(mock_db_client, records)
        assert result == 1

    def test_upsert_batch_exception_rollback(self, mock_db_client):
        """Test that batch upsert rolls back on exception."""
        from modules.loading.postgres_loader import upsert_daily_prices

        mock_db_client.session.execute.side_effect = Exception("DB Error")
        records = [
            {
                "symbol": "AAPL",
                "cob_date": "2024-01-02",
                "open_price": 150.0,
                "high_price": 152.0,
                "low_price": 149.0,
                "close_price": 151.0,
                "adj_close_price": 150.5,
                "volume": 1000000,
                "currency": "USD",
            }
        ]
        result = upsert_daily_prices(mock_db_client, records)
        assert result == 0
        mock_db_client.session.rollback.assert_called_once()

    def test_upsert_multiple_records(self, mock_db_client):
        """Test upsert with multiple records commits all."""
        from modules.loading.postgres_loader import upsert_daily_prices

        records = [
            {
                "symbol": "AAPL",
                "cob_date": "2024-01-02",
                "open_price": 150.0,
                "high_price": 152.0,
                "low_price": 149.0,
                "close_price": 151.0,
                "adj_close_price": 150.5,
                "volume": 1000000,
                "currency": "USD",
            },
            {
                "symbol": "MSFT",
                "cob_date": "2024-01-02",
                "open_price": 370.0,
                "high_price": 375.0,
                "low_price": 368.0,
                "close_price": 373.0,
                "adj_close_price": 372.0,
                "volume": 2000000,
                "currency": "USD",
            },
        ]
        result = upsert_daily_prices(mock_db_client, records)
        assert result == 2
        assert mock_db_client.session.execute.call_count == 2

    def test_insert_ingestion_log(self, mock_db_client):
        from modules.loading.postgres_loader import insert_ingestion_log

        # Should not raise
        insert_ingestion_log(
            mock_db_client,
            "test-run-id",
            "yfinance",
            symbol="AAPL",
            status="SUCCESS",
            rows_affected=100,
        )

    def test_insert_ingestion_log_exception(self, mock_db_client):
        """Test insert_ingestion_log handles exceptions gracefully."""
        from modules.loading.postgres_loader import insert_ingestion_log

        mock_db_client.session.execute.side_effect = Exception("DB Error")
        # Should not raise
        insert_ingestion_log(
            mock_db_client,
            "test-run-id",
            "yfinance",
            symbol="AAPL",
            status="FAILED",
            rows_affected=0,
            error_message="Something went wrong",
        )

    def test_insert_ingestion_log_all_params(self, mock_db_client):
        """Test insert_ingestion_log with all optional parameters."""
        from modules.loading.postgres_loader import insert_ingestion_log

        insert_ingestion_log(
            mock_db_client,
            "run-123",
            "gdelt",
            symbol="MSFT",
            status="SUCCESS",
            rows_affected=50,
            error_message=None,
            run_frequency="daily",
            date_range_start="2024-01-01",
            date_range_end="2024-12-31",
        )
        mock_db_client.session.execute.assert_called_once()
        mock_db_client.session.commit.assert_called_once()


class TestKafkaHandler:
    """Tests for Kafka event producer and consumer."""

    def test_producer_init(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer(bootstrap_servers="localhost:9092")
        assert producer.bootstrap_servers == "localhost:9092"

    def test_consumer_init(self):
        from modules.kafka.kafka_handler import EventConsumer

        consumer = EventConsumer(group_id="test-group", topics=["test-topic"])
        assert consumer.group_id == "test-group"
        assert consumer.topics == ["test-topic"]

    def test_factory_function(self):
        from modules.kafka.kafka_handler import get_event_producer

        producer = get_event_producer({"BootstrapServers": "kafka:29092"})
        assert producer.bootstrap_servers == "kafka:29092"

    def test_publish_no_connection(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        producer._producer = None
        # Should not raise when kafka is unavailable
        producer.publish_event("test", "key", {"data": 1})

    def test_publish_batch_empty(self):
        from modules.kafka.kafka_handler import EventProducer

        producer = EventProducer()
        producer.publish_batch("test", [])  # Should not raise
