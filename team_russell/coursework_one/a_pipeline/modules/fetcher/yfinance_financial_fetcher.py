"""Fetch annual financial statement data from Yahoo Finance.

Uses annual balance sheet, income statement, and cash flow statement
(up to 4 fiscal years), giving ~4 years of historical financial data
per company.

Returns data in the same structure as the Alpha Vantage fetcher so the
downstream transformer is unchanged.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

_DELAY_SECONDS = 0.5  # be polite to yfinance servers


def _extract_bs_reports(ticker) -> list:
    """Extract annual balance sheet reports into standardised dicts.

    Uses ticker.balance_sheet which returns up to 4 fiscal year-end snapshots.
    Includes current_assets and current_liabilities for the WCA quality metric.
    """
    try:
        bs = ticker.balance_sheet
        if bs is None or bs.empty:
            return []

        reports = []
        for col in bs.columns:
            date_str = str(col.date()) if hasattr(col, "date") else str(col)[:10]

            def get(row, _bs=bs, _col=col):
                try:
                    return str(_bs.loc[row, _col]) if row in _bs.index else None
                except Exception:
                    return None

            # Prefer "Total Debt" (current + long-term); fall back to long-term only
            total_debt = get("Total Debt") or get("Long Term Debt")
            reports.append(
                {
                    "fiscalDateEnding": date_str,
                    "totalAssets": get("Total Assets"),
                    "totalLiabilities": get("Total Liabilities Net Minority Interest"),
                    "totalDebt": total_debt,
                    "cashAndCashEquivalentsAtCarryingValue": get("Cash And Cash Equivalents"),
                    "currentAssets": get("Current Assets"),
                    "currentLiabilities": get("Current Liabilities"),
                }
            )
        return reports

    except Exception as exc:
        logger.warning(f"Annual balance sheet parse error: {exc}")
        return []


def _extract_inc_reports(ticker) -> list:
    """Extract annual income statement and cash flow reports into standardised dicts.

    Uses ticker.financials (income) and ticker.cashflow (cash flow), both
    returning up to 4 fiscal year-end snapshots matched by date.
    Includes gross_profit (GPA metric) and free_cash_flow (CF/Y metric).
    """
    try:
        inc = ticker.financials
        if inc is None or inc.empty:
            return []

        # Build a cash flow lookup by date for free_cash_flow
        cf_by_date = {}
        try:
            cf = ticker.cashflow
            if cf is not None and not cf.empty:
                for col in cf.columns:
                    date_str = str(col.date()) if hasattr(col, "date") else str(col)[:10]
                    try:
                        fcf = (
                            str(cf.loc["Free Cash Flow", col])
                            if "Free Cash Flow" in cf.index
                            else None
                        )
                    except Exception:
                        fcf = None
                    cf_by_date[date_str] = fcf
        except Exception as exc:
            logger.warning(f"Cash flow parse error: {exc}")

        # Trailing annual dividend rate (single value, same for all report years)
        annual_dividend_rate = None
        try:
            info = ticker.info
            annual_dividend_rate = str(info.get("trailingAnnualDividendRate", 0.0) or 0.0)
        except Exception:
            annual_dividend_rate = "0.0"

        reports = []
        for col in inc.columns:
            date_str = str(col.date()) if hasattr(col, "date") else str(col)[:10]

            def get(row, _inc=inc, _col=col):
                try:
                    return str(_inc.loc[row, _col]) if row in _inc.index else None
                except Exception:
                    return None

            reports.append(
                {
                    "fiscalDateEnding": date_str,
                    "netIncome": get("Net Income"),
                    "ebitda": get("EBITDA"),
                    "totalRevenue": get("Total Revenue"),
                    "grossProfit": get("Gross Profit"),
                    "freeCashFlow": cf_by_date.get(date_str),
                    "annualDividendRate": annual_dividend_rate,
                }
            )
        return reports

    except Exception as exc:
        logger.warning(f"Annual income statement parse error: {exc}")
        return []


def fetch_financials_yfinance(symbol: str) -> Optional[dict]:
    """Fetch annual balance sheet, income statement, and cash flow for a symbol.

    Fetches up to 4 years of annual data using ticker.balance_sheet,
    ticker.financials, and ticker.cashflow. Returns data formatted to match
    the Alpha Vantage transformer structure so the downstream pipeline is
    unchanged.

    Args:
        symbol: Ticker symbol.

    Returns:
        Dict with keys symbol, balance_sheet, income_statement, fetched_at.
        Returns None if no data is available.
    """
    try:
        ticker = yf.Ticker(symbol.strip())

        bs_reports = _extract_bs_reports(ticker)
        inc_reports = _extract_inc_reports(ticker)

        if not bs_reports and not inc_reports:
            logger.warning(f"No annual financial data available for {symbol}")
            return None

        fetched_at = datetime.now(timezone.utc).isoformat()

        return {
            "symbol": symbol.strip(),
            "balance_sheet": {
                "symbol": symbol.strip(),
                "type": "balance_sheet",
                "data": {"quarterlyReports": bs_reports},
                "fetched_at": fetched_at,
            },
            "income_statement": {
                "symbol": symbol.strip(),
                "type": "income_statement",
                "data": {"quarterlyReports": inc_reports},
                "fetched_at": fetched_at,
            },
        }

    except Exception as exc:
        logger.error(f"Failed to fetch financials for {symbol}: {exc}")
        return None
    finally:
        time.sleep(_DELAY_SECONDS)
