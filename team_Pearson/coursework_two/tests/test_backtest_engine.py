"""Unit tests for CW2 backtest engine orchestration helpers."""

from datetime import date

import pandas as pd
import pytest
from team_Pearson.coursework_two.modules.backtest import data_loader as data_loader_mod
from team_Pearson.coursework_two.modules.backtest import engine as engine_mod
from team_Pearson.coursework_two.modules.backtest.engine import (
    BacktestEngine,
    _apply_drawdown_brake_to_targets,
    _build_backtest_quality_report,
    _evaluate_drawdown_brake,
)


def _engine(*, rebalance_frequency: str = "monthly"):
    return BacktestEngine(
        {
            "backtest": {
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "rebalance_frequency": rebalance_frequency,
                "execution_lag": 1,
                "transaction_cost_bps": 15,
                "long_only": True,
                "weighting": "equal",
                "top_n": 25,
                "benchmark_ticker": "SPY",
                "portfolio_name": "cw2_core_equity",
                "initial_nav": 1.0,
                "min_eligible_universe": 3,
                "max_forward_fill_days": 5,
            }
        },
        db_engine=object(),
    )


def test_resolve_period_target_weights_uses_signals_when_above_threshold():
    engine = _engine()
    signals = [
        {"symbol": "A", "target_weight": 0.4, "regime": "normal"},
        {"symbol": "B", "target_weight": 0.35, "regime": "normal"},
        {"symbol": "C", "target_weight": 0.25, "regime": "normal"},
    ]
    target, source, regime = engine._resolve_period_target_weights(signals, {"X": 1.0})
    assert source == "signal"
    assert regime == "normal"
    assert set(target) == {"A", "B", "C"}


def test_resolve_period_target_weights_carries_drifted_when_below_threshold():
    engine = _engine()
    signals = [
        {"symbol": "A", "target_weight": 0.6, "regime": "stress"},
        {"symbol": "B", "target_weight": 0.4, "regime": "stress"},
    ]
    drifted = {"X": 0.55, "Y": 0.45}
    target, source, regime = engine._resolve_period_target_weights(signals, drifted)
    assert source == "carry"
    assert regime is None
    assert target == drifted


def test_dynamic_backtest_window_defaults_to_trailing_five_years():
    engine = BacktestEngine(
        {
            "backtest": {
                "start_date": "auto",
                "end_date": "2026-04-14",
                "lookback_years": 5,
                "rebalance_frequency": "monthly",
                "execution_lag": 1,
                "transaction_cost_bps": 15,
                "long_only": True,
                "weighting": "equal",
                "top_n": 25,
                "benchmark_ticker": "SPY",
                "portfolio_name": "cw2_core_equity",
                "initial_nav": 1.0,
                "min_eligible_universe": 15,
            }
        },
        db_engine=object(),
    )
    assert engine.bt_cfg["start_date"].isoformat() == "2021-04-14"
    assert engine.bt_cfg["end_date"].isoformat() == "2026-04-14"
    assert engine.run_config_snapshot["backtest"]["lookback_years"] == 5


def test_normalize_execution_config_defaults_to_flat_all_in_cost():
    execution_cfg = BacktestEngine._normalize_execution_config(
        {},
        default_bps=15.0,
        default_ffill=5,
    )

    assert execution_cfg["cost_model"] == "flat_total_bps"
    assert execution_cfg["base_slippage_bps"] == 0.0
    assert execution_cfg["open_execution_penalty_bps"] == 0.0
    assert execution_cfg["gap_slippage_multiplier"] == 0.0
    assert execution_cfg["participation_slippage_bps"] == 0.0
    assert execution_cfg["bid_ask_spread_model"] == "none"
    assert execution_cfg["bid_ask_crossing_fraction"] == 0.0


def test_validate_signal_history_requires_aligned_monthly_snapshots(monkeypatch):
    engine = _engine()
    rebalance_dates = [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)]
    monkeypatch.setattr(
        engine_mod,
        "load_signal_snapshot_counts",
        lambda *args, **kwargs: {
            date(2025, 3, 28): 25,
        },
    )

    with pytest.raises(ValueError, match="Insufficient rebalance-aligned signal history"):
        engine._validate_signal_history(rebalance_dates)


