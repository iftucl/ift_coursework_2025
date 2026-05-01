from __future__ import annotations

from datetime import date

from team_Pearson.coursework_two.modules.analysis import universe_benchmark as benchmark_mod


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, rows, sink):
        self._rows = rows
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, stmt, params):
        self._sink.append((stmt, dict(params)))
        return _FakeResult(self._rows)


class _FakeEngine:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def connect(self):
        return _FakeConnection(self._rows, self.calls)


def test_build_universe_ew_path_tracks_nav_and_weight_history(monkeypatch):
    run_context = {
        "run_id": "run-1",
        "run_row": {
            "start_date": date(2025, 4, 1),
            "end_date": date(2025, 5, 31),
            "benchmark_ticker": "SPY",
        },
        "periods": [
            {
                "rebalance_date": date(2025, 4, 30),
                "execution_date": date(2025, 5, 1),
                "period_end_date": date(2025, 5, 30),
            },
            {
                "rebalance_date": date(2025, 5, 30),
                "execution_date": date(2025, 6, 2),
                "period_end_date": date(2025, 6, 30),
            },
        ],
    }

    monkeypatch.setattr(
        benchmark_mod,
        "_load_trading_calendar",
        lambda run_context, db_engine: [date(2025, 5, 1), date(2025, 5, 30)],
    )
    monkeypatch.setattr(
        benchmark_mod,
        "_load_universe_symbols",
        lambda run_context, db_engine: {
            date(2025, 4, 30): ["AAA", "BBB"],
            date(2025, 5, 30): [],
        },
    )
    monkeypatch.setattr(
        benchmark_mod,
        "load_adjusted_close_prices",
        lambda *args, **kwargs: "price-panel",
    )
    monkeypatch.setattr(
        benchmark_mod,
        "compute_period_simple_returns",
        lambda *args, **kwargs: ({"AAA": 0.10, "BBB": 0.00}, None),
    )

    rows, weight_history = benchmark_mod.build_universe_ew_path(
        run_context,
        db_engine=object(),
        period_regimes={
            date(2025, 5, 30): {"regime": "normal"},
            date(2025, 6, 30): {"regime": "stress"},
        },
    )

    assert weight_history[date(2025, 4, 30)] == {"AAA": 0.5, "BBB": 0.5}
    assert weight_history[date(2025, 5, 30)] == {}
    assert rows[0]["series_name"] == "universe_ew"
    assert rows[0]["period_return"] == 0.05
    assert rows[0]["nav"] == 1.05
    assert rows[0]["num_holdings"] == 2
    assert rows[0]["regime"] == "normal"
    assert rows[1]["period_return"] == 0.0
    assert rows[1]["nav"] == 1.05
    assert rows[1]["num_holdings"] == 0
    assert rows[1]["regime"] == "stress"


def test_build_universe_ew_nav_returns_only_rows(monkeypatch):
    expected_rows = [{"period_end_date": date(2025, 5, 30), "nav": 1.02}]
    monkeypatch.setattr(
        benchmark_mod,
        "build_universe_ew_path",
        lambda *args, **kwargs: (expected_rows, {"ignored": {"AAA": 1.0}}),
    )

    rows = benchmark_mod.build_universe_ew_nav(
        {"run_id": "run-1", "periods": []},
        db_engine=object(),
        period_regimes={},
    )

    assert rows == expected_rows


def test_load_universe_symbols_groups_rows_by_rebalance_date():
    rebalance_dates = [date(2025, 4, 30), date(2025, 5, 30)]
    engine = _FakeEngine(
        [
            {"as_of_date": date(2025, 4, 30), "symbol": "AAA"},
            {"as_of_date": date(2025, 4, 30), "symbol": "BBB"},
            {"as_of_date": date(2025, 5, 30), "symbol": "CCC"},
        ]
    )

    symbols = benchmark_mod._load_universe_symbols(
        {"periods": [{"rebalance_date": dt} for dt in rebalance_dates]},
        engine,
    )

    assert list(symbols) == rebalance_dates
    assert symbols[date(2025, 4, 30)] == ["AAA", "BBB"]
    assert symbols[date(2025, 5, 30)] == ["CCC"]
    assert engine.calls[0][1] == {"dates": rebalance_dates}


def test_load_trading_calendar_uses_run_row_bounds(monkeypatch):
    captured = {}

    def fake_load_trading_calendar(db_engine, start_date, end_date, benchmark_ticker):
        captured["db_engine"] = db_engine
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["benchmark_ticker"] = benchmark_ticker
        return ["2025-04-30"]

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.backtest.data_loader.load_trading_calendar",
        fake_load_trading_calendar,
    )

    run_context = {
        "run_row": {
            "start_date": date(2025, 4, 1),
            "end_date": date(2025, 5, 30),
            "benchmark_ticker": "SPY",
        }
    }

    calendar = benchmark_mod._load_trading_calendar(run_context, db_engine="engine")

    assert calendar == ["2025-04-30"]
    assert captured == {
        "db_engine": "engine",
        "start_date": date(2025, 4, 1),
        "end_date": date(2025, 5, 30),
        "benchmark_ticker": "SPY",
    }
