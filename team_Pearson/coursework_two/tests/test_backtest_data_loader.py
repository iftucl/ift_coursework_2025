"""Unit tests for CW2 backtest data-loader price helpers."""

from datetime import date

import pandas as pd
import pytest
from team_Pearson.coursework_two.modules.backtest import data_loader as data_loader_mod


class _Result:
    def __init__(self, rows, columns):
        self._rows = rows
        self._columns = columns

    def fetchall(self):
        return list(self._rows)

    def keys(self):
        return list(self._columns)


class _Conn:
    def __init__(self, rows_by_factor):
        self._rows_by_factor = rows_by_factor
        self.calls = []

    def execute(self, sql, params=None):  # noqa: ARG002
        params = params or {}
        self.calls.append((str(sql), dict(params)))
        factor_name = params.get("factor_name")
        if factor_name is None:
            raise AssertionError(f"Unexpected params without factor_name: {params}")
        return _Result(
            self._rows_by_factor.get(factor_name, []),
            ["symbol", "observation_date", "factor_value"],
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Engine:
    def __init__(self, rows_by_factor):
        self._rows_by_factor = rows_by_factor
        self.conn = _Conn(rows_by_factor)

    def connect(self):
        return self.conn


def test_load_open_prices_uses_raw_panel_when_close_price_missing():
    engine = _Engine(
        {
            "open_price": [
                ("AAA", date(2026, 1, 5), 100.0),
                ("AAA", date(2026, 1, 6), 101.0),
            ],
            "adjusted_close_price": [
                ("AAA", date(2026, 1, 5), 100.5),
                ("AAA", date(2026, 1, 6), 102.0),
            ],
        }
    )

    panel = data_loader_mod.load_open_prices(
        engine,
        ["AAA"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        lookback_days=0,
    )

    expected = pd.DataFrame(
        {"AAA": [100.0, 101.0]},
        index=[date(2026, 1, 5), date(2026, 1, 6)],
    )
    expected.index.name = "observation_date"
    expected.columns.name = "symbol"
    pd.testing.assert_frame_equal(panel, expected)


def test_load_open_prices_rescales_when_raw_close_history_exists():
    engine = _Engine(
        {
            "open_price": [
                ("AAA", date(2026, 1, 5), 50.0),
                ("AAA", date(2026, 1, 6), 55.0),
            ],
            "close_price": [
                ("AAA", date(2026, 1, 5), 100.0),
                ("AAA", date(2026, 1, 6), 110.0),
            ],
            "adjusted_close_price": [
                ("AAA", date(2026, 1, 5), 200.0),
                ("AAA", date(2026, 1, 6), 220.0),
            ],
        }
    )

    panel = data_loader_mod.load_open_prices(
        engine,
        ["AAA"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        lookback_days=0,
    )

    expected = pd.DataFrame(
        {"AAA": [100.0, 110.0]},
        index=[date(2026, 1, 5), date(2026, 1, 6)],
    )
    expected.index.name = "observation_date"
    expected.columns.name = "symbol"
    pd.testing.assert_frame_equal(panel, expected)


def test_load_adjusted_close_prices_applies_publish_date_cutoff():
    engine = _Engine(
        {
            "adjusted_close_price": [
                ("AAA", date(2026, 1, 5), 100.5),
                ("AAA", date(2026, 1, 6), 102.0),
            ]
        }
    )

    panel = data_loader_mod.load_adjusted_close_prices(
        engine,
        ["AAA"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        lookback_days=0,
    )

    assert not panel.empty
    assert "COALESCE(publish_date, observation_date) <= :end_date" in engine.conn.calls[0][0]


def test_publish_cutoff_predicate_raises_when_required_parts_missing():
    with pytest.raises(ValueError, match="publish cutoff predicate requires"):
        data_loader_mod._pit_publish_cutoff_predicate("")

    with pytest.raises(ValueError, match="publish cutoff predicate requires"):
        data_loader_mod._pit_publish_cutoff_predicate("end_date", observation_column="")


def test_build_portfolio_covariance_context_falls_back_to_diagonal(monkeypatch):
    calendar = [date(2026, 1, day) for day in range(5, 9)]
    returns = pd.DataFrame(
        {
            "AAA": [0.01, -0.02, 0.03],
            "BBB": [0.02, -0.01, 0.01],
        }
    )
    calls = []

    def fake_estimate(returns_arg, **kwargs):  # noqa: ARG001
        calls.append(kwargs["method"])
        if kwargs["method"] == "statistical_factor":
            return pd.DataFrame()
        return pd.DataFrame(
            [[0.04, 0.0], [0.0, 0.03]],
            index=["AAA", "BBB"],
            columns=["AAA", "BBB"],
        )

    monkeypatch.setattr(
        data_loader_mod,
        "load_trading_calendar",
        lambda *args, **kwargs: calendar,
    )
    monkeypatch.setattr(
        data_loader_mod,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        data_loader_mod,
        "build_return_panel",
        lambda *args, **kwargs: returns,
    )
    monkeypatch.setattr(data_loader_mod, "estimate_shrunk_covariance", fake_estimate)

    covariance, meta = data_loader_mod._build_portfolio_covariance_context(
        object(),
        date(2026, 1, 8),
        ["AAA", "BBB"],
        {
            "portfolio_construction": {
                "weighting": "mean_variance",
                "covariance": {
                    "method": "statistical_factor",
                    "lookback_days": 60,
                    "min_history_days": 40,
                    "shrinkage_intensity": 0.25,
                    "factor_count": 1,
                    "fallback_to_diagonal_shrinkage": True,
                    "max_forward_fill_days": 0,
                },
            },
            "backtest": {"benchmark_ticker": "SPY"},
        },
    )

    assert calls == ["statistical_factor", "diagonal_shrinkage"]
    assert not covariance.empty
    assert meta["requested_covariance_method"] == "statistical_factor"
    assert meta["covariance_method"] == "diagonal_shrinkage_0.25"
    assert meta["covariance_fallback_used"] is True
    assert meta["covariance_fallback_reason"] == "empty"


def test_build_portfolio_covariance_context_uses_fundamental_factor(monkeypatch):
    calendar = [date(2026, 1, day) for day in range(5, 12)]
    returns = pd.DataFrame(
        {
            "AAA": [0.01, -0.02, 0.03, 0.01, -0.01],
            "BBB": [0.02, -0.01, 0.01, 0.00, 0.02],
        }
    )
    captured = {}

    def fake_fundamental(returns_arg, exposures_arg, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        return (
            pd.DataFrame(
                [[0.04, 0.01], [0.01, 0.03]],
                index=["AAA", "BBB"],
                columns=["AAA", "BBB"],
            ),
            {
                "factor_return_days": 44,
                "fundamental_factor_names": ["market_beta", "sector:Technology"],
                "fundamental_sector_factor_count": 1,
                "fundamental_style_factor_count": 1,
            },
        )

    monkeypatch.setattr(
        data_loader_mod,
        "load_trading_calendar",
        lambda *args, **kwargs: calendar,
    )
    monkeypatch.setattr(
        data_loader_mod,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        data_loader_mod,
        "build_return_panel",
        lambda *args, **kwargs: returns,
    )
    monkeypatch.setattr(
        data_loader_mod,
        "load_fundamental_exposure_observations",
        lambda *args, **kwargs: pd.DataFrame({"symbol": ["AAA"]}),
    )
    monkeypatch.setattr(
        data_loader_mod,
        "load_sector_map",
        lambda *args, **kwargs: {"AAA": "Technology", "BBB": "Technology"},
    )
    monkeypatch.setattr(
        data_loader_mod,
        "estimate_fundamental_factor_covariance",
        fake_fundamental,
    )

    covariance, meta = data_loader_mod._build_portfolio_covariance_context(
        object(),
        date(2026, 1, 11),
        ["AAA", "BBB"],
        {
            "portfolio_construction": {
                "weighting": "mean_variance",
                "covariance": {
                    "method": "fundamental_factor",
                    "lookback_days": 60,
                    "min_history_days": 40,
                    "shrinkage_intensity": 0.25,
                    "style_factors": ["market_beta"],
                    "include_sector_factors": True,
                    "min_factor_return_days": 20,
                    "fallback_to_statistical_factor": True,
                    "fallback_to_diagonal_shrinkage": True,
                    "max_forward_fill_days": 0,
                },
            },
            "backtest": {"benchmark_ticker": "SPY"},
        },
    )

    assert not covariance.empty
    assert captured["style_factors"] == ["market_beta"]
    assert captured["return_metadata"] is True
    assert meta["requested_covariance_method"] == "fundamental_factor"
    assert meta["covariance_method"] == "fundamental_factor"
    assert meta["factor_return_days"] == 44
    assert meta["fundamental_sector_factor_count"] == 1
    assert meta["covariance_fallback_used"] is False


def test_load_macro_series_applies_publish_date_cutoff():
    engine = _Engine(
        {
            "vix_close": [
                ("_MACRO", date(2026, 1, 5), 20.0),
                ("_MACRO", date(2026, 1, 6), 21.0),
            ]
        }
    )

    series = data_loader_mod.load_macro_series(
        engine,
        "vix_close",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
    )

    assert list(series.index) == [date(2026, 1, 5), date(2026, 1, 6)]
    assert "COALESCE(publish_date, observation_date) <= :end_date" in engine.conn.calls[0][0]


def test_load_risk_free_period_returns_compounds_forward_filled_calendar_days():
    engine = _Engine(
        {
            "us_treasury_3m": [
                ("_MACRO", date(2026, 1, 1), 3.65),
                ("_MACRO", date(2026, 1, 3), 7.30),
            ]
        }
    )

    returns = data_loader_mod.load_risk_free_period_returns(
        engine,
        [
            {
                "execution_date": date(2026, 1, 1),
                "period_end_date": date(2026, 1, 3),
            }
        ],
    )

    expected_day_1 = (1.0 + 0.0365) ** (1.0 / 365.25) - 1.0
    expected_day_2 = (1.0 + 0.0730) ** (1.0 / 365.25) - 1.0
    expected = (1.0 + expected_day_1) * (1.0 + expected_day_2) - 1.0
    assert returns[date(2026, 1, 3)] == pytest.approx(expected, rel=1e-8, abs=1e-10)
