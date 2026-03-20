"""
PostgreSQL Database Connector
Handles connections and queries to the investment database
"""

import logging
from typing import Any, Dict, List

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class PostgresConnector:
    """
    PostgreSQL database connector for accessing investment data.

    Attributes:
        config (dict): Database configuration containing host, port, user, password, etc.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize PostgreSQL connection.

        Args:
            config (dict): Configuration dictionary with keys:
                - host: Database host
                - port: Database port
                - user: Database user
                - password: Database password
                - database: Database name
                - schema: Database schema
        """
        self.config = config
        self.connection = None
        self.connect()

    def connect(self):
        """
        Establish connection to PostgreSQL database.

        Raises:
            psycopg2.Error: If connection fails
        """
        try:
            self.connection = psycopg2.connect(
                host=self.config.get("host", "localhost"),
                port=self.config.get("port", 5432),
                user=self.config.get("user", "postgres"),
                password=self.config.get("password", ""),
                database=self.config.get("database", "postgres"),
            )
            logger.info(
                f"Connected to PostgreSQL at {self.config['host']}:{self.config['port']}"
            )
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    def disconnect(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            logger.info("Disconnected from PostgreSQL")

    def get_company_universe(self) -> List[Dict[str, Any]]:
        """
        Retrieve all companies from the company_static table.

        Returns:
            List of dictionaries containing company data
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            # Query the correct table in systematic_equity schema
            queries = [
                "SELECT * FROM systematic_equity.company_static;",  # Correct location
                "SELECT * FROM public.company_static;",  # Try public schema
                "SELECT * FROM company_static;",  # Try without schema
            ]

            result = None
            for query in queries:
                try:
                    cursor.execute(query)
                    result = cursor.fetchall()
                    logger.info(f"Successfully queried with: {query}")
                    break
                except psycopg2.Error as e:
                    logger.debug(f"Query failed: {query} - {e}")
                    continue

            if result is None:
                raise Exception("Could not retrieve companies with any query format")

            cursor.close()
            logger.info(f"Retrieved {len(result)} companies from database")
            return result
        except psycopg2.Error as e:
            logger.error(f"Error retrieving companies: {e}")
            raise

    def get_company_by_symbol(self, symbol: str) -> Dict[str, Any]:
        """
        Retrieve a specific company by symbol.

        Args:
            symbol (str): Company ticker symbol

        Returns:
            Dictionary containing company data or None if not found
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            queries = [
                "SELECT * FROM systematic_equity.company_static WHERE symbol = %s;",
                "SELECT * FROM public.company_static WHERE symbol = %s;",
                "SELECT * FROM company_static WHERE symbol = %s;",
            ]

            company = None
            for query in queries:
                try:
                    cursor.execute(query, (symbol,))
                    company = cursor.fetchone()
                    if company:
                        logger.debug(f"Found company with query: {query}")
                        break
                except psycopg2.Error:
                    continue

            cursor.close()
            return company
        except psycopg2.Error as e:
            logger.error(f"Error retrieving company {symbol}: {e}")
            raise

    def insert_company(
        self,
        symbol: str,
        security: str,
        gics_sector: str,
        gics_industry: str,
        country: str,
        region: str,
    ):
        """
        Insert a new company into the database.

        Args:
            symbol (str): Company ticker symbol
            security (str): Security name
            gics_sector (str): GICS sector
            gics_industry (str): GICS industry
            country (str): Country
            region (str): Region

        Returns:
            bool: True if insert successful
        """
        try:
            cursor = self.connection.cursor()
            schema = self.config.get("schema", "systematic_equity")
            query = sql.SQL(
                "INSERT INTO fift.{schema}.company_static "
                "(symbol, security, gics_sector, gics_industry, country, region) "
                "VALUES (%s, %s, %s, %s, %s, %s);"
            ).format(schema=sql.Identifier(schema))
            cursor.execute(
                query, (symbol, security, gics_sector, gics_industry, country, region)
            )
            self.connection.commit()
            cursor.close()
            logger.info(f"Inserted company: {symbol}")
            return True
        except psycopg2.Error as e:
            self.connection.rollback()
            logger.error(f"Error inserting company: {e}")
            raise

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """
        Execute a custom SQL query.

        Args:
            query (str): SQL query to execute
            params (tuple): Query parameters

        Returns:
            List of dictionaries containing query results
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            results = cursor.fetchall()
            cursor.close()
            return results
        except psycopg2.Error as e:
            logger.error(f"Error executing query: {e}")
            raise

    def get_unique_sectors(self) -> List[str]:
        """
        Get all unique GICS sectors from the database.

        Returns:
            List of unique sector names
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            queries = [
                "SELECT DISTINCT gics_sector FROM systematic_equity.company_static WHERE gics_sector IS NOT NULL ORDER BY gics_sector;",
                "SELECT DISTINCT gics_sector FROM public.company_static WHERE gics_sector IS NOT NULL ORDER BY gics_sector;",
                "SELECT DISTINCT gics_sector FROM company_static WHERE gics_sector IS NOT NULL ORDER BY gics_sector;",
            ]

            result = None
            for query in queries:
                try:
                    cursor.execute(query)
                    result = cursor.fetchall()
                    logger.info(f"Retrieved sectors with: {query}")
                    break
                except psycopg2.Error as e:
                    logger.debug(f"Query failed: {query} - {e}")
                    continue

            if result is None:
                raise Exception("Could not retrieve sectors from database")

            cursor.close()
            sectors = [row["gics_sector"].strip() for row in result]
            logger.info(f"Found {len(sectors)} unique sectors: {sectors}")
            return sectors
        except psycopg2.Error as e:
            logger.error(f"Error retrieving sectors: {e}")
            raise

    def get_companies_by_sector(self, sector: str) -> List[Dict[str, Any]]:
        """
        Get all companies in a specific sector.

        Args:
            sector (str): Sector name

        Returns:
            List of companies in the sector
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            queries = [
                "SELECT * FROM systematic_equity.company_static WHERE gics_sector = %s ORDER BY symbol;",
                "SELECT * FROM public.company_static WHERE gics_sector = %s ORDER BY symbol;",
                "SELECT * FROM company_static WHERE gics_sector = %s ORDER BY symbol;",
            ]

            result = None
            for query in queries:
                try:
                    cursor.execute(query, (sector,))
                    result = cursor.fetchall()
                    logger.info(
                        f"Retrieved {len(result)} companies in sector: {sector}"
                    )
                    break
                except psycopg2.Error as e:
                    logger.debug(f"Query failed for sector {sector}: {e}")
                    continue

            if result is None:
                raise Exception(f"Could not retrieve companies for sector {sector}")

            cursor.close()
            return result
        except psycopg2.Error as e:
            logger.error(f"Error retrieving companies for sector {sector}: {e}")
            raise

    def get_sector_statistics(self) -> Dict[str, int]:
        """
        Get count of companies per sector.

        Returns:
            Dictionary with sector names and company counts
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            queries = [
                "SELECT gics_sector, COUNT(*) as count FROM systematic_equity.company_static WHERE gics_sector IS NOT NULL GROUP BY gics_sector ORDER BY count DESC;",
                "SELECT gics_sector, COUNT(*) as count FROM public.company_static WHERE gics_sector IS NOT NULL GROUP BY gics_sector ORDER BY count DESC;",
                "SELECT gics_sector, COUNT(*) as count FROM company_static WHERE gics_sector IS NOT NULL GROUP BY gics_sector ORDER BY count DESC;",
            ]

            result = None
            for query in queries:
                try:
                    cursor.execute(query)
                    result = cursor.fetchall()
                    logger.info("Retrieved sector statistics")
                    break
                except psycopg2.Error as e:
                    logger.debug(f"Query failed: {e}")
                    continue

            if result is None:
                raise Exception("Could not retrieve sector statistics")

            cursor.close()
            stats = {row["gics_sector"].strip(): row["count"] for row in result}
            return stats
        except psycopg2.Error as e:
            logger.error(f"Error retrieving sector statistics: {e}")
            raise

    def get_industry_statistics(self) -> Dict[str, int]:
        """
        Get count of companies per GICS industry.

        Returns:
            Dictionary with industry names and company counts
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            queries = [
                "SELECT gics_industry, COUNT(*) as count FROM systematic_equity.company_static WHERE gics_industry IS NOT NULL GROUP BY gics_industry ORDER BY count DESC;",
                "SELECT gics_industry, COUNT(*) as count FROM public.company_static WHERE gics_industry IS NOT NULL GROUP BY gics_industry ORDER BY count DESC;",
                "SELECT gics_industry, COUNT(*) as count FROM company_static WHERE gics_industry IS NOT NULL GROUP BY gics_industry ORDER BY count DESC;",
            ]

            result = None
            for query in queries:
                try:
                    cursor.execute(query)
                    result = cursor.fetchall()
                    logger.info("Retrieved industry statistics")
                    break
                except psycopg2.Error as e:
                    logger.debug(f"Query failed: {e}")
                    continue

            if result is None:
                raise Exception("Could not retrieve industry statistics")

            cursor.close()
            stats = {row["gics_industry"].strip(): row["count"] for row in result}
            return stats
        except psycopg2.Error as e:
            logger.error(f"Error retrieving industry statistics: {e}")
            raise

    def get_companies_by_industry(self, industry: str) -> List[Dict[str, Any]]:
        """
        Get all companies in a specific GICS industry.

        Args:
            industry (str): Industry name

        Returns:
            List of companies in the industry
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            queries = [
                "SELECT * FROM systematic_equity.company_static WHERE gics_industry = %s ORDER BY symbol;",
                "SELECT * FROM public.company_static WHERE gics_industry = %s ORDER BY symbol;",
                "SELECT * FROM company_static WHERE gics_industry = %s ORDER BY symbol;",
            ]

            result = None
            for query in queries:
                try:
                    cursor.execute(query, (industry,))
                    result = cursor.fetchall()
                    logger.info(
                        f"Retrieved {len(result)} companies in industry: {industry}"
                    )
                    break
                except psycopg2.Error as e:
                    logger.debug(f"Query failed for industry {industry}: {e}")
                    continue

            if result is None:
                raise Exception(f"Could not retrieve companies for industry {industry}")

            cursor.close()
            return result
        except psycopg2.Error as e:
            logger.error(f"Error retrieving companies for industry {industry}: {e}")
            raise

    def get_company_universe_df(self) -> pd.DataFrame:
        """
        Get the complete company universe as a pandas DataFrame.

        Returns:
            DataFrame with all companies and their attributes
        """
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)

            # Try multiple query approaches
            queries = [
                "SELECT symbol, security, gics_sector, gics_industry, country, region FROM systematic_equity.company_static ORDER BY symbol",
                "SELECT symbol, security, gics_sector, gics_industry, country, region FROM public.company_static ORDER BY symbol",
                "SELECT symbol, security, gics_sector, gics_industry, country, region FROM company_static ORDER BY symbol",
            ]

            result = None
            for query in queries:
                try:
                    cursor.execute(query)
                    result = cursor.fetchall()
                    logger.info(
                        f"Retrieved {len(result)} companies from company universe"
                    )
                    break
                except psycopg2.Error as e:
                    logger.debug(f"Query failed: {e}")
                    continue

            if result is None:
                raise Exception("Could not retrieve company universe")

            cursor.close()

            # Convert to DataFrame
            df = pd.DataFrame(result)
            return df

        except psycopg2.Error as e:
            logger.error(f"Error retrieving company universe: {e}")
            raise

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
