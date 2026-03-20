"""Load processed price and financial data from PostgreSQL for factor computation."""

import calendar
import logging
from datetime import date

import pandas as pd
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# Spec requires 5 consecutive years; yfinance caps at 4, so we use 4 as the threshold.
_MIN_YEARS = 4

# 3-month lag on financial data to prevent look-ahead bias (per spec section 9).
# yfinance labels data by fiscal year-end date (not publication date). A 3-month
# lag is used because US SEC rules allow up to 90 days after fiscal year-end for
# 10-K filing. This correctly excludes October and November fiscal year-end
# companies whose reports are not yet filed at the December 31 rebalance date,
# while including all other fiscal year-ends (Jun, Sep, Mar, Dec-prior-year, etc.)
_LAG_MONTHS = 3


def _engine(pg_config: dict):
    url = (
        f"postgresql+psycopg2://{pg_config['user']}:{pg_config['password']}"
        f"@{pg_config['host']}:{pg_config['port']}/{pg_config['database']}"
    )
    return create_engine(url)


def load_factor_inputs(pg_config: dict, quarter_end_date: str) -> pd.DataFrame:
    """Load data needed to compute the composite factor for one year-end date.

    For each company, selects:
      - The most recent closing price on or before the rebalance date.
      - The most recent annual financial report whose fiscal year-end is at
        least _LAG_MONTHS before the rebalance date (look-ahead bias prevention).
      - The GICS sector from company_static for sector-neutral scoring and
        eligibility filtering (Financials and Real Estate are excluded).

    Using DISTINCT ON instead of an exact date match correctly handles companies
    with non-December fiscal year-ends (e.g. Apple Sep 30, Microsoft Jun 30).

    Only includes companies with at least _MIN_YEARS of annual financial
    records in the database (universe eligibility filter).

    Args:
        pg_config: PostgreSQL connection config dict.
        quarter_end_date: Year-end rebalance date string 'YYYY-MM-DD'.

    Returns:
        DataFrame with one row per eligible company containing all fields
        needed for value and quality factor computation.
    """
    sql = text(
        """
        WITH eligible_companies AS (
            -- Keep only companies with sufficient years of financial history
            SELECT symbol
            FROM systematic_equity.financials
            GROUP BY symbol
            HAVING COUNT(*) >= :min_years
        ),
        latest_price AS (
            -- Most recent price on or before rebalance date
            SELECT DISTINCT ON (symbol)
                symbol,
                closing_price,
                shares_outstanding
            FROM systematic_equity.price_history
            WHERE price_date <= :qdate
            ORDER BY symbol, price_date DESC
        ),
        latest_financials AS (
            -- Most recent annual report with fiscal year-end at least 3 months
            -- before the rebalance date. This handles all fiscal year-ends
            -- correctly and prevents look-ahead bias:
            --   Jun 30 companies: FY2024 data passes  (Jun 30 <= Sep 30) ✓
            --   Sep 30 companies: FY2024 data passes  (Sep 30 <= Sep 30) ✓
            --   Oct 31 companies: FY2024 data blocked (Oct 31 > Sep 30)  ✓ (10-K not filed yet)
            --   Nov 30 companies: FY2024 data blocked (Nov 30 > Sep 30)  ✓ (10-K not filed yet)
            --   Dec 31 companies: FY2023 data passes  (Dec 31, 2023 <= Sep 30, 2024) ✓
            --                     FY2024 data blocked (Dec 31, 2024 > Sep 30, 2024) ✓
            SELECT DISTINCT ON (symbol)
                symbol,
                period_date,
                total_assets,
                total_liabilities,
                net_income_ttm,
                ebitda_ttm,
                total_debt,
                cash_and_equivalents,
                book_value,
                revenue,
                gross_profit,
                free_cash_flow,
                current_assets,
                current_liabilities,
                annual_dividend_rate
            FROM systematic_equity.financials
            WHERE period_date <= :lag_cutoff
            ORDER BY symbol, period_date DESC
        )
        SELECT
            f.symbol,
            cs.gics_sector,
            p.closing_price,
            p.shares_outstanding,
            f.total_assets,
            f.total_liabilities,
            f.net_income_ttm,
            f.ebitda_ttm,
            f.total_debt,
            f.cash_and_equivalents,
            f.book_value,
            f.revenue,
            f.gross_profit,
            f.free_cash_flow,
            f.current_assets,
            f.current_liabilities,
            f.annual_dividend_rate
        FROM latest_financials f
        JOIN latest_price p USING (symbol)
        JOIN eligible_companies e USING (symbol)
        LEFT JOIN systematic_equity.company_static cs USING (symbol)
    """
    )

    # Compute the lag cutoff in Python to avoid SQLAlchemy/psycopg2 conflicts
    # with the PostgreSQL :: cast syntax inside parameterised queries.
    qdate = date.fromisoformat(quarter_end_date)
    lag_month = qdate.month - _LAG_MONTHS
    lag_year = qdate.year + (lag_month - 1) // 12
    lag_month = (lag_month - 1) % 12 + 1
    lag_day = min(qdate.day, calendar.monthrange(lag_year, lag_month)[1])
    lag_cutoff = date(lag_year, lag_month, lag_day).isoformat()

    engine = _engine(pg_config)
    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "qdate": quarter_end_date,
                "min_years": _MIN_YEARS,
                "lag_cutoff": lag_cutoff,
            },
        )

    # Fill NULL gics_sector with a placeholder so sector logic handles it cleanly
    df["gics_sector"] = df["gics_sector"].fillna("Unknown")

    logger.info(
        f"Loaded {len(df)} companies for {quarter_end_date} "
        f"(financials lag cutoff: {lag_cutoff}, min {_MIN_YEARS} years filter)"
    )
    return df
