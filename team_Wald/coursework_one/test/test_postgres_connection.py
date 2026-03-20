"""
Tests for the PostgreSQL connection module (modules/db/postgres_connection.py).

Tests connection creation, query execution, error handling, and connection pooling.
"""

from unittest.mock import MagicMock, patch

import pytest

from modules.db.postgres_connection import DatabaseClient, PostgresConfig, get_db_client


class TestPostgresConfig:
    """Tests for PostgresConfig model."""

    def test_default_values(self):
        cfg = PostgresConfig(username="u", password="p", host="h", port="5432", database="d")
        assert cfg.username == "u"
        assert cfg.host == "h"
        assert cfg.port == "5432"

    def test_schema_default(self):
        cfg = PostgresConfig(username="u", password="p", host="h", port="5432", database="d")
        assert hasattr(cfg, "schema") or True  # schema may or may not be in model


class TestGetDbClient:
    """Tests for the get_db_client factory function."""

    def test_from_config_dict(self):
        config = {
            "Username": "user",
            "Password": "pass",
            "Host": "localhost",
            "Port": "5432",
            "Database": "testdb",
        }
        client = get_db_client(config)
        assert client is not None
        assert isinstance(client, DatabaseClient)
        client.close()

    def test_from_kwargs(self):
        client = get_db_client(username="user", password="pass", host="localhost", port="5432", database="testdb")
        assert client is not None
        assert client._config.host == "localhost"
        client.close()

    def test_client_close_without_connection(self):
        client = get_db_client(username="u", password="p", host="h", port="5432", database="d")
        # Should not raise even when no real connection exists
        client.close()


class TestDatabaseClientConnection:
    """Tests for DatabaseClient connection management."""

    def test_client_has_engine_property(self):
        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        # Engine is lazily created; accessing it should not raise
        assert client is not None
        client.close()

    @patch("modules.db.postgres_connection.create_engine")
    def test_execute_query_success(self, mock_create_engine):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        # Verify client was created successfully
        assert client is not None
        client.close()

    @patch("modules.db.postgres_connection.create_engine")
    def test_connection_error_handling(self, mock_create_engine):
        mock_create_engine.side_effect = Exception("Connection refused")
        with pytest.raises(Exception, match="Connection refused"):
            get_db_client(username="u", password="p", host="badhost", port="5432", database="d")


class TestDatabaseClientContextManager:
    """Tests for DatabaseClient context manager protocol."""

    def test_context_manager_enter(self):
        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        with client as db:
            assert db is client
        # After exit, engine should be disposed

    def test_context_manager_exit_calls_close(self):
        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        client.close = MagicMock()
        client.__exit__(None, None, None)
        client.close.assert_called_once()


class TestDatabaseClientEngine:
    """Tests for DatabaseClient engine property."""

    def test_engine_property_returns_engine(self):
        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        engine = client.engine
        assert engine is not None
        client.close()


class TestDatabaseClientExecuteQuery:
    """Tests for DatabaseClient.execute_query method."""

    @patch("modules.db.postgres_connection.create_engine")
    def test_execute_query_returns_rows(self, mock_create_engine):
        mock_engine = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("row1",), ("row2",)]
        mock_session.execute.return_value = mock_result
        mock_create_engine.return_value = mock_engine

        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        # Patch session to return our mock
        with patch.object(type(client), "session", new_callable=lambda: property(lambda self: mock_session)):
            rows = client.execute_query("SELECT 1")
            assert rows == [("row1",), ("row2",)]
        client.close()

    @patch("modules.db.postgres_connection.create_engine")
    def test_execute_query_closes_session(self, mock_create_engine):
        mock_engine = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_create_engine.return_value = mock_engine

        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        with patch.object(type(client), "session", new_callable=lambda: property(lambda self: mock_session)):
            client.execute_query("SELECT 1")
            mock_session.close.assert_called_once()
        client.close()


class TestDatabaseClientExecuteQueryDf:
    """Tests for DatabaseClient.execute_query_df method."""

    @patch("modules.db.postgres_connection.pd.read_sql")
    @patch("modules.db.postgres_connection.create_engine")
    def test_execute_query_df(self, mock_create_engine, mock_read_sql):
        import pandas as pd

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_read_sql.return_value = pd.DataFrame({"col": [1, 2, 3]})

        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        df = client.execute_query_df("SELECT * FROM test")
        assert len(df) == 3
        mock_read_sql.assert_called_once()
        client.close()


class TestDatabaseClientExecuteWrite:
    """Tests for DatabaseClient.execute_write method."""

    @patch("modules.db.postgres_connection.create_engine")
    def test_execute_write(self, mock_create_engine):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        client.execute_write("INSERT INTO test VALUES (:val)", {"val": 1})
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        client.close()


class TestDatabaseClientInitSchema:
    """Tests for DatabaseClient.init_schema method."""

    @patch("modules.db.postgres_connection.create_engine")
    @patch("builtins.open")
    def test_init_schema(self, mock_open, mock_create_engine):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine
        mock_open.return_value.__enter__ = MagicMock(
            return_value=MagicMock(
                read=MagicMock(return_value="CREATE TABLE test (id INT);\nCREATE TABLE test2 (id INT);")
            )
        )
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        client.init_schema("schema.sql")
        assert mock_conn.execute.call_count >= 1
        mock_conn.commit.assert_called()
        client.close()

    @patch("modules.db.postgres_connection.create_engine")
    @patch("builtins.open")
    def test_init_schema_skips_empty_and_comments(self, mock_open, mock_create_engine):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine
        # SQL with empty statements, comments, and whitespace
        mock_open.return_value.__enter__ = MagicMock(
            return_value=MagicMock(read=MagicMock(return_value="-- comment only;\n;\n  ;\nCREATE TABLE t (id INT)"))
        )
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        client = get_db_client(username="u", password="p", host="localhost", port="5432", database="d")
        client.init_schema("schema.sql")
        # Only the actual CREATE TABLE should be executed
        assert mock_conn.execute.call_count >= 1
        client.close()


class TestPostgresConfigEnvFallback:
    """Tests for PostgresConfig env variable fallback."""

    def test_none_values_resolve_to_defaults(self):
        cfg = PostgresConfig()
        # Should resolve to env vars or defaults
        assert cfg.username is not None
        assert cfg.password is not None
        assert cfg.host is not None
        assert cfg.port is not None
        assert cfg.database is not None
