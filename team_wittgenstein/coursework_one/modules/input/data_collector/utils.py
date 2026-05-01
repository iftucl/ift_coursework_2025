"""Shared utility functions for data fetching."""

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class UtilsMixin:
    """Shared utility methods for DataFetcher."""

    @staticmethod
    def _ensure_fundamentals_schema(df):
        """Ensure fundamentals DataFrame conforms to expected output schema."""
        columns = [
            "symbol",
            "fiscal_year",
            "fiscal_quarter",
            "report_date",
            "currency",
            "total_assets",
            "total_debt",
            "net_income",
            "book_equity",
            "shares_outstanding",
            "eps",
            "source",
        ]
        if df is None or df.empty:
            return pd.DataFrame(columns=columns)

        out = df.copy()

        # Handle legacy column names
        if "book_value_equity" in out.columns and "book_equity" not in out.columns:
            out = out.rename(columns={"book_value_equity": "book_equity"})
        if "total_equity" in out.columns and "book_equity" not in out.columns:
            out = out.rename(columns={"total_equity": "book_equity"})

        for col in columns:
            if col not in out.columns:
                out[col] = None

        out["report_date"] = pd.to_datetime(out["report_date"], errors="coerce")
        out["fiscal_year"] = pd.to_numeric(out["fiscal_year"], errors="coerce").astype(
            "Int64"
        )
        out["fiscal_quarter"] = pd.to_numeric(
            out["fiscal_quarter"], errors="coerce"
        ).astype("Int64")
        out["shares_outstanding"] = (
            pd.to_numeric(out["shares_outstanding"], errors="coerce")
            .round()
            .astype("Int64")
        )
        out["source"] = out["source"].fillna("unknown")
        return out[columns]

    @staticmethod
    def _apply_fundamentals_period(df, period):
        """Filter fundamentals to the most recent N quarters per symbol.

        For a period like "5y", keeps the most recent 20 quarters (5 x 4)
        per symbol rather than using a date cutoff, which can miss quarters
        near the boundary.
        """
        if df is None or df.empty:
            return df

        out = df.copy()
        out = out.sort_values(
            ["symbol", "fiscal_year", "fiscal_quarter"],
            ascending=[True, False, False],
        )

        p = (period or "5y").strip().lower()
        if p == "max":
            return out

        if p.endswith("y"):
            try:
                years = int(p[:-1])
                if years > 0:
                    max_quarters = years * 4
                    out = out.groupby("symbol").head(max_quarters)
                    return out
            except ValueError:
                pass
        return out

    @staticmethod
    def _period_years(period, default_years=5):
        """Parse period string ('5y', 'max') to integer years or None."""
        p = (period or f"{default_years}y").strip().lower()
        if p == "max":
            return None
        if p.endswith("y"):
            try:
                years = int(p[:-1])
                if years > 0:
                    return years
            except ValueError:
                pass
        return default_years

    def _classify_missing(self, symbols):
        """Classify why symbols returned no data.

        For each symbol that produced no rows, checks ticker.info to
        determine whether the company is genuinely delisted (expected,
        acceptable) or whether the fetch failed for another reason
        (network error, rate limit - should be investigated).

        Args:
            symbols: List of symbol strings that returned no data.

        Returns:
            dict with keys:
                'delisted'    - list of symbols confirmed delisted/invalid
                'fetch_error' - list of symbols that should have data
        """
        delisted = []
        fetch_error = []

        for symbol in symbols:
            try:
                info = yf.Ticker(symbol).info
                if not info or info.get("regularMarketPrice") is None:
                    delisted.append(symbol)
                    logger.info("classify_missing: %s appears delisted", symbol)
                else:
                    fetch_error.append(symbol)
                    logger.warning(
                        "classify_missing: %s is active but returned no data "
                        "(possible fetch error)",
                        symbol,
                    )
            except Exception as e:
                fetch_error.append(symbol)
                logger.warning("classify_missing: could not check %s: %s", symbol, e)

        logger.info(
            "Missing symbol classification: %d delisted, %d fetch errors",
            len(delisted),
            len(fetch_error),
        )
        return {"delisted": delisted, "fetch_error": fetch_error}