def test_validate_signal_history_accepts_two_aligned_snapshots(monkeypatch):
    engine = _engine()
    rebalance_dates = [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)]
    monkeypatch.setattr(
        engine_mod,
        "load_signal_snapshot_counts",
        lambda *args, **kwargs: {
            date(2025, 2, 27): 25,
            date(2025, 3, 28): 25,
        },
    )

    engine._validate_signal_history(rebalance_dates)


def test_scheduled_rebalance_dates_support_quarterly_with_initial_entry():
    engine = _engine(rebalance_frequency="quarterly")
    rebalance_dates = [
        date(2025, 1, 31),
        date(2025, 2, 28),
        date(2025, 3, 31),
        date(2025, 4, 30),
        date(2025, 6, 30),
    ]

    scheduled = engine._scheduled_rebalance_dates(rebalance_dates)

    assert scheduled == [
        date(2025, 1, 31),
        date(2025, 3, 31),
        date(2025, 6, 30),
    ]


def test_validate_signal_history_for_quarterly_uses_scheduled_dates(monkeypatch):
    engine = _engine(rebalance_frequency="quarterly")
    rebalance_dates = [
        date(2025, 1, 31),
        date(2025, 2, 28),
        date(2025, 3, 31),
        date(2025, 4, 30),
        date(2025, 6, 30),
    ]
    monkeypatch.setattr(
        engine_mod,
        "load_signal_snapshot_counts",
        lambda *args, **kwargs: {
            date(2025, 1, 30): 25,
            date(2025, 3, 28): 25,
        },
    )

    engine._validate_signal_history(rebalance_dates)


def test_scheduled_rebalance_dates_support_semiannual_with_initial_entry():
    engine = _engine(rebalance_frequency="semiannual")
    rebalance_dates = [
        date(2025, 1, 31),
        date(2025, 2, 28),
        date(2025, 6, 30),
        date(2025, 9, 30),
        date(2025, 12, 31),
    ]

    scheduled = engine._scheduled_rebalance_dates(rebalance_dates)

    assert scheduled == [
        date(2025, 1, 31),
        date(2025, 6, 30),
        date(2025, 12, 31),
    ]


def test_validate_benchmark_history_rejects_missing_trading_days():
    engine = _engine()
    benchmark_prices = pd.Series(
        [100.0, 101.0],
        index=[date(2025, 1, 31), date(2025, 2, 28)],
    )

    with pytest.raises(ValueError, match="Benchmark price history is incomplete"):
        engine._validate_benchmark_history(
            benchmark_prices,
            trading_calendar=[
                date(2025, 1, 31),
                date(2025, 2, 28),
                date(2025, 3, 31),
            ],
            start_date=date(2025, 1, 31),
            end_date=date(2025, 3, 31),
        )


def test_get_rebalance_dates_trims_terminal_incomplete_period(monkeypatch):
    engine = _engine()
    calendar = [
        date(2025, 2, 28),
        date(2025, 3, 3),
        date(2025, 3, 31),
        date(2025, 4, 1),
    ]
    monkeypatch.setattr(engine_mod, "load_trading_calendar", lambda *args, **kwargs: calendar)
    monkeypatch.setattr(
        engine_mod,
        "get_month_end_trading_days",
        lambda trading_calendar: [
            date(2025, 2, 28),
            date(2025, 3, 31),
            date(2025, 4, 1),
        ],
    )

    rebalance_dates, out_calendar = engine._get_rebalance_dates()

    assert out_calendar == calendar
    assert rebalance_dates == [date(2025, 2, 28), date(2025, 3, 31)]


def test_load_trading_calendar_prefers_macro_history_over_benchmark_series():
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class _Conn:
        def execute(self, sql, params):  # noqa: ARG002
            sql_text = str(sql)
            if "symbol = '_MACRO'" in sql_text:
                return _Result(
                    [
                        {"trading_date": date(2025, 1, 2)},
                        {"trading_date": date(2025, 1, 3)},
                    ]
                )
            if "DISTINCT observation_date" in sql_text:
                return _Result([])
            if "FROM systematic_equity.benchmark_prices" in sql_text:
                return _Result([{"trading_date": date(2025, 1, 2)}])
            raise AssertionError(f"Unexpected SQL: {sql_text}")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    trading_calendar = data_loader_mod.load_trading_calendar(
        _Engine(),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        benchmark_ticker="SPY",
    )

    assert trading_calendar == [date(2025, 1, 2), date(2025, 1, 3)]


