"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : MongoDB connection for news article document store
Project : CW1 - Value + News Sentiment Strategy

Stores raw GDELT/NewsAPI articles as semi-structured documents.
Uses lazy initialisation so the pipeline degrades gracefully
if MongoDB is unavailable.

Collections:
  - raw_news_articles  : fetched headline, description, source, url, tone
  - raw_financial_data : cached yfinance JSON responses
  - raw_price_history  : cached price DataFrames
"""

import os
from datetime import datetime, timezone
from typing import Optional

from modules.utils.logger import pipeline_logger

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure, OperationFailure

    PYMONGO_AVAILABLE = True
except ImportError:
    MongoClient = None
    ConnectionFailure = Exception
    OperationFailure = Exception
    PYMONGO_AVAILABLE = False


class MongoDBClient:
    """MongoDB client for the Value + Sentiment pipeline.

    Wraps PyMongo with lazy connection, graceful degradation,
    and convenience methods for CRUD operations on news documents.

    :param host: MongoDB host
    :type host: str
    :param port: MongoDB port
    :type port: int
    :param username: Auth username
    :type username: str
    :param password: Auth password
    :type password: str
    :param database: Target database name
    :type database: str
    """

    def __init__(
        self,
        host: str = None,
        port: int = None,
        username: str = None,
        password: str = None,
        database: str = "ift_cw1_sentiment",
    ):
        self.host = host or os.environ.get("MONGO_HOST", "localhost")
        self.port = port or int(os.environ.get("MONGO_PORT", "27019"))
        self.username = username or os.environ.get("MONGO_USERNAME", "ift_bigdata")
        self.password = password or os.environ.get("MONGO_PASSWORD", "mongo_password")
        self.database_name = database
        self._client = None
        self._db = None

    @property
    def client(self):
        """Lazy-initialise PyMongo client with connection verification.

        :return: MongoClient or None
        """
        if self._client is None:
            if not PYMONGO_AVAILABLE:
                pipeline_logger.warning("pymongo not installed — MongoDB disabled")
                return None
            try:
                self._client = MongoClient(
                    host=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    authSource="admin",
                    serverSelectionTimeoutMS=5000,
                )
                self._client.admin.command("ping")
                self._db = self._client[self.database_name]
                pipeline_logger.info("Connected to MongoDB at %s:%s", self.host, self.port)
            except (ConnectionFailure, OperationFailure, Exception) as e:
                pipeline_logger.warning("Could not connect to MongoDB: %s", e)
                self._client = None
                self._db = None
        return self._client

    @property
    def db(self):
        """Returns the MongoDB database handle, or None if unavailable."""
        if self.client is None:
            return None
        return self._db

    def get_collection(self, collection_name: str):
        """Get a MongoDB collection handle.

        :param collection_name: Name of the collection
        :type collection_name: str
        :return: Collection object or None
        """
        if self.db is None:
            return None
        return self.db[collection_name]

    def insert_documents(self, collection_name: str, documents: list[dict]) -> int:
        """Batch-insert documents into a collection.

        Adds ``fetched_at`` timestamp to each document for lineage tracking.

        :param collection_name: Target collection
        :type collection_name: str
        :param documents: List of document dicts
        :type documents: list[dict]
        :return: Number of documents inserted
        :rtype: int
        """
        if self.db is None or not documents:
            return 0
        try:
            now = datetime.now(timezone.utc)
            for doc in documents:
                doc["fetched_at"] = now
            result = self.db[collection_name].insert_many(documents)
            count = len(result.inserted_ids)
            pipeline_logger.info("Inserted %d documents into MongoDB:%s", count, collection_name)
            return count
        except Exception as e:
            pipeline_logger.warning("Failed to insert into %s: %s", collection_name, e)
            return 0

    def insert_one(self, collection_name: str, document: dict) -> Optional[str]:
        """Insert a single document.

        :param collection_name: Target collection
        :type collection_name: str
        :param document: Document dict
        :type document: dict
        :return: Inserted ID string or None
        :rtype: str or None
        """
        if self.db is None:
            return None
        try:
            document["fetched_at"] = datetime.now(timezone.utc)
            result = self.db[collection_name].insert_one(document)
            return str(result.inserted_id)
        except Exception as e:
            pipeline_logger.warning("Failed to insert document into %s: %s", collection_name, e)
            return None

    def query_documents(self, collection_name: str, query: dict, projection: dict = None, limit: int = 0) -> list:
        """Query documents from a collection.

        :param collection_name: Collection to query
        :type collection_name: str
        :param query: MongoDB filter dict
        :type query: dict
        :param projection: Fields to include/exclude
        :type projection: dict or None
        :param limit: Max documents to return (0 = unlimited)
        :type limit: int
        :return: List of matching documents
        :rtype: list[dict]
        """
        if self.db is None:
            return []
        try:
            cursor = self.db[collection_name].find(query, projection).limit(limit)
            return list(cursor)
        except Exception as e:
            pipeline_logger.warning("Failed to query %s: %s", collection_name, e)
            return []

    def update_document(self, collection_name: str, query: dict, update: dict) -> int:
        """Update documents matching a query.

        :param collection_name: Target collection
        :type collection_name: str
        :param query: MongoDB filter
        :type query: dict
        :param update: Update operations (e.g. ``{'$set': {...}}``)
        :type update: dict
        :return: Number of modified documents
        :rtype: int
        """
        if self.db is None:
            return 0
        try:
            result = self.db[collection_name].update_many(query, update)
            return result.modified_count
        except Exception as e:
            pipeline_logger.warning("Failed to update %s: %s", collection_name, e)
            return 0

    def close(self):
        """Close the MongoDB connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None


def get_mongo_client(mongo_config: dict = None) -> MongoDBClient:
    """Factory function to build a MongoDBClient from config dict.

    :param mongo_config: MongoDB config section from conf.yaml
    :type mongo_config: dict or None
    :return: Configured MongoDBClient
    :rtype: MongoDBClient
    """
    if mongo_config:
        return MongoDBClient(
            host=mongo_config.get("Host"),
            port=mongo_config.get("Port"),
            username=mongo_config.get("Username"),
            password=mongo_config.get("Password"),
            database=mongo_config.get("Database", "ift_cw1_sentiment"),
        )
    return MongoDBClient()
