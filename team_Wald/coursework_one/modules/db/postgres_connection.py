"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : PostgreSQL connection and operations
Project : CW1 - Value + News Sentiment Strategy

Follows the DatabaseMethods pattern from the ift_big_data repository
(Scripts/Python/2_ETL_Mongodb_SQL/modules/db/sql_conn.py) and extends
it with upsert operations for the value + sentiment pipeline tables.

Provides context-manager support for safe resource cleanup::

    with get_db_client(config) as db:
        db.execute_query("SELECT * FROM systematic_equity.company_static")
"""

import os

import pandas as pd
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, engine, text
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm import scoped_session, sessionmaker

from modules.utils.logger import pipeline_logger


class PostgresConfig(BaseModel):
    """Pydantic model for PostgreSQL connection configuration.

    Falls back to environment variables when constructor values are
    not supplied, following the ift_big_data teaching material pattern
    (Scripts/Python/4_Calibrate_Factors/modules/db_ops/postgres_config.py).

    :param username: Database username
    :type username: str or None
    :param password: Database password
    :type password: str or None
    :param host: Database host address
    :type host: str or None
    :param port: Database port number
    :type port: str or None
    :param database: Target database name
    :type database: str or None
    """

    username: str | None = Field(None, validate_default=True)
    password: str | None = Field(None, validate_default=True)
    host: str | None = Field(None, validate_default=True)
    port: str | None = Field(None, validate_default=True)
    database: str | None = Field(None, validate_default=True)

    @field_validator("username", mode="after")
    @classmethod
    def resolve_username(cls, v) -> str:
        """Resolve username from environment if not provided."""
        return v or os.environ.get("POSTGRES_USERNAME", "postgres")

    @field_validator("password", mode="after")
    @classmethod
    def resolve_password(cls, v) -> str:
        """Resolve password from environment if not provided."""
        return v or os.environ.get("POSTGRES_PASSWORD", "postgres")

    @field_validator("host", mode="after")
    @classmethod
    def resolve_host(cls, v) -> str:
        """Resolve host from environment if not provided."""
        return v or os.environ.get("POSTGRES_HOST_DEV", os.environ.get("POSTGRES_HOST", "localhost"))

    @field_validator("port", mode="after")
    @classmethod
    def resolve_port(cls, v) -> str:
        """Resolve port from environment if not provided."""
        return v or os.environ.get("POSTGRES_PORT_DEV", os.environ.get("POSTGRES_PORT", "5438"))

    @field_validator("database", mode="after")
    @classmethod
    def resolve_database(cls, v) -> str:
        """Resolve database name from environment if not provided."""
        return v or os.environ.get("POSTGRES_DATABASE", "fift")


class DatabaseClient:
    """PostgreSQL database client with session management.

    Wraps SQLAlchemy engine and session factory. Supports context-manager
    protocol for automatic cleanup, following the pattern from
    ``Scripts/Python/2_ETL_Mongodb_SQL/modules/db/sql_conn.py``.

    :param config: Pydantic PostgresConfig with resolved connection params
    :type config: PostgresConfig
    """

    def __init__(self, config: PostgresConfig):
        self._config = config
        self._engine = self._create_engine()
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def engine(self) -> Engine:
        """Returns the SQLAlchemy engine instance."""
        return self._engine

    @property
    def session(self):
        """Returns a new scoped session."""
        return scoped_session(self._session_factory)()

    def _create_engine(self) -> Engine:
        """Create a SQLAlchemy engine from the Pydantic config.

        :return: Configured SQLAlchemy engine
        :rtype: Engine
        :raises Exception: If connection cannot be established
        """
        url = engine.URL.create(
            drivername="postgresql",
            username=self._config.username,
            password=self._config.password,
            host=self._config.host,
            port=self._config.port,
            database=self._config.database,
        )
        return create_engine(url, pool_size=10, max_overflow=5, pool_pre_ping=True)

    def execute_query(self, sql_query: str) -> list:
        """Execute a read query and return all result rows.

        :param sql_query: SQL SELECT statement
        :type sql_query: str
        :return: List of result row tuples
        :rtype: list
        """
        session = self.session
        try:
            result = session.execute(text(sql_query))
            return result.all()
        finally:
            session.close()

    def execute_query_df(self, sql_query: str) -> pd.DataFrame:
        """Execute a query and return a pandas DataFrame.

        :param sql_query: SQL SELECT statement
        :type sql_query: str
        :return: Query results as DataFrame
        :rtype: pd.DataFrame
        """
        return pd.read_sql(sql_query, self._engine)

    def execute_write(self, sql_statement: str, params: dict = None):
        """Execute a write statement (INSERT, UPDATE, DELETE).

        :param sql_statement: SQL DML statement
        :type sql_statement: str
        :param params: Optional bind parameters
        :type params: dict or None
        """
        with self._engine.connect() as conn:
            conn.execute(text(sql_statement), params or {})
            conn.commit()

    def init_schema(self, sql_file_path: str):
        """Initialise database schema from a SQL DDL file.

        :param sql_file_path: Path to the SQL file
        :type sql_file_path: str
        """
        with open(sql_file_path, "r") as f:
            sql_content = f.read()
        with self._engine.connect() as conn:
            for statement in sql_content.split(";"):
                stmt = statement.strip()
                if not stmt:
                    continue
                lines = [ln for ln in stmt.splitlines() if ln.strip() and not ln.strip().startswith("--")]
                if not lines:
                    continue
                conn.execute(text(stmt))
            conn.commit()
        pipeline_logger.info("Database schema initialised from %s", sql_file_path)

    def close(self):
        """Dispose the engine and release all pooled connections."""
        self._engine.dispose()


def get_db_client(db_config: dict = None, **kwargs) -> DatabaseClient:
    """Factory function to build a DatabaseClient from config dict.

    :param db_config: Database config dict from conf.yaml
    :type db_config: dict or None
    :return: Ready-to-use DatabaseClient
    :rtype: DatabaseClient

    Example::

        >>> client = get_db_client(conf['config']['Database']['Postgres'])
        >>> rows = client.execute_query("SELECT 1")
    """
    if db_config:
        pg_config = PostgresConfig(
            username=db_config.get("Username"),
            password=db_config.get("Password"),
            host=db_config.get("Host"),
            port=str(db_config.get("Port", "5438")),
            database=db_config.get("Database"),
        )
    else:
        pg_config = PostgresConfig(
            username=kwargs.get("username"),
            password=kwargs.get("password"),
            host=kwargs.get("host"),
            port=kwargs.get("port"),
            database=kwargs.get("database"),
        )
    return DatabaseClient(pg_config)