def test_load_trading_calendar_unions_primary_sources_before_benchmark():
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class _Conn:
        def execute(self, sql, params):  # noqa: ARG002
            sql_text = str(sql)
            if "symbol = '_MACRO'" in sql_text:
                return _Result(
                    [
                        {"trading_date": date(2025, 1, 2)},
                        {"trading_date": date(2025, 1, 3)},
                    ]
                )
            if "DISTINCT observation_date" in sql_text:
                return _Result(
                    [
                        {"trading_date": date(2025, 1, 3)},
                        {"trading_date": date(2025, 1, 6)},
                    ]
                )
            if "FROM systematic_equity.benchmark_prices" in sql_text:
                return _Result([{"trading_date": date(2025, 1, 2)}])
            raise AssertionError(f"Unexpected SQL: {sql_text}")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    trading_calendar = data_loader_mod.load_trading_calendar(
        _Engine(),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        benchmark_ticker="SPY",
    )

    assert trading_calendar == [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]


def test_load_regime_target_maps_backfills_as_of_date(monkeypatch):
    monkeypatch.setattr(
        data_loader_mod,
        "_load_cw2_config",
        lambda: {"portfolio_construction": {"weighting": "equal"}},
    )
    monkeypatch.setattr(
        data_loader_mod,
        "_load_feature_bundle_for_date",
        lambda engine, as_of_date: {
            "factor_scores": [
                {
                    "symbol": "AAA",
                    "quality_score": 1.0,
                    "value_score": 0.5,
                    "market_technical_score": 0.2,
                    "sentiment_score": 0.1,
                    "dividend_score": 0.0,
                }
            ],
            "risk_overlay": [{"symbol": "AAA", "pass_all": True}],
            "universe_screen": [
                {
                    "symbol": "AAA",
                    "pass_all": True,
                    "country": "US",
                    "gics_sector": "Tech",
                }
            ],
            "company_info": {"AAA": {"country": "US", "gics_sector": "Tech"}},
        },
    )
    monkeypatch.setattr(
        data_loader_mod,
        "_build_portfolio_covariance_context",
        lambda *args, **kwargs: ({}, {}),
    )
    monkeypatch.setattr(
        data_loader_mod,
        "_forced_regime_config",
        lambda config, portfolio_name, forced_regime: config,
    )
    monkeypatch.setattr(
        data_loader_mod,
        "compute_composite_alpha",
        lambda rows, vix_level, config, forced_regime=None: rows,
    )
    captured = {"normal": None, "stress": None}

    def _fake_build_portfolio_targets(scores, *args, **kwargs):
        if captured["normal"] is None:
            captured["normal"] = scores
        else:
            captured["stress"] = scores
        return [{"symbol": "AAA", "target_weight": 1.0}]

    monkeypatch.setattr(data_loader_mod, "build_portfolio_targets", _fake_build_portfolio_targets)

    data_loader_mod.load_regime_target_maps(
        engine=object(),
        as_of_date=date(2026, 4, 14),
        portfolio_name="cw2_core_equity",
        config={"portfolio_construction": {"weighting": "equal"}},
    )

    assert captured["normal"][0]["as_of_date"] == date(2026, 4, 14)
    assert captured["stress"][0]["as_of_date"] == date(2026, 4, 14)


def test_build_execution_ledger_records_include_forward_fill_flags():
    execution_result = type(
        "ExecutionResult",
        (),
        {
            "trade_records": [
                {
                    "symbol": "AAA",
                    "requested_trade_weight": 0.10,
                    "executed_trade_weight": 0.08,
                }
            ]
        },
    )()

    records = BacktestEngine._build_execution_ledger_records(
        rebalance_date=date(2026, 3, 31),
        execution_date=date(2026, 4, 1),
        execution_result=execution_result,
        period_return_metadata={"AAA": {"used_forward_fill": True, "forward_fill_days": 2}},
    )

    assert records[0]["had_forward_fill"] is True
    assert records[0]["forward_fill_days"] == 2


def test_build_backtest_quality_report_tracks_core_row_counts():
    report = _build_backtest_quality_report(
        run_name="bt_demo",
        performance_records=[
            {
                "period_end_date": date(2026, 3, 31),
                "portfolio_nav": 1.02,
                "benchmark_nav": 1.01,
                "liquidity_clipped": False,
                "forward_filled_symbol_count": 2,
                "forward_fill_day_count": 4,
            }
        ],
        holding_records=[{"symbol": "AAA"}],
        cash_ledger_records=[{"rebalance_date": date(2026, 2, 27)}],
        execution_ledger_records=[{"symbol": "AAA", "executed_trade_weight": 0.1}],
        intraday_events=[{"event_type": "stock_stop_loss"}],
        intraday_daily_state=[],
        metrics={"sharpe_ratio": 1.1, "max_drawdown": -0.08},
    )

    assert report["run_name"] == "bt_demo"
    assert report["period_count"] == 1
    assert report["metric_count"] == 2
    assert report["execution_ledger_row_count"] == 1
    assert report["forward_filled_periods"] == 1
    assert report["forward_filled_symbol_total"] == 2
    assert report["forward_fill_day_total"] == 4


