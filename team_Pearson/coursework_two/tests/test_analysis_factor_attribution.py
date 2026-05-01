"""Unit tests for CW2 proxy factor attribution."""

from datetime import date

import pandas as pd
from team_Pearson.coursework_two.modules.analysis import factor_attribution as factor_attr


def test_compute_factor_attribution_builds_proxy_rows(monkeypatch):
    run_context = {
        "run_id": "demo-run",
        "run_row": {"benchmark_ticker": "SPY"},
        "config": {"backtest": {"max_forward_fill_days": 5}},
        "periods": [
            {
                "rebalance_date": date(2026, 3, 31),
                "execution_date": date(2026, 4, 1),
                "period_end_date": date(2026, 4, 30),
            }
        ],
    }
    monkeypatch.setattr(
        factor_attr,
        "_load_strategy_holdings",
        lambda run_id, db_engine: {date(2026, 3, 31): {"AAA": 0.6, "BBB": 0.4}},
    )
    monkeypatch.setattr(
        factor_attr,
        "_load_factor_scores",
        lambda rebalance_dates, db_engine: {
            date(2026, 3, 31): pd.DataFrame(
                [
                    {
                        "symbol": "AAA",
                        "quality_score": 1.5,
                        "value_score": 0.2,
                        "market_technical_score": 0.4,
                        "sentiment_score": 0.1,
                        "dividend_score": 0.0,
                    },
                    {
                        "symbol": "BBB",
                        "quality_score": 0.5,
                        "value_score": 0.1,
                        "market_technical_score": 0.3,
                        "sentiment_score": 0.0,
                        "dividend_score": 0.2,
                    },
                    {
                        "symbol": "CCC",
                        "quality_score": -0.3,
                        "value_score": -0.2,
                        "market_technical_score": 0.0,
                        "sentiment_score": -0.1,
                        "dividend_score": 0.3,
                    },
                    {
                        "symbol": "DDD",
                        "quality_score": -0.6,
                        "value_score": -0.4,
                        "market_technical_score": -0.1,
                        "sentiment_score": -0.2,
                        "dividend_score": 0.4,
                    },
                    {
                        "symbol": "EEE",
                        "quality_score": 0.9,
                        "value_score": 0.3,
                        "market_technical_score": 0.2,
                        "sentiment_score": 0.2,
                        "dividend_score": 0.1,
                    },
                    {
                        "symbol": "FFF",
                        "quality_score": -1.0,
                        "value_score": -0.5,
                        "market_technical_score": -0.2,
                        "sentiment_score": -0.3,
                        "dividend_score": 0.5,
                    },
                ]
            )
        },
    )
    monkeypatch.setattr(
        factor_attr,
        "load_trading_calendar",
        lambda *args, **kwargs: [date(2026, 4, 1), date(2026, 4, 30)],
    )
    monkeypatch.setattr(
        factor_attr,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        factor_attr,
        "compute_period_simple_returns",
        lambda *args, **kwargs: (
            {
                "AAA": 0.10,
                "BBB": 0.02,
                "CCC": -0.03,
                "DDD": -0.05,
                "EEE": 0.06,
                "FFF": -0.08,
            },
            {},
        ),
    )

    rows = factor_attr.compute_factor_attribution(run_context, db_engine=object())

    quality_row = next(row for row in rows if row["factor_name"] == "quality")
    assert quality_row["run_id"] == "demo-run"
    assert quality_row["top_bucket_size"] >= 1
    assert quality_row["bottom_bucket_size"] >= 1
    assert quality_row["strategy_exposure"] is not None
    assert quality_row["factor_spread_return"] is not None
    assert quality_row["contribution_proxy"] is not None
