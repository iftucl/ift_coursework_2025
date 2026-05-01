"""Unit tests for CW2 investable universe screening."""

from datetime import date

import pandas as pd
from team_Pearson.coursework_two.modules.portfolio.universe_screen import build_investable_universe


def test_universe_screen_applies_percentile_and_floor_filters():
    risk_data = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT", "MID", "SMALL", "ILLQ"],
            "log_market_cap": [28.0, 27.5, 22.0, 19.5, 23.0],
            "liquidity_20d": [1.2e9, 9e8, 8e6, 3e6, 5e5],
        }
    )
    company_info = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT", "MID", "SMALL", "ILLQ"],
            "gics_sector": [
                "Tech",
                "Tech",
                "Industrials",
                "Industrials",
                "Health Care",
            ],
            "country": ["US", "US", "US", "US", "US"],
        }
    )

    config = {
        "investable_universe": {
            "min_market_cap_log": 20.0,
            "market_cap_bottom_percentile": 0.20,
            "min_liquidity_20d": 2_000_000,
            "liquidity_bottom_percentile": 0.20,
        }
    }
    out = build_investable_universe(
        risk_data,
        company_info,
        as_of_date=date(2026, 4, 14),
        config=config,
    )
    lookup = {row["symbol"]: row for row in out}
    assert lookup["AAPL"]["pass_all"] is True
    assert lookup["MSFT"]["pass_all"] is True
    assert lookup["MID"]["pass_all"] is True
    assert lookup["SMALL"]["pass_market_cap"] is False
    assert lookup["ILLQ"]["pass_liquidity"] is False


def test_universe_screen_can_apply_country_filter():
    risk_data = pd.DataFrame(
        {
            "symbol": ["AAPL", "VOD"],
            "log_market_cap": [28.0, 24.0],
            "liquidity_20d": [1.2e9, 2e7],
        }
    )
    company_info = pd.DataFrame(
        {
            "symbol": ["AAPL", "VOD"],
            "gics_sector": ["Tech", "Communication Services"],
            "country": ["US", "GB"],
        }
    )

    config = {
        "investable_universe": {
            "country_allowlist": ["US"],
            "min_market_cap_log": None,
            "market_cap_bottom_percentile": None,
            "min_liquidity_20d": None,
            "liquidity_bottom_percentile": None,
        }
    }
    out = build_investable_universe(
        risk_data,
        company_info,
        as_of_date=date(2026, 4, 14),
        config=config,
    )
    lookup = {row["symbol"]: row for row in out}
    assert lookup["AAPL"]["pass_country"] is True
    assert lookup["VOD"]["pass_country"] is False
    assert lookup["VOD"]["pass_all"] is False