def test_evaluate_drawdown_brake_activates_on_threshold():
    active, drawdown, fraction = _evaluate_drawdown_brake(
        nav_history=[1.0, 1.05, 0.88],
        currently_active=False,
        config={
            "enabled": True,
            "lookback_periods": 12,
            "threshold_pct": 0.15,
            "recovery_drawdown_pct": 0.08,
            "de_risk_fraction": 0.35,
        },
    )

    assert active is True
    assert drawdown > 0.15
    assert fraction == 0.35


def test_apply_drawdown_brake_to_targets_adds_cash_sleeve():
    adjusted = _apply_drawdown_brake_to_targets({"AAA": 0.6, "BBB": 0.4}, de_risk_fraction=0.25)

    assert adjusted["_CASH"] == pytest.approx(0.25)
    assert adjusted["AAA"] == pytest.approx(0.45)
    assert adjusted["BBB"] == pytest.approx(0.30)


def test_run_executes_monthly_performance_with_quarterly_signal_schedule(monkeypatch):
    """Run the engine through the non-intraday path without requiring a live DB."""

    captured = {
        "holdings": None,
        "performance": None,
        "cash": None,
        "execution": None,
        "metrics": None,
        "quality": None,
        "completed": False,
    }
    calendar = [
        date(2025, 1, 31),
        date(2025, 2, 3),
        date(2025, 2, 28),
        date(2025, 3, 3),
        date(2025, 3, 31),
        date(2025, 4, 1),
    ]
    rebalance_dates = [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)]
    benchmark_prices = pd.Series(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        index=calendar,
    )
    price_panel = pd.DataFrame(
        {
            "AAA": [10.0, 10.5, 11.0, 11.2],
            "BBB": [20.0, 19.5, 20.0, 20.4],
        },
        index=[date(2025, 2, 3), date(2025, 3, 3), date(2025, 3, 31), date(2025, 4, 1)],
    )
    open_panel = price_panel.copy()
    volume_panel = pd.DataFrame(
        {"AAA": [1_000_000, 1_100_000, 1_200_000, 1_300_000], "BBB": [900_000] * 4},
        index=price_panel.index,
    )

    def _signals_for_date(db, rebalance_date, portfolio_name):  # noqa: ARG001
        return [
            {
                "symbol": "AAA",
                "target_weight": 0.60,
                "composite_alpha": 1.2,
                "gics_sector": "Tech",
                "regime": "normal",
            },
            {
                "symbol": "BBB",
                "target_weight": 0.40,
                "composite_alpha": 0.8,
                "gics_sector": "Health Care",
                "regime": "normal",
            },
        ]

    monkeypatch.setattr(engine_mod, "ensure_backtest_schema", lambda db: None)
    monkeypatch.setattr(engine_mod, "ensure_ops_monitoring_schema", lambda db: None)
    monkeypatch.setattr(engine_mod, "create_backtest_run", lambda db, **kwargs: "run-minimal")
    monkeypatch.setattr(
        engine_mod.BacktestEngine, "_get_rebalance_dates", lambda self: (rebalance_dates, calendar)
    )
    monkeypatch.setattr(
        engine_mod.BacktestEngine, "_validate_signal_history", lambda self, dates: None
    )
    monkeypatch.setattr(
        engine_mod, "load_benchmark_prices", lambda *args, **kwargs: benchmark_prices
    )
    monkeypatch.setattr(engine_mod, "load_signals", _signals_for_date)
    monkeypatch.setattr(
        engine_mod, "load_adjusted_close_prices", lambda *args, **kwargs: price_panel
    )
    monkeypatch.setattr(engine_mod, "load_open_prices", lambda *args, **kwargs: open_panel)
    monkeypatch.setattr(engine_mod, "load_daily_volumes", lambda *args, **kwargs: volume_panel)
    monkeypatch.setattr(
        engine_mod,
        "load_risk_free_period_returns",
        lambda db, schedule: {row["period_end_date"]: 0.001 for row in schedule},
    )
    monkeypatch.setattr(engine_mod, "load_vix_level", lambda *args, **kwargs: 18.0)
    monkeypatch.setattr(
        engine_mod,
        "write_holdings",
        lambda db, run_id, rows: captured.__setitem__("holdings", rows),
    )
    monkeypatch.setattr(
        engine_mod,
        "write_performance",
        lambda db, run_id, rows: captured.__setitem__("performance", rows),
    )
    monkeypatch.setattr(
        engine_mod,
        "write_cash_ledger",
        lambda db, run_id, rows: captured.__setitem__("cash", rows),
    )
    monkeypatch.setattr(
        engine_mod,
        "write_execution_ledger",
        lambda db, run_id, rows: captured.__setitem__("execution", rows),
    )
    monkeypatch.setattr(
        engine_mod,
        "write_intraday_events",
        lambda db, run_id, rows, config_snapshot: None,
    )
    monkeypatch.setattr(
        engine_mod,
        "write_metrics",
        lambda db, run_id, rows: captured.__setitem__("metrics", rows),
    )
    monkeypatch.setattr(
        engine_mod,
        "record_quality_snapshot",
        lambda **kwargs: captured.__setitem__("quality", kwargs),
    )
    monkeypatch.setattr(
        engine_mod,
        "mark_backtest_completed",
        lambda db, run_id, config_snapshot: captured.__setitem__("completed", True),
    )
    monkeypatch.setattr(
        engine_mod,
        "mark_backtest_failed",
        lambda db, run_id, config_snapshot: pytest.fail("run should not fail"),
    )

    engine = BacktestEngine(
        {
            "backtest": {
                "start_date": "2025-01-31",
                "end_date": "2025-03-31",
                "rebalance_frequency": "quarterly",
                "execution_lag": 1,
                "transaction_cost_bps": 10,
                "long_only": True,
                "benchmark_ticker": "SPY",
                "portfolio_name": "cw2_core_equity",
                "initial_nav": 1.0,
                "min_eligible_universe": 2,
                "max_forward_fill_days": 2,
                "execution": {
                    "enable_liquidity_clipping": False,
                    "adv_lookback_days": 1,
                    "min_adv_history_days": 1,
                },
                "drawdown_brake": {
                    "enabled": True,
                    "lookback_periods": 3,
                    "threshold_pct": 0.50,
                },
            }
        },
        db_engine=object(),
    )

    run_id = engine.run("quarterly_targets_monthly_measurement")

    assert run_id == "run-minimal"
    assert captured["completed"] is True
    assert len(captured["performance"]) == 2
    assert len(captured["cash"]) == 2
    assert {row["symbol"] for row in captured["holdings"]} == {"AAA", "BBB"}
    assert captured["performance"][0]["regime"] == "normal"
    assert captured["performance"][1]["turnover"] >= 0.0
    assert captured["metrics"]
    assert captured["quality"]["quality_report"]["cash_ledger_matches_period_count"] is True


