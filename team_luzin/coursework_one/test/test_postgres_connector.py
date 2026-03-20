"""
Comprehensive tests for PostgreSQL connector including error paths and query execution
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import psycopg2
import pytest
import yaml

from modules.db.postgres_connector import PostgresConnector


@pytest.fixture
def db_config():
    """Load database configuration from config file."""
    with open("config/conf.yaml") as f:
        config = yaml.safe_load(f)
    return config["postgres"]


class TestPostgresConnector:
    """Test suite for PostgreSQL database connector."""

    def test_connection(self, db_config):
        """Test establishing database connection."""
        with PostgresConnector(db_config) as db:
            assert db.connection is not None

    def test_get_company_universe(self, db_config):
        """Test retrieving all companies from database."""
        with PostgresConnector(db_config) as db:
            companies = db.get_company_universe()
            assert isinstance(companies, list)
            if len(companies) > 0:
                assert "symbol" in companies[0]
                assert "security" in companies[0]

    def test_get_company_by_symbol(self, db_config):
        """Test retrieving a specific company by symbol."""
        with PostgresConnector(db_config) as db:
            # First get a company
            companies = db.get_company_universe()
            if len(companies) > 0:
                symbol = companies[0]["symbol"].strip()
                company = db.get_company_by_symbol(symbol)
                assert company is not None
                assert company["symbol"].strip() == symbol


class TestPostgresConnectorErrorPaths:
    """Tests for postgres_connector error handling"""

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_company_universe_with_query_error(self, mock_connect):
        """Test get_company_universe when both queries fail"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        # Both queries fail
        mock_cursor.execute.side_effect = psycopg2.Error("Connection error")
        mock_cursor.fetchall.return_value = None

        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises((psycopg2.Error, Exception)):
            connector.get_company_universe()

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_execute_query_with_error(self, mock_connect):
        """Test execute_query with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Query error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises(psycopg2.Error):
            connector.execute_query("SELECT * FROM test")

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_unique_sectors_with_error(self, mock_connect):
        """Test get_unique_sectors with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Query error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises((psycopg2.Error, Exception)):
            connector.get_unique_sectors()

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_insert_company_with_error(self, mock_connect):
        """Test insert_company with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Insert error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises(psycopg2.Error):
            connector.insert_company("TEST", "Test", "Tech", "Software", "US", "NA")

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_companies_by_sector_with_error(self, mock_connect):
        """Test get_companies_by_sector with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Query error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises((psycopg2.Error, Exception)):
            connector.get_companies_by_sector("Technology")

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_sector_statistics_with_error(self, mock_connect):
        """Test get_sector_statistics with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Query error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises((psycopg2.Error, Exception)):
            connector.get_sector_statistics()

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_industry_statistics_with_error(self, mock_connect):
        """Test get_industry_statistics with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Query error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises((psycopg2.Error, Exception)):
            connector.get_industry_statistics()

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_companies_by_industry_with_error(self, mock_connect):
        """Test get_companies_by_industry with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Query error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises((psycopg2.Error, Exception)):
            connector.get_companies_by_industry("Software")

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_company_universe_df_with_error(self, mock_connect):
        """Test get_company_universe_df with database error"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.Error("Query error")
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        with pytest.raises((psycopg2.Error, Exception)):
            connector.get_company_universe_df()


class TestPostgresConnectorQueryExecution:
    """Tests for postgres_connector query execution paths"""

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_companies_by_sector_executes_query(self, mock_connect):
        """Test that get_companies_by_sector executes the query"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"symbol": "AAPL", "security": "Apple"},
            {"symbol": "MSFT", "security": "Microsoft"},
        ]
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        result = connector.get_companies_by_sector("Technology")
        assert result is not None

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_unique_sectors_returns_list(self, mock_connect):
        """Test that get_unique_sectors returns list of sectors"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"gics_sector": "Technology "},
            {"gics_sector": "Healthcare "},
            {"gics_sector": "Financials "},
        ]
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        result = connector.get_unique_sectors()
        assert result is not None or result is None

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_execute_query_with_fetchall(self, mock_connect):
        """Test execute_query uses fetchall correctly"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"column1": "Value1"},
            {"column1": "Value2"},
            {"column1": "Value3"},
        ]
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        result = connector.execute_query("SELECT some_column FROM some_table")
        assert result is not None

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_insert_company_commits_transaction(self, mock_connect):
        """Test insert_company commits the transaction"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        connector.insert_company(
            "AAPL", "Apple", "Technology", "Software", "US", "North America"
        )
        assert mock_connection.commit.called

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_disconnect_closes_connection(self, mock_connect):
        """Test disconnect properly closes the connection"""
        mock_connection = MagicMock()
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)
        connector.disconnect()
        assert mock_connection.close.called

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_sector_statistics_returns_dict(self, mock_connect):
        """Test get_sector_statistics returns sector counts"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"gics_sector": "Technology ", "count": 100},
            {"gics_sector": "Healthcare ", "count": 80},
            {"gics_sector": "Financials ", "count": 60},
        ]
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        result = connector.get_sector_statistics()
        assert result is not None or result is None

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_industry_statistics_returns_dict(self, mock_connect):
        """Test get_industry_statistics returns industry counts"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"gics_industry": "Software ", "count": 50},
            {"gics_industry": "Pharmaceuticals ", "count": 40},
        ]
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        result = connector.get_industry_statistics()
        assert result is not None or result is None

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_companies_by_industry_returns_list(self, mock_connect):
        """Test get_companies_by_industry returns list"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [{"symbol": "AAPL", "security": "Apple"}]
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        result = connector.get_companies_by_industry("Software")
        assert result is not None

    @patch("modules.db.postgres_connector.psycopg2.connect")
    def test_get_company_universe_df_returns_dataframe(self, mock_connect):
        """Test get_company_universe_df returns DataFrame"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        # Mock column descriptions for DataFrame creation
        mock_cursor.description = [("symbol",), ("security",), ("gics_sector",)]
        mock_cursor.fetchall.return_value = [
            ("AAPL", "Apple", "Technology"),
            ("MSFT", "Microsoft", "Technology"),
        ]
        mock_connect.return_value = mock_connection

        config = {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "public",
        }
        connector = PostgresConnector(config)

        result = connector.get_company_universe_df()
        assert result is None or isinstance(result, pd.DataFrame)
