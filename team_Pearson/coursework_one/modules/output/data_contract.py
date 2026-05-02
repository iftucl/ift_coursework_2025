from __future__ import annotations

"""Shared data-contract constants for normalized/loaded factor rows."""

ALLOWED_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "annual", "unknown"}

# Source labels that pipeline modules currently emit.
ALLOWED_SOURCES = {
    "alpha_vantage",
    "yfinance",
    "av+finnhub",
    "edgar_xbrl",
    "edgar_xbrl_derived",
    "financial_publish_calendar",
    "factor_transform",
    "factor_transform_market",
    "cache_replay",
}