def test_run_executes_intraday_overlay_and_daily_state(monkeypatch):
    captured = {
        "events": None,
        "daily_state": None,
        "performance": None,
    }
    calendar = [date(2025, 1, 31), date(2025, 2, 3), date(2025, 2, 28), date(2025, 3, 3)]
    rebalance_dates = [date(2025, 1, 31), date(2025, 2, 28)]
    benchmark_prices = pd.Series([100.0, 101.0, 102.0, 103.0], index=calendar)
    price_panel = pd.DataFrame(
        {"AAA": [10.0, 10.4], "BBB": [20.0, 20.2]},
        index=[date(2025, 2, 3), date(2025, 3, 3)],
    )
    event_factor_calls = []

    monkeypatch.setattr(engine_mod, "ensure_backtest_schema", lambda db: None)
    monkeypatch.setattr(engine_mod, "ensure_ops_monitoring_schema", lambda db: None)
    monkeypatch.setattr(engine_mod, "create_backtest_run", lambda db, **kwargs: "run-intraday")
    monkeypatch.setattr(
        engine_mod.BacktestEngine,
        "_get_rebalance_dates",
        lambda self: (rebalance_dates, calendar),
    )
    monkeypatch.setattr(
        engine_mod.BacktestEngine, "_validate_signal_history", lambda self, dates: None
    )
    monkeypatch.setattr(
        engine_mod, "load_benchmark_prices", lambda *args, **kwargs: benchmark_prices
    )
    monkeypatch.setattr(
        engine_mod,
        "load_signals",
        lambda *args, **kwargs: [
            {"symbol": "AAA", "target_weight": 0.5, "regime": "normal"},
            {"symbol": "BBB", "target_weight": 0.5, "regime": "normal"},
        ],
    )
    monkeypatch.setattr(
        engine_mod, "load_adjusted_close_prices", lambda *args, **kwargs: price_panel
    )
    monkeypatch.setattr(engine_mod, "load_open_prices", lambda *args, **kwargs: price_panel)
    monkeypatch.setattr(engine_mod, "load_high_prices", lambda *args, **kwargs: price_panel * 1.02)
    monkeypatch.setattr(engine_mod, "load_low_prices", lambda *args, **kwargs: price_panel * 0.98)
    monkeypatch.setattr(
        engine_mod, "load_daily_volumes", lambda *args, **kwargs: price_panel * 100_000
    )
    monkeypatch.setattr(
        engine_mod,
        "load_regime_target_maps",
        lambda *args, **kwargs: ({"AAA": 0.60, "BBB": 0.40}, {"AAA": 0.30, "BBB": 0.70}),
    )
    monkeypatch.setattr(
        engine_mod,
        "load_risk_free_period_returns",
        lambda db, schedule: {row["period_end_date"]: 0.0 for row in schedule},
    )
    monkeypatch.setattr(engine_mod, "load_vix_level", lambda *args, **kwargs: 28.0)
    monkeypatch.setattr(
        engine_mod,
        "load_vix_series",
        lambda *args, **kwargs: pd.Series([28.0, 35.0], index=price_panel.index),
    )
    monkeypatch.setattr(
        engine_mod,
        "load_term_spread_series",
        lambda *args, **kwargs: pd.Series([0.2, -0.1], index=price_panel.index),
    )

    def _load_factor_panel(*args, factor_name, **kwargs):
        event_factor_calls.append(factor_name)
        return price_panel * 0.0

    monkeypatch.setattr(engine_mod, "load_factor_panel", _load_factor_panel)

    intraday_result = type(
        "IntradayResult",
        (),
        {
            "period_gross_return": 0.025,
            "total_intraday_cost": 0.0002,
            "final_weights": {"AAA": 0.55, "BBB": 0.45},
            "final_target_variant": "stress",
            "intraday_stop_loss_count": 1,
            "intraday_regime_switch_count": 1,
            "events": [{"event_type": "vix_spike", "symbol": None}],
            "daily_state": [{"date": date(2025, 2, 4), "variant": "stress"}],
        },
    )()
    monkeypatch.setattr(engine_mod, "run_intraday_period", lambda **kwargs: intraday_result)
    monkeypatch.setattr(engine_mod, "write_holdings", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        engine_mod,
        "write_performance",
        lambda db, run_id, rows: captured.__setitem__("performance", rows),
    )
    monkeypatch.setattr(engine_mod, "write_cash_ledger", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_mod, "write_execution_ledger", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        engine_mod,
        "write_intraday_events",
        lambda db, run_id, rows, config_snapshot: captured.__setitem__("events", rows),
    )
    monkeypatch.setattr(
        engine_mod,
        "write_intraday_daily_state",
        lambda db, run_id, rows: captured.__setitem__("daily_state", rows),
    )
    monkeypatch.setattr(engine_mod, "write_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_mod, "record_quality_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(engine_mod, "mark_backtest_completed", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        engine_mod,
        "mark_backtest_failed",
        lambda *args, **kwargs: pytest.fail("intraday run should not fail"),
    )

    engine = BacktestEngine(
        {
            "backtest": {
                "start_date": "2025-01-31",
                "end_date": "2025-02-28",
                "rebalance_frequency": "monthly",
                "execution_lag": 1,
                "transaction_cost_bps": 10,
                "long_only": True,
                "benchmark_ticker": "SPY",
                "portfolio_name": "cw2_core_equity",
                "initial_nav": 1.0,
                "min_eligible_universe": 2,
                "max_forward_fill_days": 2,
                "intraday_triggers": {
                    "enabled": True,
                    "save_daily_state": True,
                    "event_driven_enabled": True,
                    "news_sentiment_shock_enabled": True,
                    "earnings_event_enabled": True,
                    "rating_downgrade_event_enabled": True,
                    "stop_loss_mode": "vol_scaled",
                    "stop_loss_vol_lookback_days": 3,
                },
                "execution": {
                    "enable_liquidity_clipping": False,
                    "adv_lookback_days": 1,
                    "min_adv_history_days": 1,
                },
            }
        },
        db_engine=object(),
    )

    assert engine.run("intraday_overlay") == "run-intraday"
    assert captured["performance"][0]["regime"] == "stress"
    assert captured["performance"][0]["intraday_stop_loss_count"] == 1
    assert captured["events"] == intraday_result.events
    assert captured["daily_state"] == intraday_result.daily_state
    assert {
        "sentiment_surprise",
        "earnings_publication_flag",
        "rating_downgrade_count_daily",
    } <= set(event_factor_calls)


def test_run_marks_backtest_failed_when_launch_validation_fails(monkeypatch):
    captured = {"failed": False, "quality": None}

    monkeypatch.setattr(engine_mod, "ensure_backtest_schema", lambda db: None)
    monkeypatch.setattr(engine_mod, "ensure_ops_monitoring_schema", lambda db: None)
    monkeypatch.setattr(engine_mod, "create_backtest_run", lambda db, **kwargs: "run-fail")
    monkeypatch.setattr(
        engine_mod.BacktestEngine,
        "_get_rebalance_dates",
        lambda self: (_ for _ in ()).throw(ValueError("calendar unavailable")),
    )
    monkeypatch.setattr(
        engine_mod,
        "record_quality_snapshot",
        lambda **kwargs: captured.__setitem__("quality", kwargs),
    )
    monkeypatch.setattr(
        engine_mod,
        "mark_backtest_failed",
        lambda db, run_id, config_snapshot: captured.__setitem__("failed", True),
    )

    engine = _engine()

    with pytest.raises(ValueError, match="calendar unavailable"):
        engine.run("bad-calendar")

    assert captured["failed"] is True
    assert captured["quality"]["quality_report"]["error_type"] == "ValueError"


def test_engine_date_and_config_helper_edges(monkeypatch):
    monkeypatch.setattr(engine_mod, "_today_utc", lambda: date(2026, 4, 20))

    assert engine_mod._resolve_end_date(None) == date(2026, 4, 20)
    assert engine_mod._resolve_end_date("latest") == date(2026, 4, 20)
    assert engine_mod._resolve_start_date(
        "rolling", end_date=date(2024, 2, 29), lookback_years=1
    ) == date(2023, 2, 28)
    assert engine_mod._coerce_date("2025-01-31") == date(2025, 1, 31)
    assert engine_mod._first_non_null([None, "normal", "stress"]) == "normal"
    assert engine_mod._first_non_null([None, None]) is None

    with pytest.raises(ValueError, match="start_date"):
        BacktestEngine(
            {"backtest": {"start_date": "2025-01-31", "end_date": "2025-01-31"}},
            db_engine=object(),
        )
    with pytest.raises(ValueError, match="execution_lag"):
        BacktestEngine(
            {
                "backtest": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-02-01",
                    "execution_lag": 0,
                }
            },
            db_engine=object(),
        )
    with pytest.raises(ValueError, match="long-only"):
        BacktestEngine(
            {
                "backtest": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-02-01",
                    "long_only": False,
                }
            },
            db_engine=object(),
        )

    intraday_cfg = BacktestEngine._normalize_intraday_triggers(
        {}, default_bps=12.0, default_ffill=4
    )
    assert intraday_cfg["transaction_cost_bps"] == 12.0
    assert intraday_cfg["max_forward_fill_days"] == 4
    assert intraday_cfg["stop_loss_mode"] == "fixed_pct"

    merged = engine_mod._deep_merge_dicts(
        {"backtest": {"execution": {"a": 1}, "top_n": 25}},
        {"backtest": {"execution": {"b": 2}}},
    )
    assert merged == {"backtest": {"execution": {"a": 1, "b": 2}, "top_n": 25}}


