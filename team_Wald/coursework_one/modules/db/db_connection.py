"""
Database connection module for Team Wald Coursework One.

Provides connection functions for PostgreSQL, MongoDB, and MinIO
using settings loaded from config/conf.yaml.

Usage::

    from modules.db.db_connection import get_postgres_conn, get_mongo_client, get_minio_client

    conn   = get_postgres_conn()
    client = get_mongo_client()
    minio  = get_minio_client()
"""

import logging
import os
from pathlib import Path

import psycopg2
import yaml
from minio import Minio
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load configuration from config/conf.yaml.

    :return: Parsed YAML configuration dictionary.
    :rtype: dict
    """
    config_path = Path(__file__).parents[2] / "config" / "conf.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

def get_postgres_conn() -> psycopg2.extensions.connection:
    """Create and return a PostgreSQL connection.

    Connection parameters are read from config/conf.yaml (postgresql section).
    Environment variables override config values when set:
    ``POSTGRES_HOST``, ``POSTGRES_PORT``, ``POSTGRES_USER``,
    ``POSTGRES_PASSWORD``, ``POSTGRES_DB``.

    :return: An open psycopg2 connection.
    :rtype: psycopg2.extensions.connection
    :raises psycopg2.OperationalError: If the connection cannot be established.

    Example::

        conn = get_postgres_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            print(cur.fetchone())
        conn.close()
    """
    cfg = _load_config()["postgresql"]

    params = {
        "host": os.getenv("POSTGRES_HOST", cfg["host"]),
        "port": int(os.getenv("POSTGRES_PORT", cfg["port"])),
        "user": os.getenv("POSTGRES_USER", cfg["user"]),
        "password": os.getenv("POSTGRES_PASSWORD", cfg["password"]),
        "dbname": os.getenv("POSTGRES_DB", cfg["database"]),
    }

    logger.info("Connecting to PostgreSQL at %s:%s", params["host"], params["port"])
    conn = psycopg2.connect(**params)
    logger.info("PostgreSQL connection established.")
    return conn


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------

def get_mongo_client() -> MongoClient:
    """Create and return a MongoDB client.

    Connection parameters are read from config/conf.yaml (mongodb section).
    Environment variables override config values when set:
    ``MONGO_HOST``, ``MONGO_PORT``.

    :return: A connected PyMongo MongoClient.
    :rtype: pymongo.MongoClient
    :raises pymongo.errors.ConnectionFailure: If the server is not reachable.

    Example::

        client = get_mongo_client()
        db = client["wald_db"]
        print(db.list_collection_names())
        client.close()
    """
    cfg = _load_config()["mongodb"]

    host = os.getenv("MONGO_HOST", cfg["host"])
    port = int(os.getenv("MONGO_PORT", cfg["port"]))

    logger.info("Connecting to MongoDB at %s:%s", host, port)
    client = MongoClient(host, port, serverSelectionTimeoutMS=5000)

    # Verify the connection is alive
    client.admin.command("ping")
    logger.info("MongoDB connection established.")
    return client


def get_mongo_db(client: MongoClient = None):
    """Return the configured MongoDB database object.

    :param client: Existing MongoClient; creates a new one if None.
    :type client: pymongo.MongoClient, optional
    :return: PyMongo database object.
    :rtype: pymongo.database.Database
    """
    if client is None:
        client = get_mongo_client()
    db_name = _load_config()["mongodb"]["database"]
    return client[db_name]


# ---------------------------------------------------------------------------
# MinIO
# ---------------------------------------------------------------------------

def get_minio_client() -> Minio:
    """Create and return a MinIO client.

    Connection parameters are read from config/conf.yaml (minio section).
    Environment variables override config values when set:
    ``MINIO_ENDPOINT``, ``MINIO_ACCESS_KEY``, ``MINIO_SECRET_KEY``.

    :return: A configured Minio client.
    :rtype: minio.Minio
    :raises Exception: If the endpoint is unreachable.

    Example::

        minio = get_minio_client()
        buckets = minio.list_buckets()
        for b in buckets:
            print(b.name)
    """
    cfg = _load_config()["minio"]

    endpoint = os.getenv("MINIO_ENDPOINT", cfg["endpoint"])
    access_key = os.getenv("MINIO_ACCESS_KEY", cfg["access_key"])
    secret_key = os.getenv("MINIO_SECRET_KEY", cfg["secret_key"])
    secure = cfg.get("secure", False)

    logger.info("Connecting to MinIO at %s", endpoint)
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    logger.info("MinIO client created.")
    return client


def ensure_bucket(client: Minio, bucket: str = None) -> str:
    """Ensure the configured MinIO bucket exists, creating it if necessary.

    :param client: An active Minio client.
    :type client: minio.Minio
    :param bucket: Bucket name; falls back to config value when None.
    :type bucket: str, optional
    :return: The bucket name.
    :rtype: str
    """
    if bucket is None:
        bucket = _load_config()["minio"]["bucket"]
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Created MinIO bucket: %s", bucket)
    else:
        logger.info("MinIO bucket already exists: %s", bucket)
    return bucket
