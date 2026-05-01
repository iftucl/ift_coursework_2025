"""Store raw API responses in MongoDB for audit and reprocessing."""

import logging

from pymongo import MongoClient

logger = logging.getLogger(__name__)


class MongoRawWriter:
    """Upserts raw data documents into MongoDB by symbol.

    Collections:
        raw_prices          — yfinance price payloads
        raw_balance_sheet   — Alpha Vantage balance sheet payloads
        raw_income_statement — Alpha Vantage income statement payloads

    Args:
        host: MongoDB host.
        port: MongoDB port.
        database: Database name.
    """

    def __init__(self, host: str, port: int, database: str) -> None:
        self._client = MongoClient(host, port)
        self._db = self._client[database]

    def upsert(self, collection: str, symbol: str, document: dict) -> None:
        """Upsert a document into a collection keyed by symbol.

        Args:
            collection: Target MongoDB collection name.
            symbol: Ticker symbol used as the document key.
            document: Data to store.
        """
        self._db[collection].update_one(
            {"symbol": symbol},
            {"$set": document},
            upsert=True,
        )
        logger.debug(f"Upserted {symbol} into MongoDB collection '{collection}'")

    def upsert_prices(self, symbol: str, data: dict) -> None:
        self.upsert("raw_prices", symbol, data)

    def upsert_balance_sheet(self, symbol: str, data: dict) -> None:
        self.upsert("raw_balance_sheet", symbol, data)

    def upsert_income_statement(self, symbol: str, data: dict) -> None:
        self.upsert("raw_income_statement", symbol, data)