def test_engine_rebalance_and_validation_helper_edges(monkeypatch):
    engine = _engine(rebalance_frequency="annual")
    rebalance_dates = [
        date(2025, 1, 31),
        date(2025, 6, 30),
        date(2025, 12, 31),
        date(2026, 3, 31),
    ]
    assert engine._scheduled_rebalance_dates(rebalance_dates) == [
        date(2025, 1, 31),
        date(2025, 12, 31),
    ]

    unsupported = _engine()
    unsupported.bt_cfg["rebalance_frequency"] = "weekly"
    with pytest.raises(NotImplementedError, match="Unsupported rebalance frequency"):
        unsupported._scheduled_rebalance_dates(rebalance_dates)

    with pytest.raises(ValueError, match="No rebalance dates"):
        engine._validate_signal_history([])

    monkeypatch.setattr(engine_mod, "load_signal_snapshot_counts", lambda *args, **kwargs: {})
    with pytest.raises(ValueError, match="No portfolio_target_positions"):
        engine._validate_signal_history(rebalance_dates)

    monkeypatch.setattr(
        engine_mod,
        "load_signal_snapshot_counts",
        lambda *args, **kwargs: {date(2025, 1, 30): 1, date(2025, 12, 30): 1},
    )
    with pytest.raises(ValueError, match="Available snapshot dates/counts"):
        engine._validate_signal_history(rebalance_dates)


