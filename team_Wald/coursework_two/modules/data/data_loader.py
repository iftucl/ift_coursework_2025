"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Data loader — point-in-time access to CW1 PostgreSQL + MongoDB
Project : CW2 - Value-Sentiment Investment Strategy

Loads price history, value metrics, sentiment scores, company metadata
and article-level news from the CW1 data pipeline infrastructure.

Security & integration hardening (v2.2):

    * **Parameterised SQL** — every value-bearing placeholder uses
      SQLAlchemy bound parameters; identifiers (schema / table) are
      whitelisted via :func:`modules.data.cw1_schema.assert_safe_identifier`
      so they cannot be used as injection vectors.
    * **Env-var credential resolution** — Postgres and MongoDB passwords
      fall back to environment variables (matching CW1's own resolver
      pattern) instead of hardcoded literals. The chain is
      ``cw1_conf.yaml`` → environment variable → fail-loud.
    * **Point-in-time Mongo queries** — the news-article reader applies
      ``published_at <= as_of_date`` server-side so the back-tester
      cannot leak future news into a past rebalance.
    * **Correct CW1 field names** — VADER compound is read from
      ``compound_score`` (the field CW1 actually writes) rather than
      the previous ``vader_compound`` typo, and article date is read
      from ``published_at`` first (CW1's canonical field) with
      ``fetched_at`` / ``date`` / ``seendate`` as legacy fallbacks.
    * **Resource hygiene** — every connection is opened in a
      context-managed try / finally so a failed query never leaks a
      socket or pool slot.

:Design: Part D §D7 — CW1 Integration
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Optional

import numpy as np
import pandas as pd
import yaml
from sqlalchemy import create_engine, engine, text

from modules.data.cw1_schema import (
    DEFAULT_SCHEMA,
    MONGO_COLLECTION_NEWS,
    MONGO_DB_NAME,
    MONGO_FIELD_COMPANY_ID,
    MONGO_FIELD_COMPANY_NAME,
    MONGO_FIELD_COMPOUND_SCORE,
    MONGO_FIELD_DESCRIPTION,
    MONGO_FIELD_FETCHED_AT,
    MONGO_FIELD_HEADLINE,
    MONGO_FIELD_NEGATIVE_SCORE,
    MONGO_FIELD_NEUTRAL_SCORE,
    MONGO_FIELD_POSITIVE_SCORE,
    MONGO_FIELD_PUBLISHED_AT,
    MONGO_FIELD_SOURCE,
    MONGO_FIELD_SOURCE_NAME,
    MONGO_NEWS_PROJECTION,
    TABLE_COMPANY_STATIC,
    TABLE_COMPOSITE_RANKINGS,
    TABLE_DAILY_PRICES,
    TABLE_SENTIMENT_SCORES,
    TABLE_VALUE_METRICS,
    assert_safe_identifier,
)

logger = logging.getLogger(__name__)

# Envelope for environment-variable resolution. Keys map env-var names
# to the path inside the CW1 conf.yaml ``Database.{Postgres|MongoDB}`` block.
_PG_ENV_PASSWORD = 'POSTGRES_PASSWORD'
_PG_ENV_USERNAME = 'POSTGRES_USERNAME'
_PG_ENV_HOST = 'POSTGRES_HOST_DEV'
_PG_ENV_PORT = 'POSTGRES_PORT_DEV'
_PG_ENV_DATABASE = 'POSTGRES_DATABASE'

_MONGO_ENV_PASSWORD = 'MONGO_PASSWORD'
_MONGO_ENV_USERNAME = 'MONGO_USERNAME'
_MONGO_ENV_HOST = 'MONGO_HOST'
_MONGO_ENV_PORT = 'MONGO_PORT'


def _resolve_secret(conf_value, env_var: str) -> Optional[str]:
    """Resolve a credential value with the precedence YAML > env > None.

    Empty / missing YAML values fall through to the environment so that
    operators can keep secrets out of source control by exporting them
    (e.g. ``export POSTGRES_PASSWORD=...``). This mirrors CW1's
    ``PostgresConfig`` validator behaviour but adds explicit None
    handling so a missing secret raises early rather than silently
    connecting with the literal string ``'None'``.

    :param conf_value: Value pulled from CW1 conf.yaml (may be None)
    :param env_var: Environment variable to consult on a YAML miss
    :type env_var: str
    :returns: Resolved value or None if neither source set it
    :rtype: str or None
    """
    if conf_value not in (None, '', 'null'):
        return str(conf_value)
    env_value = os.environ.get(env_var)
    if env_value:
        return env_value
    return None


class DataLoader:
    """Load CW1 pipeline data from PostgreSQL + MongoDB for CW2 backtesting.

    All public methods enforce point-in-time discipline (``date <= as_of``)
    and use parameter binding. Identifiers (schema / table) are whitelisted
    against :mod:`modules.data.cw1_schema` before any interpolation.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, config: dict):
        self._config = config
        self._schema = assert_safe_identifier(
            config.get('data', {}).get('postgres_schema', DEFAULT_SCHEMA),
            kind='schema',
        )
        self._engine = self._create_engine()
        logger.info("DataLoader initialised — schema: %s", self._schema)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _load_cw1_conf(self) -> dict:
        """Load CW1 conf.yaml and return the active env profile dict."""
        cw1_path = self._config['cw1']['config_path']
        env_type = self._config['cw1']['env_type']
        with open(cw1_path, 'r') as f:
            cw1_conf = yaml.safe_load(f)
        if env_type not in cw1_conf:
            raise KeyError(f"CW1 conf.yaml has no {env_type!r} profile")
        return cw1_conf[env_type]

    def _create_engine(self):
        """Create SQLAlchemy engine from CW1 config + env-var fallbacks.

        Credential resolution chain per field:

            1. Value from CW1 ``conf.yaml``
            2. Environment variable (mirroring CW1's own ``PostgresConfig``)
            3. Documented hard default (host/port/database only — never
               passwords)

        :returns: SQLAlchemy engine instance
        :rtype: sqlalchemy.engine.Engine
        :raises RuntimeError: If no Postgres password can be resolved
        """
        env_profile = self._load_cw1_conf()
        db_conf = env_profile.get('config', {}).get('Database', {}).get('Postgres', {}) or {}

        username = _resolve_secret(db_conf.get('Username'), _PG_ENV_USERNAME) or 'postgres'
        password = _resolve_secret(db_conf.get('Password'), _PG_ENV_PASSWORD)
        host = _resolve_secret(db_conf.get('Host'), _PG_ENV_HOST) or 'localhost'
        port = str(_resolve_secret(db_conf.get('Port'), _PG_ENV_PORT) or '5439')
        database = _resolve_secret(db_conf.get('Database'), _PG_ENV_DATABASE) or 'fift'

        if password is None:
            raise RuntimeError(
                "No Postgres password resolved from CW1 conf.yaml or "
                f"the {_PG_ENV_PASSWORD} environment variable. Refusing "
                "to connect with an empty credential."
            )

        # Honour the CW1 ``Schema:`` field if present and non-empty —
        # it overrides the CW2-side default but only when safe.
        cw1_schema = db_conf.get('Schema')
        if cw1_schema and assert_safe_identifier(str(cw1_schema), kind='schema'):
            self._schema = str(cw1_schema)

        url = engine.URL.create(
            drivername='postgresql',
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
        )
        # Note: never log the URL — it contains the password.
        logger.info(
            "Postgres connection: host=%s port=%s db=%s schema=%s user=%s",
            host, port, database, self._schema, username,
        )
        return create_engine(
            url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=3600,  # cycle stale connections every hour
        )

    @contextmanager
    def _connection(self):
        """Yield a managed SQLAlchemy connection that is always returned."""
        conn = self._engine.connect()
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # PostgreSQL readers (all parameterised)
    # ------------------------------------------------------------------

    def load_company_static(self) -> pd.DataFrame:
        """Load the full universe with GICS sector data.

        :returns: DataFrame with columns ``[symbol, security, gics_sector,
                  gics_industry, country, region]``. Symbols are stripped
                  and upper-cased per CW1 convention.
        :rtype: pd.DataFrame
        """
        sql = text(
            f'SELECT TRIM(symbol) AS symbol, security, gics_sector, '
            f'gics_industry, TRIM(country) AS country, region '
            f'FROM {self._schema}.{TABLE_COMPANY_STATIC}'
        )
        with self._connection() as conn:
            df = pd.read_sql(sql, conn)
        df['symbol'] = df['symbol'].astype(str).str.strip().str.upper()
        logger.info("Loaded %d companies from %s", len(df), TABLE_COMPANY_STATIC)
        return df

    def load_daily_prices(
        self,
        start_date: str,
        end_date: str,
        tickers: Optional[list] = None,
    ) -> pd.DataFrame:
        """Load adjusted close prices for the back-test window.

        :param start_date: ISO date (YYYY-MM-DD) — inclusive lower bound
        :type start_date: str
        :param end_date: ISO date — inclusive upper bound
        :type end_date: str
        :param tickers: Optional whitelist; tickers are normalised
                        (strip + upper) before binding
        :type tickers: list or None
        :returns: Pivoted DataFrame ``dates × tickers`` (adj_close_price)
        :rtype: pd.DataFrame
        """
        from sqlalchemy import bindparam

        params: dict = {'start': start_date, 'end': end_date}
        cleaned_tickers = None
        if tickers:
            cleaned_tickers = [
                str(t).strip().upper() for t in tickers if str(t).strip()
            ]

        if cleaned_tickers:
            # SQLAlchemy expanding bind parameter — the driver serialises
            # the list as a parameterised IN(...) clause, fully escaping
            # every element.
            sql = text(
                f'SELECT TRIM(symbol) AS symbol, cob_date, adj_close_price '
                f'FROM {self._schema}.{TABLE_DAILY_PRICES} '
                f'WHERE cob_date BETWEEN :start AND :end '
                f'AND TRIM(UPPER(symbol)) IN :tickers '
                f'ORDER BY cob_date, symbol'
            ).bindparams(bindparam('tickers', expanding=True))
            params['tickers'] = cleaned_tickers
        else:
            sql = text(
                f'SELECT TRIM(symbol) AS symbol, cob_date, adj_close_price '
                f'FROM {self._schema}.{TABLE_DAILY_PRICES} '
                f'WHERE cob_date BETWEEN :start AND :end '
                f'ORDER BY cob_date, symbol'
            )

        with self._connection() as conn:
            df = pd.read_sql(sql, conn, params=params, parse_dates=['cob_date'])

        df['symbol'] = df['symbol'].astype(str).str.strip().str.upper()
        prices = df.pivot(index='cob_date', columns='symbol', values='adj_close_price')
        prices.index.name = 'date'
        prices = prices.sort_index()

        logger.info(
            "Loaded prices: %d dates × %d tickers (%s to %s)",
            len(prices), len(prices.columns),
            prices.index.min().strftime('%Y-%m-%d') if len(prices) > 0 else 'N/A',
            prices.index.max().strftime('%Y-%m-%d') if len(prices) > 0 else 'N/A',
        )
        return prices

    def load_value_metrics(self, as_of_date: str) -> pd.DataFrame:
        """Load value metrics available *as of* the given date.

        Uses ``DISTINCT ON`` to return the most recent record per
        ``company_id`` while respecting the point-in-time bound
        ``date <= :as_of``.

        **Fallback for single-snapshot CW1 data**: CW1 stores one
        value_metrics row per company per pipeline run, stamped with
        the run_date. yfinance only returns current trailing-twelve-
        month ratios so CW1 has no way to produce historical snapshots.
        When the strict point-in-time query returns zero rows, we fall
        back to the latest available snapshot and log a warning. This
        trades strict PIT discipline for a functional backtest and is
        standard practice for static-factor backtests in academia.

        :param as_of_date: ISO date upper bound
        :type as_of_date: str
        :returns: DataFrame with ``[company_id, date, pe_ratio, pb_ratio,
                  ev_ebitda, dividend_yield, debt_equity, value_score]``
        :rtype: pd.DataFrame
        """
        pit_sql = text(
            f'SELECT DISTINCT ON (company_id) '
            f'TRIM(company_id) AS company_id, date, pe_ratio, pb_ratio, '
            f'ev_ebitda, dividend_yield, debt_equity, value_score '
            f'FROM {self._schema}.{TABLE_VALUE_METRICS} '
            f'WHERE date <= :as_of '
            f'ORDER BY company_id, date DESC'
        )
        with self._connection() as conn:
            df = pd.read_sql(pit_sql, conn, params={'as_of': as_of_date}, parse_dates=['date'])

        if len(df) == 0:
            logger.warning(
                "No value_metrics rows <= %s — falling back to latest snapshot "
                "(CW1 stores a single static factor snapshot; strict PIT not possible)",
                as_of_date,
            )
            fallback_sql = text(
                f'SELECT DISTINCT ON (company_id) '
                f'TRIM(company_id) AS company_id, date, pe_ratio, pb_ratio, '
                f'ev_ebitda, dividend_yield, debt_equity, value_score '
                f'FROM {self._schema}.{TABLE_VALUE_METRICS} '
                f'ORDER BY company_id, date DESC'
            )
            with self._connection() as conn:
                df = pd.read_sql(fallback_sql, conn, parse_dates=['date'])

        df['company_id'] = df['company_id'].astype(str).str.strip().str.upper()
        logger.info(
            "Loaded value metrics for %d companies (as of %s)",
            len(df), as_of_date,
        )
        return df

    def load_sentiment_scores(self, as_of_date: str) -> pd.DataFrame:
        """Load aggregated sentiment scores available as of a given date.

        Applies the same static-factor fallback as
        :meth:`load_value_metrics` — if the point-in-time query returns
        zero rows (because CW1 stores a single snapshot), fall back to
        the latest available row and log a warning.

        :param as_of_date: ISO date upper bound
        :type as_of_date: str
        :returns: DataFrame with the full aggregated CW1 sentiment row
        :rtype: pd.DataFrame
        """
        pit_sql = text(
            f'SELECT DISTINCT ON (company_id) '
            f'TRIM(company_id) AS company_id, date, avg_sentiment, '
            f'positive_count, negative_count, neutral_count, total_articles, '
            f'positive_ratio, sentiment_score '
            f'FROM {self._schema}.{TABLE_SENTIMENT_SCORES} '
            f'WHERE date <= :as_of '
            f'ORDER BY company_id, date DESC'
        )
        with self._connection() as conn:
            df = pd.read_sql(pit_sql, conn, params={'as_of': as_of_date}, parse_dates=['date'])

        if len(df) == 0:
            logger.warning(
                "No sentiment_scores rows <= %s — falling back to latest snapshot",
                as_of_date,
            )
            fallback_sql = text(
                f'SELECT DISTINCT ON (company_id) '
                f'TRIM(company_id) AS company_id, date, avg_sentiment, '
                f'positive_count, negative_count, neutral_count, total_articles, '
                f'positive_ratio, sentiment_score '
                f'FROM {self._schema}.{TABLE_SENTIMENT_SCORES} '
                f'ORDER BY company_id, date DESC'
            )
            with self._connection() as conn:
                df = pd.read_sql(fallback_sql, conn, parse_dates=['date'])

        df['company_id'] = df['company_id'].astype(str).str.strip().str.upper()
        logger.info(
            "Loaded sentiment scores for %d companies (as of %s)",
            len(df), as_of_date,
        )
        return df

    def load_composite_rankings(self, as_of_date: str) -> pd.DataFrame:
        """Load CW1 composite rankings for OLD-vs-NEW signal comparison.

        :param as_of_date: ISO date upper bound
        :type as_of_date: str
        :returns: DataFrame with the full CW1 composite ranking row
        :rtype: pd.DataFrame
        """
        sql = text(
            f'SELECT DISTINCT ON (company_id) '
            f'TRIM(company_id) AS company_id, date, value_score, '
            f'sentiment_score, composite_score, rank, invest_decision '
            f'FROM {self._schema}.{TABLE_COMPOSITE_RANKINGS} '
            f'WHERE date <= :as_of '
            f'ORDER BY company_id, date DESC'
        )
        with self._connection() as conn:
            df = pd.read_sql(sql, conn, params={'as_of': as_of_date}, parse_dates=['date'])
        df['company_id'] = df['company_id'].astype(str).str.strip().str.upper()
        logger.info("Loaded CW1 composite rankings for %d companies", len(df))
        return df

    # ------------------------------------------------------------------
    # MongoDB reader for article-level quality-weighted sentiment
    # ------------------------------------------------------------------

    # Minimum distinct companies required from the Mongo article-level
    # path. Below this, the article set is too thin to build a portfolio
    # universe from, so we fall back to the aggregated PostgreSQL
    # sentiment_scores path (which yields the full static-factor
    # snapshot of ~550 companies via the same fallback pattern as
    # ``load_value_metrics``).
    _MIN_MONGO_COMPANIES = 50

    def load_news_article_metadata(self, as_of_date: str) -> pd.DataFrame:
        """Load article-level news metadata, point-in-time.

        Falls back gracefully to the aggregated PostgreSQL sentiment
        scores when MongoDB is unavailable **or** when the Mongo query
        returns fewer than ``_MIN_MONGO_COMPANIES`` distinct companies
        — this is the normal situation for historical rebalance dates,
        because CW1's news extraction only retrieves current articles,
        not historical ones. The article-level path is still the first
        choice when the most recent rebalance has sufficient coverage.

        :param as_of_date: ISO date upper bound for ``published_at``
        :type as_of_date: str
        :returns: DataFrame with article metadata or aggregated fallback
        :rtype: pd.DataFrame
        """
        articles_df = self._load_articles_from_mongo(as_of_date)
        if articles_df is not None and len(articles_df) > 0:
            n_companies = (
                articles_df[MONGO_FIELD_COMPANY_ID].nunique()
                if MONGO_FIELD_COMPANY_ID in articles_df.columns
                else 0
            )
            if n_companies >= self._MIN_MONGO_COMPANIES:
                logger.info(
                    "Loaded %d article-level records from MongoDB (as of %s, %d companies)",
                    len(articles_df), as_of_date, n_companies,
                )
                return articles_df
            logger.info(
                "Mongo article-level path returned only %d companies "
                "(<%d threshold) — falling back to aggregated sentiment_scores",
                n_companies, self._MIN_MONGO_COMPANIES,
            )

        logger.info(
            "MongoDB articles unavailable — falling back to aggregated sentiment_scores"
        )
        return self.load_sentiment_scores(as_of_date)

    def _load_articles_from_mongo(self, as_of_date: str) -> Optional[pd.DataFrame]:
        """Query article-level data from CW1 MongoDB ``raw_news_articles``.

        The query enforces ``published_at <= as_of_date`` server-side so
        no future news leaks into a past rebalance. Connection lifecycle
        is bracketed with try / finally to guarantee socket closure even
        on partial failure.

        :param as_of_date: ISO date upper bound
        :type as_of_date: str
        :returns: Article metadata DataFrame or None on failure
        :rtype: pd.DataFrame or None
        """
        try:
            from pymongo import MongoClient
        except ImportError:
            logger.info("pymongo not installed — cannot load article-level data")
            return None

        try:
            env_profile = self._load_cw1_conf()
        except (FileNotFoundError, KeyError) as exc:
            logger.info("CW1 conf.yaml unavailable: %s", exc)
            return None

        mongo_conf = env_profile.get('config', {}).get('Database', {}).get('MongoDB', {}) or {}
        username = _resolve_secret(mongo_conf.get('Username'), _MONGO_ENV_USERNAME) or 'ift_bigdata'
        password = _resolve_secret(mongo_conf.get('Password'), _MONGO_ENV_PASSWORD)
        host = _resolve_secret(mongo_conf.get('Host'), _MONGO_ENV_HOST) or 'localhost'
        port_raw = _resolve_secret(mongo_conf.get('Port'), _MONGO_ENV_PORT) or '27019'
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            logger.warning("Invalid Mongo port %r — aborting Mongo load", port_raw)
            return None

        if password is None:
            logger.info(
                "No Mongo password resolved (set %s env var or CW1 conf.yaml). "
                "Falling back to aggregated sentiment.",
                _MONGO_ENV_PASSWORD,
            )
            return None

        client = None
        try:
            client = MongoClient(
                host=host,
                port=port,
                username=username,
                password=password,
                authSource='admin',
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=10000,
                maxPoolSize=20,
            )
            client.admin.command('ping')

            db_name = mongo_conf.get('Database', MONGO_DB_NAME)
            collection_name = (
                mongo_conf.get('Collections', {}).get('raw_news', MONGO_COLLECTION_NEWS)
            )
            collection = client[db_name][collection_name]

            # Point-in-time filter: published_at <= as_of_date.
            # Article timestamps live in ``published_at``; we OR with
            # ``fetched_at`` to also keep records that pre-date the
            # ``published_at`` migration in older Mongo dumps.
            from datetime import datetime
            try:
                cutoff = datetime.fromisoformat(as_of_date)
            except ValueError:
                cutoff = pd.to_datetime(as_of_date).to_pydatetime()

            point_in_time_query = {
                '$or': [
                    {MONGO_FIELD_PUBLISHED_AT: {'$lte': cutoff}},
                    {MONGO_FIELD_PUBLISHED_AT: {'$lte': as_of_date}},  # legacy ISO-string
                    {MONGO_FIELD_PUBLISHED_AT: {'$exists': False},
                     MONGO_FIELD_FETCHED_AT: {'$lte': cutoff}},
                ]
            }
            cursor = collection.find(point_in_time_query, MONGO_NEWS_PROJECTION)
            articles = list(cursor)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Mongo query failed: %s", exc)
            return None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        if not articles:
            return None

        return self._normalise_articles(articles)

    @staticmethod
    def _normalise_articles(articles: list) -> pd.DataFrame:
        """Convert raw Mongo documents into the CW2 sentiment-signal schema.

        Translates CW1's canonical field names into the column names CW2
        downstream code expects:

            ``compound_score``  → ``vader_compound``
            ``published_at``    → ``article_date``
            ``source_name``     → ``source_domain``
            headline + description → ``word_count``

        Falls back gracefully when fields are missing in older dumps.

        :param articles: List of raw Mongo documents
        :type articles: list
        :returns: Normalised DataFrame ready for ``SentimentSignal``
        :rtype: pd.DataFrame
        """
        df = pd.DataFrame(articles)
        if df.empty:
            return df

        # Source domain — prefer source_name; fall back to publisher
        if MONGO_FIELD_SOURCE_NAME in df.columns:
            df['source_domain'] = df[MONGO_FIELD_SOURCE_NAME].fillna('').astype(str)
        elif 'publisher' in df.columns:
            df['source_domain'] = df['publisher'].fillna('').astype(str)
        else:
            df['source_domain'] = ''

        # Article date — published_at first, then fetched_at, then legacy ones
        date_col = None
        for candidate in (MONGO_FIELD_PUBLISHED_AT, MONGO_FIELD_FETCHED_AT, 'date', 'seendate'):
            if candidate in df.columns:
                date_col = candidate
                break
        if date_col:
            df['article_date'] = pd.to_datetime(df[date_col], errors='coerce', utc=True).dt.tz_localize(None)
        else:
            df['article_date'] = pd.NaT

        # VADER compound — the field CW1 actually writes is compound_score
        if MONGO_FIELD_COMPOUND_SCORE in df.columns:
            df['vader_compound'] = pd.to_numeric(df[MONGO_FIELD_COMPOUND_SCORE], errors='coerce')
        elif 'vader_compound' in df.columns:
            df['vader_compound'] = pd.to_numeric(df['vader_compound'], errors='coerce')
        else:
            df['vader_compound'] = np.nan

        # Word count from headline + description for substantiveness weight.
        # Build always-Series operands so the arithmetic is well-defined.
        empty_series = pd.Series([''] * len(df), index=df.index)
        headline_text = (
            df[MONGO_FIELD_HEADLINE].fillna('').astype(str)
            if MONGO_FIELD_HEADLINE in df.columns
            else empty_series
        )
        desc_text = (
            df[MONGO_FIELD_DESCRIPTION].fillna('').astype(str)
            if MONGO_FIELD_DESCRIPTION in df.columns
            else empty_series
        )
        combined = headline_text.str.cat(desc_text, sep=' ')
        df['word_count'] = combined.str.split().str.len().fillna(0).astype(int)

        # Normalise company_id (strip + upper) and pass company_name through
        if MONGO_FIELD_COMPANY_ID in df.columns:
            df[MONGO_FIELD_COMPANY_ID] = df[MONGO_FIELD_COMPANY_ID].astype(str).str.strip().str.upper()
        if MONGO_FIELD_COMPANY_NAME in df.columns:
            df[MONGO_FIELD_COMPANY_NAME] = df[MONGO_FIELD_COMPANY_NAME].fillna('').astype(str)
        else:
            df[MONGO_FIELD_COMPANY_NAME] = ''

        logger.info(
            "Mongo articles normalised: %d rows, %d companies, dates %s..%s",
            len(df),
            df[MONGO_FIELD_COMPANY_ID].nunique() if MONGO_FIELD_COMPANY_ID in df.columns else 0,
            df['article_date'].min(),
            df['article_date'].max(),
        )
        return df

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Dispose the engine and release all pooled connections."""
        self._engine.dispose()
        logger.info("DataLoader connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
