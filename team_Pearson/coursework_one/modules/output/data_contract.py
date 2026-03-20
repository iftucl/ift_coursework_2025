from __future__ import annotations

"""Shared data-contract constants for normalized/loaded factor rows."""

ALLOWED_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "annual", "unknown"}

# Source labels that pipeline modules currently emit.
ALLOWED_SOURCES = {
    "alpha_vantage",
    "yfinance",
    "extractor_b",
    "factor_transform",
    "cache_replay",
}
