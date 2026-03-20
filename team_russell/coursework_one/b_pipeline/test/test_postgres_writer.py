"""Unit tests for Pipeline B PostgreSQL writer module."""

from unittest.mock import MagicMock, patch

from modules.db_writer.postgres_writer import PostgresWriter


def _make_writer(mock_engine_cls):
    mock_engine = MagicMock()
    mock_engine_cls.return_value = mock_engine
    writer = PostgresWriter("localhost", 5432, "user", "pass", "fift")
    return writer, mock_engine


def _bind_conn(mock_engine):
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__ = lambda s: mock_conn
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


class TestPostgresWriterPrices:
    @patch("modules.db_writer.postgres_writer.create_engine")
    def test_upsert_prices_executes_sql(self, mock_engine_cls):
        writer, mock_engine = _make_writer(mock_engine_cls)
        mock_conn = _bind_conn(mock_engine)

        writer.upsert_prices(
            [
                {
                    "symbol": "AAPL",
                    "price_date": "2024-01-02",
                    "closing_price": 150.0,
                    "shares_outstanding": 1_000_000,
                }
            ]
        )

        mock_conn.execute.assert_called_once()

    @patch("modules.db_writer.postgres_writer.create_engine")
    def test_upsert_prices_empty_list_skips_execution(self, mock_engine_cls):
        writer, mock_engine = _make_writer(mock_engine_cls)
        writer.upsert_prices([])
        mock_engine.begin.assert_not_called()

    @patch("modules.db_writer.postgres_writer.create_engine")
    def test_upsert_prices_passes_all_records(self, mock_engine_cls):
        writer, mock_engine = _make_writer(mock_engine_cls)
        mock_conn = _bind_conn(mock_engine)

        records = [
            {
                "symbol": "AAPL",
                "price_date": "2024-01-02",
                "closing_price": 150.0,
                "shares_outstanding": 1_000_000,
            },
            {
                "symbol": "MSFT",
                "price_date": "2024-01-02",
                "closing_price": 300.0,
                "shares_outstanding": 2_000_000,
            },
        ]
        writer.upsert_prices(records)

        passed_records = mock_conn.execute.call_args[0][1]
        assert len(passed_records) == 2


class TestPostgresWriterFinancials:
    def _financial_record(self):
        return {
            "period_date": "2024-12-31",
            "total_assets": 500e6,
            "total_liabilities": 200e6,
            "net_income_ttm": 10e6,
            "ebitda_ttm": 20e6,
            "total_debt": 50e6,
            "cash_and_equivalents": 10e6,
            "book_value": 300e6,
            "revenue": 120e6,
            "gross_profit": 60e6,
            "free_cash_flow": 8e6,
            "current_assets": 80e6,
            "current_liabilities": 40e6,
            "annual_dividend_rate": 0.96,
        }

    @patch("modules.db_writer.postgres_writer.create_engine")
    def test_upsert_financials_executes_sql(self, mock_engine_cls):
        writer, mock_engine = _make_writer(mock_engine_cls)
        mock_conn = _bind_conn(mock_engine)

        writer.upsert_financials("AAPL", [self._financial_record()])

        mock_conn.execute.assert_called_once()

    @patch("modules.db_writer.postgres_writer.create_engine")
    def test_upsert_financials_empty_list_skips_execution(self, mock_engine_cls):
        writer, mock_engine = _make_writer(mock_engine_cls)
        writer.upsert_financials("AAPL", [])
        mock_engine.begin.assert_not_called()

    @patch("modules.db_writer.postgres_writer.create_engine")
    def test_upsert_financials_prepends_symbol_to_records(self, mock_engine_cls):
        writer, mock_engine = _make_writer(mock_engine_cls)
        mock_conn = _bind_conn(mock_engine)

        writer.upsert_financials("AAPL", [self._financial_record()])

        records = mock_conn.execute.call_args[0][1]
        assert records[0]["symbol"] == "AAPL"


class TestPostgresWriterConnectionUrl:
    @patch("modules.db_writer.postgres_writer.create_engine")
    def test_url_contains_host_and_database(self, mock_engine_cls):
        mock_engine_cls.return_value = MagicMock()
        PostgresWriter("myhost", 5439, "myuser", "mypass", "mydb")
        url = mock_engine_cls.call_args[0][0]
        assert "myhost" in url
        assert "mydb" in url
        assert "myuser" in url
