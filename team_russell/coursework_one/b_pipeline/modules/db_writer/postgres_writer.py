"""Write processed records into PostgreSQL systematic_equity tables."""

import logging
from typing import List

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class PostgresWriter:
    """Upserts processed price and financial records into PostgreSQL.

    Args:
        host, port, user, password, database: Connection parameters.
    """

    def __init__(self, host: str, port: int, user: str, password: str, database: str) -> None:
        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
        self._engine = create_engine(url)

    def upsert_prices(self, records: List[dict]) -> None:
        """Upsert daily price records into systematic_equity.price_history.

        Args:
            records: List of dicts with symbol, price_date, closing_price,
                     shares_outstanding.
        """
        if not records:
            return

        sql = text(
            """
            INSERT INTO systematic_equity.price_history
                (symbol, price_date, closing_price, shares_outstanding)
            VALUES
                (:symbol, :price_date, :closing_price, :shares_outstanding)
            ON CONFLICT (symbol, price_date) DO UPDATE SET
                closing_price      = EXCLUDED.closing_price,
                shares_outstanding = COALESCE(
                    EXCLUDED.shares_outstanding,
                    price_history.shares_outstanding
                )
        """
        )

        with self._engine.begin() as conn:
            conn.execute(sql, records)

        logger.info(f"Upserted {len(records)} price records for {records[0]['symbol']}")

    def upsert_financials(self, symbol: str, records: List[dict]) -> None:
        """Upsert quarterly financial records into systematic_equity.financials.

        Args:
            symbol: Ticker symbol.
            records: List of dicts from transformer.transform_financials().
        """
        if not records:
            return

        sql = text(
            """
            INSERT INTO systematic_equity.financials
                (symbol, period_date, total_assets, total_liabilities,
                 net_income_ttm, ebitda_ttm, total_debt, cash_and_equivalents,
                 book_value, revenue, gross_profit, free_cash_flow,
                 current_assets, current_liabilities, annual_dividend_rate)
            VALUES
                (:symbol, :period_date, :total_assets, :total_liabilities,
                 :net_income_ttm, :ebitda_ttm, :total_debt, :cash_and_equivalents,
                 :book_value, :revenue, :gross_profit, :free_cash_flow,
                 :current_assets, :current_liabilities, :annual_dividend_rate)
            ON CONFLICT (symbol, period_date) DO UPDATE SET
                total_assets          = EXCLUDED.total_assets,
                total_liabilities     = EXCLUDED.total_liabilities,
                net_income_ttm        = EXCLUDED.net_income_ttm,
                ebitda_ttm            = EXCLUDED.ebitda_ttm,
                total_debt            = EXCLUDED.total_debt,
                cash_and_equivalents  = EXCLUDED.cash_and_equivalents,
                book_value            = EXCLUDED.book_value,
                revenue               = EXCLUDED.revenue,
                gross_profit          = EXCLUDED.gross_profit,
                free_cash_flow        = EXCLUDED.free_cash_flow,
                current_assets        = EXCLUDED.current_assets,
                current_liabilities   = EXCLUDED.current_liabilities,
                annual_dividend_rate  = EXCLUDED.annual_dividend_rate
        """
        )

        enriched = [{"symbol": symbol, **rec} for rec in records]
        with self._engine.begin() as conn:
            conn.execute(sql, enriched)

        logger.info(f"Upserted {len(records)} financial records for {symbol}")
