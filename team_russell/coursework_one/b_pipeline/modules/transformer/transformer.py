"""Transform raw API data into structured records ready for database storage."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_float(value) -> Optional[float]:
    """Convert a value to float, returning None if not possible or NaN."""
    try:
        result = float(value)
        return None if result != result else result  # NaN != NaN is True
    except (TypeError, ValueError):
        return None


def transform_prices(raw: dict) -> list:
    """Flatten raw yfinance price dict into a list of daily price records.

    Args:
        raw: Dict with keys symbol, prices (date→price), shares_outstanding.

    Returns:
        List of dicts each with symbol, price_date, closing_price, shares_outstanding.
    """
    symbol = raw["symbol"].strip()
    shares = raw.get("shares_outstanding")

    records = []
    for date_str, price in raw.get("prices", {}).items():
        records.append(
            {
                "symbol": symbol,
                "price_date": date_str,
                "closing_price": _safe_float(price),
                "shares_outstanding": shares,
            }
        )
    return records


def transform_financials(balance_sheet: dict, income_statement: dict) -> list:
    """Align annual balance sheet and income statement into financial records.

    Matches reports by fiscal date. Only dates present in both sources
    are included. Income statement records also carry cash flow fields
    (free_cash_flow) and dividend data (annual_dividend_rate) fetched
    alongside the income statement in Pipeline A.

    Args:
        balance_sheet: Raw dict from fetch_balance_sheet (contains 'data').
        income_statement: Raw dict from fetch_income_statement (contains 'data').

    Returns:
        List of dicts with standardised financial fields per fiscal year.
    """
    bs_reports = balance_sheet.get("data", {}).get("quarterlyReports", [])
    inc_reports = income_statement.get("data", {}).get("quarterlyReports", [])

    # Index income reports by fiscal date for fast lookup
    inc_by_date = {r["fiscalDateEnding"]: r for r in inc_reports}

    records = []
    for bs in bs_reports:
        date = bs.get("fiscalDateEnding")
        if not date:
            continue

        inc = inc_by_date.get(date, {})

        total_assets = _safe_float(bs.get("totalAssets"))
        total_liabilities = _safe_float(bs.get("totalLiabilities"))
        # Prefer totalDebt (current + long-term); fall back to longTermDebt
        total_debt = _safe_float(bs.get("totalDebt")) or _safe_float(bs.get("longTermDebt")) or 0.0
        cash = _safe_float(bs.get("cashAndCashEquivalentsAtCarryingValue"))
        current_assets = _safe_float(bs.get("currentAssets"))
        current_liabilities = _safe_float(bs.get("currentLiabilities"))

        net_income = _safe_float(inc.get("netIncome"))
        ebitda = _safe_float(inc.get("ebitda"))
        revenue = _safe_float(inc.get("totalRevenue"))
        gross_profit = _safe_float(inc.get("grossProfit"))
        free_cash_flow = _safe_float(inc.get("freeCashFlow"))
        annual_dividend_rate = _safe_float(inc.get("annualDividendRate")) or 0.0

        book_value = None
        if total_assets is not None and total_liabilities is not None:
            book_value = total_assets - total_liabilities

        records.append(
            {
                "period_date": date,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_debt": total_debt,
                "cash_and_equivalents": cash,
                "net_income_ttm": net_income,
                "ebitda_ttm": ebitda,
                "book_value": book_value,
                "revenue": revenue,
                "gross_profit": gross_profit,
                "free_cash_flow": free_cash_flow,
                "current_assets": current_assets,
                "current_liabilities": current_liabilities,
                "annual_dividend_rate": annual_dividend_rate,
            }
        )

    return records
