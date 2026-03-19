"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : PostgreSQL data loader with upsert support
Project : CW1 - Value + News Sentiment Strategy

Provides upsert (INSERT ... ON CONFLICT DO UPDATE) operations for
all pipeline tables, ensuring re-runnable ingestion without duplicates.

Tables managed:
  - daily_prices       (OHLCV per ticker per day)
  - value_metrics      (P/E, P/B, EV/EBITDA, dividends, D/E, value score)
  - sentiment_scores   (VADER aggregated scores per ticker)
  - composite_rankings (final combined score + invest decision)
  - fx_rates           (daily exchange rates)
  - ingestion_log      (audit trail of every pipeline run)
"""

from sqlalchemy import text

from modules.db.postgres_connection import DatabaseClient
from modules.utils.logger import pipeline_logger


def upsert_daily_prices(db: DatabaseClient, records: list[dict]) -> int:
    """Upsert daily OHLCV price records into systematic_equity.daily_prices.

    :param db: Active database client
    :type db: DatabaseClient
    :param records: List of price record dicts
    :type records: list[dict]
    :return: Number of rows affected
    :rtype: int
    """
    if not records:
        return 0
    sql = text(
        """
        INSERT INTO systematic_equity.daily_prices
            (symbol, cob_date, open_price, high_price, low_price,
             close_price, adj_close_price, volume, currency)
        VALUES
            (:symbol, :cob_date, :open_price, :high_price, :low_price,
             :close_price, :adj_close_price, :volume, :currency)
        ON CONFLICT (symbol, cob_date) DO UPDATE SET
            open_price = EXCLUDED.open_price,
            high_price = EXCLUDED.high_price,
            low_price = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            adj_close_price = EXCLUDED.adj_close_price,
            volume = EXCLUDED.volume,
            ingestion_timestamp = NOW()
    """
    )
    count = _execute_batch(db, sql, records)
    pipeline_logger.info("Upserted %d price records", count)
    return count


def upsert_value_metrics(db: DatabaseClient, records: list[dict]) -> int:
    """Upsert value metric records into systematic_equity.value_metrics.

    :param db: Active database client
    :type db: DatabaseClient
    :param records: List of value metric dicts
    :type records: list[dict]
    :return: Number of rows affected
    :rtype: int
    """
    if not records:
        return 0
    sql = text(
        """
        INSERT INTO systematic_equity.value_metrics
            (company_id, date, pe_ratio, pb_ratio, ev_ebitda,
             dividend_yield, debt_equity, value_score)
        VALUES
            (:company_id, :date, :pe_ratio, :pb_ratio, :ev_ebitda,
             :dividend_yield, :debt_equity, :value_score)
        ON CONFLICT (company_id, date) DO UPDATE SET
            pe_ratio = EXCLUDED.pe_ratio,
            pb_ratio = EXCLUDED.pb_ratio,
            ev_ebitda = EXCLUDED.ev_ebitda,
            dividend_yield = EXCLUDED.dividend_yield,
            debt_equity = EXCLUDED.debt_equity,
            value_score = EXCLUDED.value_score,
            ingestion_timestamp = NOW()
    """
    )
    count = _execute_batch(db, sql, records)
    pipeline_logger.info("Upserted %d value metric records", count)
    return count


def upsert_sentiment_scores(db: DatabaseClient, records: list[dict]) -> int:
    """Upsert sentiment score records into systematic_equity.sentiment_scores.

    :param db: Active database client
    :type db: DatabaseClient
    :param records: List of sentiment score dicts
    :type records: list[dict]
    :return: Number of rows affected
    :rtype: int
    """
    if not records:
        return 0
    sql = text(
        """
        INSERT INTO systematic_equity.sentiment_scores
            (company_id, date, avg_sentiment, positive_count, negative_count,
             neutral_count, total_articles, positive_ratio, sentiment_score)
        VALUES
            (:company_id, :date, :avg_sentiment, :positive_count, :negative_count,
             :neutral_count, :total_articles, :positive_ratio, :sentiment_score)
        ON CONFLICT (company_id, date) DO UPDATE SET
            avg_sentiment = EXCLUDED.avg_sentiment,
            positive_count = EXCLUDED.positive_count,
            negative_count = EXCLUDED.negative_count,
            neutral_count = EXCLUDED.neutral_count,
            total_articles = EXCLUDED.total_articles,
            positive_ratio = EXCLUDED.positive_ratio,
            sentiment_score = EXCLUDED.sentiment_score,
            ingestion_timestamp = NOW()
    """
    )
    count = _execute_batch(db, sql, records)
    pipeline_logger.info("Upserted %d sentiment records", count)
    return count


def upsert_composite_rankings(db: DatabaseClient, records: list[dict]) -> int:
    """Upsert composite ranking records into systematic_equity.composite_rankings.

    :param db: Active database client
    :type db: DatabaseClient
    :param records: List of composite ranking dicts
    :type records: list[dict]
    :return: Number of rows affected
    :rtype: int
    """
    if not records:
        return 0
    sql = text(
        """
        INSERT INTO systematic_equity.composite_rankings
            (company_id, date, value_score, sentiment_score,
             composite_score, rank, invest_decision)
        VALUES
            (:company_id, :date, :value_score, :sentiment_score,
             :composite_score, :rank, :invest_decision)
        ON CONFLICT (company_id, date) DO UPDATE SET
            value_score = EXCLUDED.value_score,
            sentiment_score = EXCLUDED.sentiment_score,
            composite_score = EXCLUDED.composite_score,
            rank = EXCLUDED.rank,
            invest_decision = EXCLUDED.invest_decision,
            ingestion_timestamp = NOW()
    """
    )
    count = _execute_batch(db, sql, records)
    pipeline_logger.info("Upserted %d composite rankings", count)
    return count


def upsert_fx_rates(db: DatabaseClient, records: list[dict]) -> int:
    """Upsert FX rate records into systematic_equity.fx_rates.

    :param db: Active database client
    :type db: DatabaseClient
    :param records: FX rate record dicts
    :type records: list[dict]
    :return: Number of rows affected
    :rtype: int
    """
    if not records:
        return 0
    sql = text(
        """
        INSERT INTO systematic_equity.fx_rates
            (currency_pair, cob_date, open_rate, high_rate, low_rate, close_rate)
        VALUES
            (:currency_pair, :cob_date, :open_rate, :high_rate, :low_rate, :close_rate)
        ON CONFLICT (currency_pair, cob_date) DO UPDATE SET
            open_rate = EXCLUDED.open_rate,
            high_rate = EXCLUDED.high_rate,
            low_rate = EXCLUDED.low_rate,
            close_rate = EXCLUDED.close_rate,
            ingestion_timestamp = NOW()
    """
    )
    count = _execute_batch(db, sql, records)
    pipeline_logger.info("Upserted %d FX rate records", count)
    return count


def insert_ingestion_log(
    db: DatabaseClient,
    run_id: str,
    data_source: str,
    symbol: str = None,
    status: str = "SUCCESS",
    rows_affected: int = 0,
    error_message: str = None,
    run_frequency: str = None,
    date_range_start: str = None,
    date_range_end: str = None,
):
    """Record a pipeline run event in the ingestion audit log.

    :param db: Active database client
    :type db: DatabaseClient
    :param run_id: Unique run identifier (UUID)
    :type run_id: str
    :param data_source: Source identifier (e.g. 'yfinance', 'gdelt')
    :type data_source: str
    :param symbol: Ticker symbol (optional)
    :type symbol: str or None
    :param status: Run status (SUCCESS, FAILED, SKIPPED)
    :type status: str
    :param rows_affected: Number of rows ingested
    :type rows_affected: int
    :param error_message: Error details if failed
    :type error_message: str or None
    :param run_frequency: Pipeline frequency (daily, weekly, etc.)
    :type run_frequency: str or None
    :param date_range_start: Start of data range
    :type date_range_start: str or None
    :param date_range_end: End of data range
    :type date_range_end: str or None
    """
    sql = text(
        """
        INSERT INTO systematic_equity.ingestion_log
            (run_id, data_source, symbol, status, rows_affected,
             error_message, run_frequency, date_range_start, date_range_end)
        VALUES
            (:run_id, :data_source, :symbol, :status, :rows_affected,
             :error_message, :run_frequency, :date_range_start, :date_range_end)
    """
    )
    try:
        session = db.session
        session.execute(
            sql,
            {
                "run_id": run_id,
                "data_source": data_source,
                "symbol": symbol,
                "status": status,
                "rows_affected": rows_affected,
                "error_message": error_message,
                "run_frequency": run_frequency,
                "date_range_start": date_range_start,
                "date_range_end": date_range_end,
            },
        )
        session.commit()
        session.close()
    except Exception as e:
        pipeline_logger.warning("Failed to write ingestion log: %s", e)


def _execute_batch(db: DatabaseClient, sql, records: list[dict]) -> int:
    """Execute a batch of parameterised SQL statements.

    :param db: Database client
    :param sql: SQLAlchemy text statement
    :param records: List of parameter dicts
    :return: Number of records processed
    :rtype: int
    """
    session = db.session
    try:
        for record in records:
            session.execute(sql, record)
        session.commit()
        return len(records)
    except Exception as e:
        session.rollback()
        pipeline_logger.error("Batch upsert failed: %s", e)
        return 0
    finally:
        session.close()
