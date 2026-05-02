"""Unit tests for explicit covariance-aware CW2 risk diagnostics."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from team_Pearson.coursework_two.modules.analysis import covariance_risk as covariance_module
from team_Pearson.coursework_two.modules.analysis.covariance_risk import (
    _estimate_covariance,
    _ex_ante_tracking_error,
    _portfolio_risk_stats,
    compute_covariance_diagnostics,
)


def test_covariance_shrinkage_reduces_off_diagonal():
    returns = pd.DataFrame(
        {
            "A": [0.01, 0.02, -0.01, 0.03],
            "B": [0.01, 0.01, -0.02, 0.02],
        }
    )
    sample = returns.cov()
    shrunk = _estimate_covariance(returns, shrinkage_intensity=0.50)

    assert float(abs(shrunk.loc["A", "B"])) < float(abs(sample.loc["A", "B"]))
    assert float(shrunk.loc["A", "A"]) == float(sample.loc["A", "A"])


def test_risk_contributions_sum_to_one():
    covariance = pd.DataFrame(
        [[0.04, 0.01], [0.01, 0.09]],
        index=["A", "B"],
        columns=["A", "B"],
    )
    stats = _portfolio_risk_stats({"A": 0.6, "B": 0.4}, covariance, {"A": "Tech", "B": "Finance"})
    total_pct = sum(row["risk_contribution_pct"] for row in stats["asset_contributions"])

    assert total_pct == pytest_approx(100.0)
    assert stats["effective_risk_bets"] is not None
    assert stats["diversification_ratio"] is not None


def test_ex_ante_tracking_error_zero_when_weights_match():
    covariance = pd.DataFrame(
        [[0.04, 0.01], [0.01, 0.09]],
        index=["A", "B"],
        columns=["A", "B"],
    )
    te = _ex_ante_tracking_error({"A": 0.5, "B": 0.5}, {"A": 0.5, "B": 0.5}, covariance)
    assert te == pytest_approx(0.0)


def test_compute_covariance_diagnostics_normalizes_weight_maps(monkeypatch):
    calendar = [dt.date() for dt in pd.bdate_range("2026-02-25", "2026-03-31")]
    price_panel = pd.DataFrame(
        {
            "A": np.linspace(100.0, 112.0, len(calendar)),
            "B": np.linspace(50.0, 55.0, len(calendar)) + np.sin(np.arange(len(calendar))) * 0.75,
        },
        index=calendar,
    )

    monkeypatch.setattr(
        covariance_module, "load_trading_calendar", lambda *args, **kwargs: calendar
    )
    monkeypatch.setattr(
        covariance_module,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: price_panel,
    )
    monkeypatch.setattr(
        covariance_module,
        "_load_sector_map",
        lambda *args, **kwargs: {"A": "Tech", "B": "Finance"},
    )

    run_context = {
        "run_id": "test-run",
        "run_row": {
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 31),
            "benchmark_ticker": "SPY",
        },
        "analysis_config": {
            "primary_benchmark": "SPY",
            "covariance": {
                "enabled": True,
                "include_series": ["strategy", "universe_ew"],
                "lookback_days": 25,
                "min_history_days": 20,
                "shrinkage_intensity": 0.25,
                "max_forward_fill_days": 2,
            },
        },
        "periods": [
            {
                "rebalance_date": date(2026, 3, 31),
                "period_end_date": date(2026, 4, 30),
            }
        ],
    }

    metrics, contributions = compute_covariance_diagnostics(
        run_context,
        db_engine=None,
        strategy_weights={date(2026, 3, 31): {"A": 2.0, "B": 1.0}},
        universe_weights={date(2026, 3, 31): {"A": 1.0, "B": 1.0}},
        static_weights={},
    )

    assert any(
        row["series_name"] == "strategy" and row["metric_name"] == "ex_ante_volatility_ann"
        for row in metrics
    )
    assert any(
        row["series_name"] == "strategy" and row["metric_name"] == "ex_ante_tracking_error_ann"
        for row in metrics
    )
    assert any(
        row["series_name"] == "strategy" and row["dimension_type"] == "asset"
        for row in contributions
    )


def test_compute_covariance_diagnostics_passes_factor_covariance_parameters(
    monkeypatch,
):
    calendar = [dt.date() for dt in pd.bdate_range("2026-02-25", "2026-03-31")]
    price_panel = pd.DataFrame(
        {
            "A": np.linspace(100.0, 112.0, len(calendar)),
            "B": np.linspace(50.0, 55.0, len(calendar)),
        },
        index=calendar,
    )
    captured = {}

    def fake_estimate(returns, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            [[0.04, 0.01], [0.01, 0.03]],
            index=["A", "B"],
            columns=["A", "B"],
        )

    monkeypatch.setattr(
        covariance_module, "load_trading_calendar", lambda *args, **kwargs: calendar
    )
    monkeypatch.setattr(
        covariance_module,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: price_panel,
    )
    monkeypatch.setattr(
        covariance_module,
        "_load_sector_map",
        lambda *args, **kwargs: {"A": "Tech", "B": "Finance"},
    )
    monkeypatch.setattr(covariance_module, "estimate_shrunk_covariance", fake_estimate)

    run_context = {
        "run_id": "test-run",
        "run_row": {
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 31),
            "benchmark_ticker": "SPY",
        },
        "analysis_config": {
            "primary_benchmark": "SPY",
            "covariance": {
                "enabled": True,
                "method": "statistical_factor",
                "factor_count": 2,
                "max_factor_count": 3,
                "factor_variance_target": 0.80,
                "specific_variance_floor_ratio": 0.07,
                "include_series": ["strategy", "universe_ew"],
                "lookback_days": 25,
                "min_history_days": 20,
                "shrinkage_intensity": 0.25,
                "max_forward_fill_days": 2,
            },
        },
        "periods": [
            {
                "rebalance_date": date(2026, 3, 31),
                "period_end_date": date(2026, 4, 30),
            }
        ],
    }

    metrics, _ = compute_covariance_diagnostics(
        run_context,
        db_engine=None,
        strategy_weights={date(2026, 3, 31): {"A": 0.5, "B": 0.5}},
        universe_weights={date(2026, 3, 31): {"A": 0.5, "B": 0.5}},
        static_weights={},
    )

    assert captured["method"] == "statistical_factor"
    assert captured["factor_count"] == 2
    assert captured["max_factor_count"] == 3
    assert captured["factor_variance_target"] == pytest_approx(0.80)
    assert captured["specific_variance_floor_ratio"] == pytest_approx(0.07)
    assert any(row["covariance_method"] == "statistical_factor" for row in metrics)


def test_compute_covariance_diagnostics_uses_fundamental_factor(monkeypatch):
    calendar = [dt.date() for dt in pd.bdate_range("2026-02-25", "2026-03-31")]
    price_panel = pd.DataFrame(
        {
            "A": np.linspace(100.0, 112.0, len(calendar)),
            "B": np.linspace(50.0, 55.0, len(calendar)),
        },
        index=calendar,
    )
    captured = {}

    def fake_fundamental(returns, exposures, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        return pd.DataFrame(
            [[0.04, 0.01], [0.01, 0.03]],
            index=["A", "B"],
            columns=["A", "B"],
        )

    monkeypatch.setattr(
        covariance_module, "load_trading_calendar", lambda *args, **kwargs: calendar
    )
    monkeypatch.setattr(
        covariance_module,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: price_panel,
    )
    monkeypatch.setattr(
        covariance_module,
        "_load_sector_map",
        lambda *args, **kwargs: {"A": "Tech", "B": "Tech"},
    )
    monkeypatch.setattr(
        covariance_module,
        "load_fundamental_exposure_observations",
        lambda *args, **kwargs: pd.DataFrame({"symbol": ["A"]}),
    )
    monkeypatch.setattr(
        covariance_module,
        "estimate_fundamental_factor_covariance",
        fake_fundamental,
    )

    run_context = {
        "run_id": "test-run",
        "run_row": {
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 31),
            "benchmark_ticker": "SPY",
        },
        "analysis_config": {
            "primary_benchmark": "SPY",
            "covariance": {
                "enabled": True,
                "method": "fundamental_factor",
                "style_factors": ["market_beta", "size"],
                "include_sector_factors": True,
                "exposure_lag_days": 1,
                "max_exposure_staleness_days": 365,
                "min_factor_return_days": 20,
                "min_cross_section": 3,
                "min_sector_members": 1,
                "factor_ridge": 1.0e-4,
                "factor_cov_shrinkage": 0.15,
                "include_series": ["strategy", "universe_ew"],
                "lookback_days": 25,
                "min_history_days": 20,
                "shrinkage_intensity": 0.25,
                "max_forward_fill_days": 2,
            },
        },
        "periods": [
            {
                "rebalance_date": date(2026, 3, 31),
                "period_end_date": date(2026, 4, 30),
            }
        ],
    }

    metrics, _ = compute_covariance_diagnostics(
        run_context,
        db_engine=None,
        strategy_weights={date(2026, 3, 31): {"A": 0.5, "B": 0.5}},
        universe_weights={date(2026, 3, 31): {"A": 0.5, "B": 0.5}},
        static_weights={},
    )

    assert captured["style_factors"] == ["market_beta", "size"]
    assert captured["sector_map"] == {"A": "Tech", "B": "Tech"}
    assert captured["factor_cov_shrinkage"] == pytest_approx(0.15)
    assert any(row["covariance_method"] == "fundamental_factor" for row in metrics)


def test_compute_covariance_diagnostics_falls_back_to_diagonal(monkeypatch):
    calendar = [dt.date() for dt in pd.bdate_range("2026-02-25", "2026-03-31")]
    price_panel = pd.DataFrame(
        {
            "A": np.linspace(100.0, 112.0, len(calendar)),
            "B": np.linspace(50.0, 55.0, len(calendar)),
        },
        index=calendar,
    )
    calls = []

    def fake_estimate(returns, **kwargs):  # noqa: ARG001
        calls.append(kwargs["method"])
        if kwargs["method"] == "statistical_factor":
            return pd.DataFrame()
        return pd.DataFrame(
            [[0.04, 0.01], [0.01, 0.03]],
            index=["A", "B"],
            columns=["A", "B"],
        )

    monkeypatch.setattr(
        covariance_module, "load_trading_calendar", lambda *args, **kwargs: calendar
    )
    monkeypatch.setattr(
        covariance_module,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: price_panel,
    )
    monkeypatch.setattr(
        covariance_module,
        "_load_sector_map",
        lambda *args, **kwargs: {"A": "Tech", "B": "Finance"},
    )
    monkeypatch.setattr(covariance_module, "estimate_shrunk_covariance", fake_estimate)

    run_context = {
        "run_id": "test-run",
        "run_row": {
            "start_date": date(2026, 3, 1),
            "end_date": date(2026, 3, 31),
            "benchmark_ticker": "SPY",
        },
        "analysis_config": {
            "primary_benchmark": "SPY",
            "covariance": {
                "enabled": True,
                "method": "statistical_factor",
                "factor_count": 2,
                "fallback_to_diagonal_shrinkage": True,
                "include_series": ["strategy", "universe_ew"],
                "lookback_days": 25,
                "min_history_days": 20,
                "shrinkage_intensity": 0.25,
                "max_forward_fill_days": 2,
            },
        },
        "periods": [
            {
                "rebalance_date": date(2026, 3, 31),
                "period_end_date": date(2026, 4, 30),
            }
        ],
    }

    metrics, _ = compute_covariance_diagnostics(
        run_context,
        db_engine=None,
        strategy_weights={date(2026, 3, 31): {"A": 0.5, "B": 0.5}},
        universe_weights={date(2026, 3, 31): {"A": 0.5, "B": 0.5}},
        static_weights={},
    )

    assert calls == ["statistical_factor", "diagonal_shrinkage"]
    assert any(row["covariance_method"] == "diagonal_shrinkage_0.25" for row in metrics)


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value, rel=1e-6, abs=1e-8)
