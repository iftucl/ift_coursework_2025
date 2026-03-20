"""Unit tests for Pipeline A company loader module."""

from unittest.mock import MagicMock, patch

from modules.db_loader.company_loader import Company, load_companies


class TestCompany:
    def test_company_dataclass_stores_all_fields(self):
        c = Company("AAPL", "Apple Inc.", "Technology", "Tech Hardware", "USA", "North America")
        assert c.symbol == "AAPL"
        assert c.security == "Apple Inc."
        assert c.gics_sector == "Technology"
        assert c.gics_industry == "Tech Hardware"
        assert c.country == "USA"
        assert c.region == "North America"


class TestLoadCompanies:
    def _cfg(self):
        return {"user": "u", "password": "p", "host": "h", "port": 5432, "database": "db"}

    def _mock_engine(self, mock_engine_cls, rows):
        mock_conn = MagicMock()
        mock_conn.execute.return_value = rows
        mock_engine_cls.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine_cls.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn

    @patch("modules.db_loader.company_loader.create_engine")
    def test_returns_list_of_company_objects(self, mock_engine_cls):
        self._mock_engine(
            mock_engine_cls,
            [
                ("AAPL", "Apple Inc.", "Technology", "Tech Hardware", "USA", "North America"),
                ("MSFT", "Microsoft Corp.", "Technology", "Software", "USA", "North America"),
            ],
        )
        result = load_companies(self._cfg())
        assert len(result) == 2
        assert all(isinstance(c, Company) for c in result)

    @patch("modules.db_loader.company_loader.create_engine")
    def test_symbols_are_correct(self, mock_engine_cls):
        self._mock_engine(
            mock_engine_cls,
            [
                ("AAPL", "Apple Inc.", "Technology", "Tech Hardware", "USA", "North America"),
                ("MSFT", "Microsoft Corp.", "Technology", "Software", "USA", "North America"),
            ],
        )
        result = load_companies(self._cfg())
        assert result[0].symbol == "AAPL"
        assert result[1].symbol == "MSFT"

    @patch("modules.db_loader.company_loader.create_engine")
    def test_returns_empty_list_when_no_rows(self, mock_engine_cls):
        self._mock_engine(mock_engine_cls, [])
        result = load_companies(self._cfg())
        assert result == []

    @patch("modules.db_loader.company_loader.create_engine")
    def test_connection_url_contains_host_and_database(self, mock_engine_cls):
        self._mock_engine(mock_engine_cls, [])
        load_companies(
            {
                "user": "myuser",
                "password": "mypass",
                "host": "myhost",
                "port": 5439,
                "database": "mydb",
            }
        )
        url = mock_engine_cls.call_args[0][0]
        assert "myhost" in url
        assert "mydb" in url