def test_engine_benchmark_and_record_building_helpers():
    engine = _engine()

    with pytest.raises(ValueError, match="validation window is empty"):
        engine._validate_benchmark_history(
            pd.Series([100.0], index=[date(2025, 1, 31)]),
            trading_calendar=[],
            start_date=date(2025, 1, 31),
            end_date=date(2025, 2, 28),
        )
    benchmark = pd.Series(
        [100.0, 102.0],
        index=[pd.Timestamp("2025-01-31"), pd.Timestamp("2025-02-28")],
    )
    engine._validate_benchmark_history(
        benchmark,
        trading_calendar=[date(2025, 1, 31), date(2025, 2, 28)],
        start_date=date(2025, 1, 31),
        end_date=date(2025, 2, 28),
    )
    assert engine._compute_benchmark_return(
        benchmark,
        [date(2025, 1, 31), date(2025, 2, 28)],
        date(2025, 1, 31),
        date(2025, 2, 28),
        max_forward_fill_days=1,
    ) == pytest.approx(0.02)

    holdings = engine._build_holdings_records(
        rebalance_date=date(2025, 1, 31),
        execution_date=date(2025, 2, 3),
        target_weights={"AAA": 0.50, "BBB": 0.50},
        executed_weights={"AAA": 0.45, "BBB": 0.55},
        drifted_weights={"AAA": 0.40, "BBB": 0.60},
        requested_turnover_contrib={"AAA": 0.10},
        turnover_contrib={"AAA": 0.05},
        signals=[{"symbol": "AAA", "composite_alpha": 1.2, "gics_sector": "Tech"}],
        regime="stress",
    )
    assert holdings[0]["execution_clipped"] is True
    assert holdings[0]["regime"] == "stress"
    assert engine._summarize_period_price_quality(
        {
            "AAA": {"used_forward_fill": True, "forward_fill_days": 0},
            "BBB": {"forward_fill_days": 2},
        }
    ) == {"forward_filled_symbol_count": 2, "forward_fill_day_count": 2}


