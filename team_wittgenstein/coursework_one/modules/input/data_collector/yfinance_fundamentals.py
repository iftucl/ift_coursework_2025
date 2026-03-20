"""yfinance fundamentals fallback fetcher."""

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YFinanceMixin:
    """yfinance fundamentals fallback methods for DataFetcher."""

    def _fetch_yfinance_fundamentals(self, symbol):
        """Fetch quarterly fundamentals from yfinance as lowest-priority
        fallback.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            pd.DataFrame with fundamentals, or empty DataFrame.
        """
        try:
            ticker = yf.Ticker(symbol)
            bs = ticker.quarterly_balance_sheet
            inc = ticker.quarterly_income_stmt
        except Exception as e:
            logger.warning("yfinance fundamentals failed for %s: %s", symbol, e)
            return pd.DataFrame()

        if (bs is None or bs.empty) and (inc is None or inc.empty):
            return pd.DataFrame()

        records = {}

        bs_field_map = [
            ("Total Assets", "total_assets"),
            ("Total Debt", "total_debt"),
            ("Stockholders Equity", "book_equity"),
            ("Total Stockholders Equity", "book_equity"),
            ("Ordinary Shares Number", "shares_outstanding"),
            ("Share Issued", "shares_outstanding"),
        ]
        inc_field_map = [
            ("Net Income", "net_income"),
            ("Diluted EPS", "eps"),
        ]

        if bs is not None and not bs.empty:
            for col_date in bs.columns:
                ts = pd.Timestamp(col_date)
                quarter = int((ts.month - 1) // 3) + 1
                key = (ts.year, quarter)
                if key not in records:
                    records[key] = {
                        "symbol": symbol,
                        "fiscal_year": ts.year,
                        "fiscal_quarter": quarter,
                        "report_date": ts,
                        "currency": "USD",
                        "source": "yfinance",
                    }
                for item, field in bs_field_map:
                    if item in bs.index:
                        val = bs.at[item, col_date]
                        if pd.notna(val) and records[key].get(field) is None:
                            records[key][field] = val

        if inc is not None and not inc.empty:
            for col_date in inc.columns:
                ts = pd.Timestamp(col_date)
                quarter = int((ts.month - 1) // 3) + 1
                key = (ts.year, quarter)
                if key not in records:
                    records[key] = {
                        "symbol": symbol,
                        "fiscal_year": ts.year,
                        "fiscal_quarter": quarter,
                        "report_date": ts,
                        "currency": "USD",
                        "source": "yfinance",
                    }
                for item, field in inc_field_map:
                    if item in inc.index:
                        val = inc.at[item, col_date]
                        if pd.notna(val) and records[key].get(field) is None:
                            records[key][field] = val

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(list(records.values()))
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
        return df.sort_values(
            ["fiscal_year", "fiscal_quarter"],
            ascending=[False, False],
        ).reset_index(drop=True)
