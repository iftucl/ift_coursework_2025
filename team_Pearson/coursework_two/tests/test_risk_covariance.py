"""Unit tests for shared covariance helpers."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from team_Pearson.coursework_two.modules.risk.actions import PendingRiskAction, build_action_event
from team_Pearson.coursework_two.modules.risk.covariance import (
    build_return_panel,
    covariance_quality,
    estimate_fundamental_factor_covariance,
    estimate_shrunk_covariance,
    estimate_statistical_factor_covariance,
)


def test_build_return_panel_masks_forward_filled_days():
    calendar = [
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    ]
    prices = pd.DataFrame(
        {
            "AAA": [100.0, 101.0, None, 103.0, 104.0],
            "BBB": [50.0, 51.0, 52.0, 53.0, 54.0],
        },
        index=calendar,
    )

    returns = build_return_panel(
        prices,
        trading_calendar=calendar,
        start_date=calendar[0],
        end_date=calendar[-1],
        lookback_days=10,
        min_history_days=2,
        max_forward_fill_days=5,
    )

    assert date(2026, 1, 7) in returns.index
    assert pd.isna(returns.loc[date(2026, 1, 7), "AAA"])
    assert pd.isna(returns.loc[date(2026, 1, 8), "AAA"])
    assert pd.notna(returns.loc[date(2026, 1, 7), "BBB"])


def test_covariance_quality_rejects_near_singular_matrix():
    covariance = pd.DataFrame(
        [[1.0, 1.0], [1.0, 1.0]],
        index=["A", "B"],
        columns=["A", "B"],
    )

    quality = covariance_quality(covariance)

    assert quality["is_usable"] is False
    assert quality["reason"] in {"near_singular", "ill_conditioned"}


def test_statistical_factor_covariance_returns_usable_matrix():
    returns = pd.DataFrame(
        {
            "AAA": [0.010, 0.012, -0.004, 0.006, 0.003, -0.002],
            "BBB": [0.008, 0.011, -0.003, 0.005, 0.004, -0.001],
            "CCC": [-0.006, -0.004, 0.009, -0.002, 0.001, 0.007],
            "DDD": [0.002, -0.001, 0.003, 0.004, -0.002, 0.001],
        }
    )

    covariance = estimate_statistical_factor_covariance(
        returns,
        factor_count=2,
        max_factor_count=3,
        specific_variance_floor_ratio=0.10,
    )

    assert list(covariance.index) == ["AAA", "BBB", "CCC", "DDD"]
    assert list(covariance.columns) == ["AAA", "BBB", "CCC", "DDD"]
    assert covariance.equals(covariance.T)
    quality = covariance_quality(covariance)
    assert quality["is_usable"] is True


def test_estimate_shrunk_covariance_supports_statistical_factor_method():
    returns = pd.DataFrame(
        {
            "AAA": [0.010, 0.012, -0.004, 0.006, 0.003, -0.002],
            "BBB": [0.008, 0.011, -0.003, 0.005, 0.004, -0.001],
            "CCC": [-0.006, -0.004, 0.009, -0.002, 0.001, 0.007],
        }
    )

    covariance = estimate_shrunk_covariance(
        returns,
        shrinkage_intensity=0.25,
        method="statistical_factor",
        factor_count=1,
    )

    assert covariance.shape == (3, 3)
    assert covariance_quality(covariance)["is_usable"] is True


def test_fundamental_factor_covariance_returns_usable_matrix():
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    sectors = {
        "AAA": "Technology",
        "BBB": "Technology",
        "CCC": "Health Care",
        "DDD": "Health Care",
        "EEE": "Financials",
        "FFF": "Financials",
    }
    dates = [dt.date() for dt in pd.bdate_range("2026-01-05", periods=60)]
    base_beta = pd.Series([1.15, 0.95, 0.85, 1.05, 1.20, 0.75], index=symbols)
    base_size = pd.Series([25.0, 24.5, 23.2, 23.8, 24.8, 22.9], index=symbols)
    base_pb = pd.Series([7.0, 5.8, 3.0, 3.5, 1.4, 1.1], index=symbols)

    rng = np.random.default_rng(7)
    market = rng.normal(0.0002, 0.012, len(dates))
    value = rng.normal(0.0000, 0.006, len(dates))
    size_factor = rng.normal(0.0000, 0.004, len(dates))
    returns = pd.DataFrame(index=dates, columns=symbols, dtype=float)
    rows = []
    for i, ret_date in enumerate(dates):
        exposure_date = (pd.Timestamp(ret_date) - pd.Timedelta(days=1)).date()
        for j, sym in enumerate(symbols):
            returns.loc[ret_date, sym] = (
                base_beta[sym] * market[i]
                + (1.0 / base_pb[sym]) * value[i]
                + (base_size[sym] - base_size.mean()) * size_factor[i] * 0.1
                + rng.normal(0.0, 0.002)
            )
            for factor_name, factor_value in {
                "beta_1y": base_beta[sym],
                "log_market_cap": base_size[sym],
                "pb_ratio": base_pb[sym],
                "ep_ratio": 0.03 + j * 0.004,
                "momentum_6m": -0.04 + j * 0.02,
                "volatility_60d": 0.18 + j * 0.01,
                "liquidity_20d": 3_000_000 + j * 250_000,
                "ebitda_margin": 0.20 + j * 0.01,
                "debt_to_equity": 0.8 - j * 0.05,
                "dividend_yield": 0.005 + j * 0.002,
            }.items():
                rows.append(
                    {
                        "symbol": sym,
                        "as_of_date": exposure_date,
                        "factor_name": factor_name,
                        "factor_value": float(factor_value),
                        "gics_sector": sectors[sym],
                    }
                )

    covariance, meta = estimate_fundamental_factor_covariance(
        returns,
        pd.DataFrame(rows),
        sector_map=sectors,
        style_factors=["market_beta", "size", "value", "momentum"],
        include_sector_factors=True,
        exposure_lag_days=1,
        min_cross_section=4,
        min_factor_return_days=20,
        min_sector_members=2,
        factor_cov_shrinkage=0.10,
        return_metadata=True,
    )

    assert list(covariance.index) == symbols
    assert list(covariance.columns) == symbols
    assert np.allclose(covariance.to_numpy(), covariance.to_numpy().T)
    assert covariance_quality(covariance)["is_usable"] is True
    assert meta["factor_return_days"] >= 20
    assert "market_beta" in meta["fundamental_factor_names"]
    assert meta["fundamental_sector_factor_count"] == 3


def test_build_action_event_defaults_expected_cost_to_transaction_cost():
    action = PendingRiskAction(
        event_type="trim_position",
        action_scope="symbol",
        action_family="risk_overlay",
        urgency="high",
        reason_code="vol_spike",
        scheduled_for=date(2026, 4, 30),
        symbol="AAPL",
    )

    event = build_action_event(
        action,
        event_date=date(2026, 4, 30),
        transaction_cost=0.0025,
    )

    assert event["symbol"] == "AAPL"
    assert event["expected_cost"] == 0.0025