def test_engine_drawdown_and_quality_report_edge_paths():
    assert _evaluate_drawdown_brake(
        nav_history=[1.0, 0.9],
        currently_active=False,
        config={"enabled": False},
    ) == (False, 0.0, 0.0)
    assert _evaluate_drawdown_brake(
        nav_history=[],
        currently_active=True,
        config={"enabled": True},
    ) == (False, 0.0, 0.0)
    active, drawdown, fraction = _evaluate_drawdown_brake(
        nav_history=[1.0, 0.93],
        currently_active=True,
        config={
            "enabled": True,
            "lookback_periods": 3,
            "threshold_pct": 0.15,
            "recovery_drawdown_pct": 0.08,
            "de_risk_fraction": 2.0,
        },
    )
    assert active is False
    assert drawdown == pytest.approx(0.07)
    assert fraction == 0.0
    assert _apply_drawdown_brake_to_targets({"AAA": 1.0}, de_risk_fraction=0.0) == {"AAA": 1.0}

    report = _build_backtest_quality_report(
        run_name="empty",
        performance_records=[],
        holding_records=[],
        cash_ledger_records=[{"rebalance_date": date(2025, 1, 31)}],
        execution_ledger_records=[],
        intraday_events=[],
        intraday_daily_state=[],
        metrics={},
    )
    assert report["passed"] is False
    assert "performance_rows_missing" in report["failures"]
    assert "metrics_missing" in report["failures"]
    assert "holding_rows_missing" in report["warnings"]
