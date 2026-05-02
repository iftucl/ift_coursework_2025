import numpy as np
import pandas as pd

from modules.models import CW1Inputs
from modules.snapshot_builder import build_monthly_snapshot_history


def test_build_monthly_snapshot_history_from_raw_prices():
    dates = pd.bdate_range("2024-01-01", periods=320)
    records = []
    for symbol, base_price, drift in [("AAA", 100.0, 0.0015), ("BBB", 80.0, 0.0005)]:
        for idx, date in enumerate(dates):
            close = base_price * ((1 + drift) ** idx)
            records.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": 1_000_000 + idx * 1000,
                }
            )

    price_history = pd.DataFrame(records)
    cw1_inputs = CW1Inputs(
        universe_snapshot=pd.DataFrame(),
        factors=pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "gics_sector": ["Tech", "Tech"],
                "sector": ["Tech", "Tech"],
            }
        ),
        selections=pd.DataFrame(),
        signals=pd.DataFrame(),
        price_history=price_history,
    )
    config = {"universe": {"min_rows_per_symbol": 252}}

    factors_history, selections_history = build_monthly_snapshot_history(cw1_inputs, config)

    assert not factors_history.empty
    assert not selections_history.empty
    assert "snapshot_date" in factors_history.columns
    assert "composite_score" in factors_history.columns
    assert factors_history["snapshot_date"].nunique() >= 2
    assert set(selections_history["symbol"]).issubset({"AAA", "BBB"})


def test_build_monthly_snapshot_history_respects_shorter_configured_lookback():
    dates = pd.bdate_range("2024-01-01", periods=80)
    records = []
    for symbol, base_price, drift in [("AAA", 100.0, 0.0015), ("BBB", 80.0, 0.0005)]:
        for idx, date in enumerate(dates):
            close = base_price * ((1 + drift) ** idx)
            records.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": 1_000_000 + idx * 1000,
                }
            )

    price_history = pd.DataFrame(records)
    cw1_inputs = CW1Inputs(
        universe_snapshot=pd.DataFrame(),
        factors=pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "gics_sector": ["Tech", "Tech"],
                "sector": ["Tech", "Tech"],
            }
        ),
        selections=pd.DataFrame(),
        signals=pd.DataFrame(),
        price_history=price_history,
    )

    factors_history, selections_history = build_monthly_snapshot_history(cw1_inputs, {"universe": {"min_rows_per_symbol": 24}})

    assert not factors_history.empty
    assert not selections_history.empty
    assert factors_history["snapshot_date"].min() == pd.Timestamp("2024-02-29")
