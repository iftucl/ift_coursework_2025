"""Unit tests for CW2 regime attribution analysis."""

from __future__ import annotations

from datetime import date

import pandas as pd
from team_Pearson.coursework_two.modules.analysis.regime_attribution import (
    classify_period_regimes,
    compute_regime_attribution,
)
from team_Pearson.coursework_two.modules.backtest.metrics import compute_backtest_metrics


def test_regime_split_by_vix_threshold():
    engine = _FakeEngine(
        [
            {"observation_date": date(2026, 1, 2), "factor_value": 21.0},
            {"observation_date": date(2026, 1, 15), "factor_value": 23.0},
            {"observation_date": date(2026, 2, 3), "factor_value": 27.0},
            {"observation_date": date(2026, 2, 17), "factor_value": 29.0},
        ]
    )
    periods = [
        {
            "execution_date": date(2026, 1, 2),
            "period_end_date": date(2026, 1, 31),
        },
        {
            "execution_date": date(2026, 2, 3),
            "period_end_date": date(2026, 2, 28),
        },
    ]

    regimes = classify_period_regimes(engine, periods, stress_vix_threshold=25.0)

    assert regimes[date(2026, 1, 31)]["regime"] == "normal"
    assert regimes[date(2026, 2, 28)]["regime"] == "stress"


def test_all_regime_matches_full_period_metrics(monkeypatch):
    idx = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"])
    strategy_returns = pd.Series([0.02, -0.01, 0.03], index=idx)
    benchmark_returns = pd.Series([0.01, 0.00, 0.02], index=idx)
    risk_free_returns = pd.Series([0.005, 0.005, 0.005], index=idx)

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.regime_attribution._load_strategy_series",
        lambda run_id, engine: pd.DataFrame(
            {
                "strategy_return": strategy_returns,
                "risk_free_return": risk_free_returns,
                "strategy_nav": (1.0 + strategy_returns).cumprod(),
            }
        ),
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.regime_attribution._load_benchmark_series",
        lambda run_id, engine, allowed_series: {
            "universe_ew": pd.DataFrame(
                {
                    "period_return": benchmark_returns,
                    "risk_free_return": risk_free_returns,
                    "nav": (1.0 + benchmark_returns).cumprod(),
                }
            )
        },
    )

    rows = compute_regime_attribution(
        {"run_id": "run-1"},
        db_engine=None,
        period_regimes={
            date(2026, 1, 31): {"regime": "normal"},
            date(2026, 2, 28): {"regime": "stress"},
            date(2026, 3, 31): {"regime": "normal"},
        },
    )
    all_row = next(
        row for row in rows if row["versus_series"] == "universe_ew" and row["regime"] == "all"
    )

    perf_rows = []
    nav = 1.0
    bench_nav = 1.0
    for idx_ts, strat_ret, bench_ret in zip(idx, strategy_returns, benchmark_returns):
        nav *= 1.0 + float(strat_ret)
        bench_nav *= 1.0 + float(bench_ret)
        perf_rows.append(
            {
                "period_end_date": idx_ts.date(),
                "gross_return": float(strat_ret),
                "net_return": float(strat_ret),
                "benchmark_return": float(bench_ret),
                "risk_free_return": float(risk_free_returns.loc[idx_ts]),
                "excess_return": float(strat_ret - bench_ret),
                "portfolio_nav": nav,
                "benchmark_nav": bench_nav,
                "turnover": 0.0,
                "transaction_cost": 0.0,
                "num_holdings": 25,
            }
        )
    metrics = compute_backtest_metrics(perf_rows, initial_nav=1.0)
    metrics_lookup = {
        (m["metric_group"], m["metric_name"]): float(m["metric_value"]) for m in metrics
    }

    assert all_row["strategy_ann_return"] == pytest_approx(
        metrics_lookup[("return", "annualized_return")]
    )
    assert all_row["strategy_ann_vol"] == pytest_approx(
        metrics_lookup[("risk", "annualized_volatility")]
    )
    assert all_row["strategy_sharpe"] == pytest_approx(
        metrics_lookup[("risk_adjusted", "sharpe_ratio")]
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params):
        return _FakeResult(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, rows):
        self._rows = rows

    def connect(self):
        return _FakeConnection(self._rows)


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value, rel=1e-6, abs=1e-8)
