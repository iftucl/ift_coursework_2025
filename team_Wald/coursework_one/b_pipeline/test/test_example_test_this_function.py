"""
Integration tests for database connection module.

Tests verify live connectivity to PostgreSQL, MongoDB, and MinIO.
Run with: poetry run pytest b_pipeline/test/test_db_connection.py -v
"""

import pytest
import psycopg2
from pymongo.errors import ConnectionFailure
from minio import Minio

from modules.db_loader.db_connection import (
    get_postgres_conn,
    get_mongo_client,
    get_mongo_db,
    get_minio_client,
    ensure_bucket,
)


class TestPostgresConnection:
    """Tests for PostgreSQL connectivity."""

    def test_connection_returns_conn_object(self):
        """get_postgres_conn() should return a psycopg2 connection."""
        conn = get_postgres_conn()
        assert conn is not None
        assert isinstance(conn, psycopg2.extensions.connection)
        conn.close()

    def test_connection_is_open(self):
        """Connection should be open (closed == 0)."""
        conn = get_postgres_conn()
        assert conn.closed == 0
        conn.close()

    def test_can_execute_query(self):
        """Should be able to run a simple SELECT query."""
        conn = get_postgres_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            result = cur.fetchone()
        conn.close()
        assert result == (1,)


class TestMongoConnection:
    """Tests for MongoDB connectivity."""

    def test_client_returns_mongo_client(self):
        """get_mongo_client() should return a MongoClient."""
        from pymongo import MongoClient
        client = get_mongo_client()
        assert isinstance(client, MongoClient)
        client.close()

    def test_ping_succeeds(self):
        """Server ping should not raise ConnectionFailure."""
        client = get_mongo_client()
        try:
            result = client.admin.command("ping")
            assert result.get("ok") == 1.0
        finally:
            client.close()

    def test_get_mongo_db_returns_database(self):
        """get_mongo_db() should return the configured database object."""
        from pymongo.database import Database
        client = get_mongo_client()
        db = get_mongo_db(client)
        assert isinstance(db, Database)
        client.close()


class TestMinioConnection:
    """Tests for MinIO connectivity."""

    def test_client_returns_minio_instance(self):
        """get_minio_client() should return a Minio instance."""
        client = get_minio_client()
        assert isinstance(client, Minio)

    def test_can_list_buckets(self):
        """Should be able to list buckets without exception."""
        client = get_minio_client()
        buckets = client.list_buckets()
        assert isinstance(buckets, list)

    def test_ensure_bucket_creates_or_exists(self):
        """ensure_bucket() should return the bucket name."""
        client = get_minio_client()
        bucket_name = ensure_bucket(client)
        assert isinstance(bucket_name, str)
        assert len(bucket_name) > 0
        assert client.bucket_exists(bucket_name)
