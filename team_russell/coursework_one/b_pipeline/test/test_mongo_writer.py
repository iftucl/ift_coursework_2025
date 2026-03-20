"""Unit tests for Pipeline B MongoDB writer module."""

from unittest.mock import MagicMock, patch

from modules.db_writer.mongo_writer import MongoRawWriter


def _make_writer(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    writer = MongoRawWriter("localhost", 27017, "investment_data")
    return writer, mock_client


class TestMongoRawWriterUpsert:
    @patch("modules.db_writer.mongo_writer.MongoClient")
    def test_upsert_calls_update_one(self, mock_client_cls):
        writer, mock_client = _make_writer(mock_client_cls)
        writer.upsert("raw_prices", "AAPL", {"data": 1})
        col = mock_client.__getitem__.return_value.__getitem__.return_value
        col.update_one.assert_called_once()

    @patch("modules.db_writer.mongo_writer.MongoClient")
    def test_upsert_filters_by_symbol(self, mock_client_cls):
        writer, mock_client = _make_writer(mock_client_cls)
        writer.upsert("raw_prices", "AAPL", {"data": 1})
        col = mock_client.__getitem__.return_value.__getitem__.return_value
        filter_arg = col.update_one.call_args[0][0]
        assert filter_arg == {"symbol": "AAPL"}

    @patch("modules.db_writer.mongo_writer.MongoClient")
    def test_upsert_uses_set_operator(self, mock_client_cls):
        writer, mock_client = _make_writer(mock_client_cls)
        writer.upsert("raw_prices", "AAPL", {"data": 1})
        col = mock_client.__getitem__.return_value.__getitem__.return_value
        update_arg = col.update_one.call_args[0][1]
        assert "$set" in update_arg

    @patch("modules.db_writer.mongo_writer.MongoClient")
    def test_upsert_passes_upsert_true(self, mock_client_cls):
        writer, mock_client = _make_writer(mock_client_cls)
        writer.upsert("raw_prices", "AAPL", {"data": 1})
        col = mock_client.__getitem__.return_value.__getitem__.return_value
        _, kwargs = col.update_one.call_args
        assert kwargs.get("upsert") is True


class TestMongoRawWriterHelpers:
    @patch("modules.db_writer.mongo_writer.MongoClient")
    def test_upsert_prices_delegates_to_upsert(self, mock_client_cls):
        writer, mock_client = _make_writer(mock_client_cls)
        writer.upsert_prices("AAPL", {"prices": {}})
        col = mock_client.__getitem__.return_value.__getitem__.return_value
        col.update_one.assert_called_once()

    @patch("modules.db_writer.mongo_writer.MongoClient")
    def test_upsert_balance_sheet_delegates_to_upsert(self, mock_client_cls):
        writer, mock_client = _make_writer(mock_client_cls)
        writer.upsert_balance_sheet("MSFT", {"totalAssets": "1000000"})
        col = mock_client.__getitem__.return_value.__getitem__.return_value
        col.update_one.assert_called_once()

    @patch("modules.db_writer.mongo_writer.MongoClient")
    def test_upsert_income_statement_delegates_to_upsert(self, mock_client_cls):
        writer, mock_client = _make_writer(mock_client_cls)
        writer.upsert_income_statement("GOOG", {"netIncome": "500000"})
        col = mock_client.__getitem__.return_value.__getitem__.return_value
        col.update_one.assert_called_once()
