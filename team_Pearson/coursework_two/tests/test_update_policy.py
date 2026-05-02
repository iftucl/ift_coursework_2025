"""Unit tests for the CW2 daily update-decision layer."""

from __future__ import annotations

import json
from datetime import date

from team_Pearson.coursework_two.modules.ops import update_policy as update_mod


def test_classify_update_decision_returns_full_rebalance_on_month_end():
    decision_scope, recommended_mode, reason_code = update_mod.classify_update_decision(
        run_date=date(2026, 4, 30),
        is_month_end_rebalance_day=True,
        latest_snapshot_as_of=date(2026, 3, 31),
        trigger_symbol_count=3,
    )

    assert decision_scope == "full_rebalance"
    assert recommended_mode == "operate"
    assert reason_code == "scheduled_month_end_rebalance"


def test_classify_update_decision_returns_blocked_without_snapshot():
    decision_scope, recommended_mode, reason_code = update_mod.classify_update_decision(
        run_date=date(2026, 4, 15),
        is_month_end_rebalance_day=False,
        latest_snapshot_as_of=None,
        trigger_symbol_count=0,
    )

    assert decision_scope == "blocked"
    assert recommended_mode == "none"
    assert reason_code == "missing_existing_portfolio_snapshot"


def test_classify_update_decision_returns_risk_review_when_triggers_exist():
    decision_scope, recommended_mode, reason_code = update_mod.classify_update_decision(
        run_date=date(2026, 4, 15),
        is_month_end_rebalance_day=False,
        latest_snapshot_as_of=date(2026, 3, 31),
        trigger_symbol_count=2,
    )

    assert decision_scope == "risk_review"
    assert recommended_mode == "risk_overlay_review"
    assert reason_code == "adverse_event_proxy_triggered"


def test_classify_update_decision_adds_review_gate_on_scheduled_rebalance():
    decision_scope, recommended_mode, reason_code = update_mod.classify_update_decision(
        run_date=date(2026, 6, 30),
        is_month_end_rebalance_day=True,
        latest_snapshot_as_of=date(2026, 5, 31),
        trigger_symbol_count=0,
        monitoring_review_required=True,
    )

    assert decision_scope == "full_rebalance"
    assert recommended_mode == "operate"
    assert reason_code == "scheduled_month_end_rebalance_with_review_gate"


def test_classify_update_decision_can_auto_override_scheduled_review_gate():
    decision_scope, recommended_mode, reason_code = update_mod.classify_update_decision(
        run_date=date(2026, 6, 30),
        is_month_end_rebalance_day=True,
        latest_snapshot_as_of=date(2026, 5, 31),
        trigger_symbol_count=0,
        monitoring_review_required=True,
        scheduled_rebalance_review_mode="automatic",
    )

    assert decision_scope == "full_rebalance"
    assert recommended_mode == "operate"
    assert reason_code == "scheduled_month_end_rebalance_auto_monitoring_override"


def test_classify_update_decision_returns_risk_review_when_monitoring_requires_review():
    decision_scope, recommended_mode, reason_code = update_mod.classify_update_decision(
        run_date=date(2026, 4, 15),
        is_month_end_rebalance_day=False,
        latest_snapshot_as_of=date(2026, 3, 31),
        trigger_symbol_count=0,
        monitoring_review_required=True,
        approval_required=True,
    )

    assert decision_scope == "risk_review"
    assert recommended_mode == "prepare_recommendation_for_approval"
    assert reason_code == "monitoring_review_threshold_breached"


def test_run_update_decision_from_config_materializes_payload(monkeypatch):
    captured = {}
    quality = {}

    monkeypatch.setattr(
        update_mod,
        "_load_config",
        lambda _: {"portfolio_construction": {"portfolio_name": "cw2_core_equity"}},
    )
    monkeypatch.setattr(update_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(update_mod, "ensure_update_decision_schema", lambda engine: None)
    monkeypatch.setattr(
        update_mod,
        "_is_month_end_rebalance_day",
        lambda engine, run_date, config: False,
    )
    monkeypatch.setattr(
        update_mod,
        "_latest_portfolio_snapshot",
        lambda engine, *, run_date, portfolio_name: (date(2026, 3, 31), 25),
    )
    monkeypatch.setattr(
        update_mod,
        "_latest_recommendation_as_of_date",
        lambda engine, *, run_date, portfolio_name: date(2026, 3, 31),
    )
    monkeypatch.setattr(
        update_mod,
        "_load_snapshot_symbols",
        lambda engine, *, as_of_date, portfolio_name: ["AAPL", "MSFT"],
    )
    monkeypatch.setattr(
        update_mod,
        "_resolve_signal_as_of_date",
        lambda engine, *, run_date, symbols: date(2026, 4, 14),
    )
    monkeypatch.setattr(
        update_mod,
        "_event_trigger_summary",
        lambda engine, *, run_date, signal_as_of_date, config, symbols: {
            "run_date": run_date.isoformat(),
            "signal_as_of_date": signal_as_of_date.isoformat(),
            "portfolio_symbol_count": 2,
            "news_trigger_count": 1,
            "earnings_trigger_count": 0,
            "rating_trigger_count": 0,
            "trigger_symbol_count": 1,
            "trigger_symbols": ["AAPL"],
        },
    )
    monkeypatch.setattr(
        update_mod,
        "_monitoring_review_summary",
        lambda engine, *, run_date, config, portfolio_name, latest_snapshot_as_of: {
            "enabled": True,
            "status": "evaluated",
            "review_required": False,
            "reason_count": 0,
            "review_reasons": [],
        },
    )
    monkeypatch.setattr(
        update_mod,
        "_upsert_update_decision",
        lambda engine, payload: captured.update(payload),
    )
    monkeypatch.setattr(
        update_mod, "record_quality_snapshot", lambda **kwargs: quality.update(kwargs)
    )

    report = update_mod.run_update_decision_from_config(
        run_date="2026-04-15", config_path="cw2.yaml"
    )

    assert report["decision_scope"] == "risk_review"
    assert report["recommended_mode"] == "risk_overlay_review"
    assert report["trigger_summary"]["trigger_symbol_count"] == 1
    assert report["signal_as_of_date"] == "2026-04-14"
    assert captured["portfolio_name"] == "cw2_core_equity"
    assert captured["decision_scope"] == "risk_review"
    assert captured["signal_as_of_date"] == date(2026, 4, 14)
    assert json.loads(captured["trigger_summary_json"])["monitoring_review"]["enabled"] is True
    assert quality["dataset_name"] == "portfolio_update_decisions"
    assert quality["quality_report"]["passed"] is True
    assert quality["quality_report"]["trigger_symbol_count"] == 1


def test_run_update_decision_from_config_escalates_monitoring_review(monkeypatch):
    captured = {}
    quality = {}

    monkeypatch.setattr(
        update_mod,
        "_load_config",
        lambda _: {
            "portfolio_construction": {"portfolio_name": "cw2_core_equity"},
            "recommendation": {"approval_required": True},
        },
    )
    monkeypatch.setattr(update_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(update_mod, "ensure_update_decision_schema", lambda engine: None)
    monkeypatch.setattr(
        update_mod,
        "_is_month_end_rebalance_day",
        lambda engine, run_date, config: False,
    )
    monkeypatch.setattr(
        update_mod,
        "_latest_portfolio_snapshot",
        lambda engine, *, run_date, portfolio_name: (date(2026, 3, 31), 25),
    )
    monkeypatch.setattr(
        update_mod,
        "_latest_recommendation_as_of_date",
        lambda engine, *, run_date, portfolio_name: date(2026, 3, 31),
    )
    monkeypatch.setattr(
        update_mod,
        "_load_snapshot_symbols",
        lambda engine, *, as_of_date, portfolio_name: ["AAPL", "MSFT"],
    )
    monkeypatch.setattr(
        update_mod,
        "_resolve_signal_as_of_date",
        lambda engine, *, run_date, symbols: date(2026, 4, 14),
    )
    monkeypatch.setattr(
        update_mod,
        "_event_trigger_summary",
        lambda engine, *, run_date, signal_as_of_date, config, symbols: {
            "run_date": run_date.isoformat(),
            "signal_as_of_date": signal_as_of_date.isoformat(),
            "portfolio_symbol_count": 2,
            "news_trigger_count": 0,
            "earnings_trigger_count": 0,
            "rating_trigger_count": 0,
            "trigger_symbol_count": 0,
            "trigger_symbols": [],
        },
    )
    monkeypatch.setattr(
        update_mod,
        "_monitoring_review_summary",
        lambda engine, *, run_date, config, portfolio_name, latest_snapshot_as_of: {
            "enabled": True,
            "status": "evaluated",
            "review_required": True,
            "reason_count": 2,
            "review_reasons": [
                "turnover:expected_turnover_above_threshold",
                "tracking_error:realized_tracking_error",
            ],
        },
    )
    monkeypatch.setattr(
        update_mod,
        "_upsert_update_decision",
        lambda engine, payload: captured.update(payload),
    )
    monkeypatch.setattr(
        update_mod, "record_quality_snapshot", lambda **kwargs: quality.update(kwargs)
    )

    report = update_mod.run_update_decision_from_config(
        run_date="2026-04-15", config_path="cw2.yaml"
    )

    assert report["decision_scope"] == "risk_review"
    assert report["recommended_mode"] == "prepare_recommendation_for_approval"
    assert report["requires_human_review"] is True
    assert captured["reason_code"] == "monitoring_review_threshold_breached"
    assert quality["quality_report"]["monitoring_review_required"] is True
    assert quality["quality_report"]["monitoring_review_reason_count"] == 2


def test_run_update_decision_from_config_keeps_scheduled_rebalance_automatic(
    monkeypatch,
):
    captured = {}

    monkeypatch.setattr(
        update_mod,
        "_load_config",
        lambda _: {
            "portfolio_construction": {"portfolio_name": "cw2_core_equity"},
            "recommendation": {
                "approval_required": True,
                "monitoring_review": {"scheduled_rebalance_review_mode": "automatic"},
            },
        },
    )
    monkeypatch.setattr(update_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(update_mod, "ensure_update_decision_schema", lambda engine: None)
    monkeypatch.setattr(
        update_mod,
        "_is_month_end_rebalance_day",
        lambda engine, run_date, config: True,
    )
    monkeypatch.setattr(
        update_mod,
        "_latest_portfolio_snapshot",
        lambda engine, *, run_date, portfolio_name: (date(2026, 6, 30), 25),
    )
    monkeypatch.setattr(
        update_mod,
        "_latest_recommendation_as_of_date",
        lambda engine, *, run_date, portfolio_name: date(2026, 6, 30),
    )
    monkeypatch.setattr(
        update_mod,
        "_load_snapshot_symbols",
        lambda engine, *, as_of_date, portfolio_name: ["AAPL", "MSFT"],
    )
    monkeypatch.setattr(
        update_mod,
        "_resolve_signal_as_of_date",
        lambda engine, *, run_date, symbols: date(2026, 6, 30),
    )
    monkeypatch.setattr(
        update_mod,
        "_event_trigger_summary",
        lambda engine, *, run_date, signal_as_of_date, config, symbols: {
            "run_date": run_date.isoformat(),
            "signal_as_of_date": signal_as_of_date.isoformat(),
            "portfolio_symbol_count": 2,
            "news_trigger_count": 0,
            "earnings_trigger_count": 0,
            "rating_trigger_count": 0,
            "trigger_symbol_count": 0,
            "trigger_symbols": [],
        },
    )
    monkeypatch.setattr(
        update_mod,
        "_monitoring_review_summary",
        lambda engine, *, run_date, config, portfolio_name, latest_snapshot_as_of: {
            "enabled": True,
            "status": "evaluated",
            "review_required": True,
            "reason_count": 1,
            "review_reasons": ["tracking_error:realized_tracking_error"],
        },
    )
    monkeypatch.setattr(
        update_mod,
        "_upsert_update_decision",
        lambda engine, payload: captured.update(payload),
    )
    monkeypatch.setattr(update_mod, "record_quality_snapshot", lambda **kwargs: None)

    report = update_mod.run_update_decision_from_config(
        run_date="2026-06-30", config_path="cw2.yaml"
    )

    assert report["decision_scope"] == "full_rebalance"
    assert report["recommended_mode"] == "operate"
    assert report["reason_code"] == "scheduled_month_end_rebalance_auto_monitoring_override"
    assert report["requires_human_review"] is False
    assert captured["requires_human_review"] is False


class _UpdateMappingsResult:
    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]

    def all(self):
        return [dict(row) for row in self._rows]

    def first(self):
        return dict(self._rows[0]) if self._rows else None


class _UpdateResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _UpdateMappingsResult(self._rows)

    def fetchall(self):
        return list(self._rows)


class _UpdateConn:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, sql, params=None):  # noqa: ARG002
        return _UpdateResult(self._rows)


class _UpdateEngine:
    def __init__(self, rows):
        self._rows = rows

    def connect(self):
        return _UpdateConn(self._rows)


def test_build_update_decision_quality_report_flags_blocked_state():
    report = update_mod._build_update_decision_quality_report(
        {
            "portfolio_name": "cw2_core_equity",
            "decision_scope": "blocked",
            "recommended_mode": "none",
            "reason_code": "missing_existing_portfolio_snapshot",
            "latest_snapshot_as_of_date": None,
            "latest_snapshot_position_count": None,
            "trigger_summary": {"trigger_symbol_count": 0},
            "requires_human_review": True,
            "is_month_end_rebalance_day": False,
        }
    )

    assert report["portfolio_name"] == "cw2_core_equity"
    assert report["passed"] is False
    assert report["latest_snapshot_available"] is False
    assert report["trigger_symbol_count"] == 0


def test_summarize_mandate_checks_flags_mandate_breaches():
    summary = update_mod._summarize_mandate_checks(
        [
            {"target_weight": 0.60, "gics_sector": "Info Tech"},
            {"target_weight": 0.35, "gics_sector": "Info Tech"},
        ],
        {
            "portfolio_construction": {
                "min_names": 3,
                "max_single_weight": 0.50,
                "max_sector_weight": 0.70,
            }
        },
        weight_sum_tolerance=0.01,
    )

    assert summary["breaches"] == [
        "min_names",
        "max_single_weight",
        "max_sector_weight",
        "weight_sum",
    ]
    assert summary["breach_count"] == 4


def test_summarize_tracking_error_checks_flags_budget_breaches():
    summary = update_mod._summarize_tracking_error_checks(
        {
            "available": True,
            "run_id": "abc",
            "run_name": "cw2_backtest",
            "run_end_date": "2026-03-31",
            "realized_tracking_error": 0.09,
            "ex_ante_tracking_error_ann": 0.11,
            "latest_ex_ante_rebalance_date": "2026-03-31",
            "latest_ex_ante_period_end_date": "2026-04-01",
        },
        versus_series="SPY",
        max_realized_tracking_error=0.08,
        max_ex_ante_tracking_error=0.10,
    )

    assert summary["review_required"] is True
    assert summary["breaches"] == [
        "realized_tracking_error",
        "ex_ante_tracking_error_ann",
    ]


def test_resolve_portfolio_name_prefers_recommendation_override():
    assert (
        update_mod._resolve_portfolio_name(
            {
                "recommendation": {"portfolio_name": "published_book"},
                "portfolio_construction": {"portfolio_name": "stored_book"},
            }
        )
        == "published_book"
    )
    assert update_mod._resolve_portfolio_name({}) == "cw2_core_equity"


def test_is_month_end_rebalance_day_uses_benchmark_calendar(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        update_mod,
        "load_trading_calendar",
        lambda engine, start_date, end_date, benchmark_ticker: captured.update(  # noqa: ARG005
            {
                "start_date": start_date,
                "end_date": end_date,
                "benchmark_ticker": benchmark_ticker,
            }
        )
        or [date(2026, 4, 29), date(2026, 4, 30)],
    )
    monkeypatch.setattr(
        update_mod,
        "get_month_end_trading_days",
        lambda trading_days: [date(2026, 4, 30)],  # noqa: ARG005
    )

    is_month_end = update_mod._is_month_end_rebalance_day(
        object(),
        date(2026, 4, 30),
        {"backtest": {"benchmark_ticker": "QQQ"}},
    )

    assert is_month_end is True
    assert captured == {
        "start_date": date(2026, 4, 1),
        "end_date": date(2026, 4, 30),
        "benchmark_ticker": "QQQ",
    }


def test_is_month_end_rebalance_day_filters_by_configured_frequency(monkeypatch):
    monkeypatch.setattr(
        update_mod,
        "load_trading_calendar",
        lambda engine, start_date, end_date, benchmark_ticker: [  # noqa: ARG005
            date(2026, 4, 29),
            date(2026, 4, 30),
        ],
    )
    monkeypatch.setattr(
        update_mod,
        "get_month_end_trading_days",
        lambda trading_days: [date(2026, 4, 30)],  # noqa: ARG005
    )

    assert (
        update_mod._is_month_end_rebalance_day(
            object(),
            date(2026, 4, 30),
            {
                "backtest": {
                    "benchmark_ticker": "QQQ",
                    "rebalance_frequency": "quarterly",
                }
            },
        )
        is False
    )


def test_load_snapshot_symbols_filters_blank_values():
    engine = _UpdateEngine([("AAPL",), (" ",), ("MSFT",)])

    symbols = update_mod._load_snapshot_symbols(
        engine,
        as_of_date=date(2026, 4, 30),
        portfolio_name="cw2_core_equity",
    )

    assert symbols == ["AAPL", "MSFT"]


def test_event_trigger_summary_counts_enabled_rules():
    engine = _UpdateEngine(
        [
            {
                "symbol": "AAPL",
                "factor_name": "sentiment_surprise",
                "factor_value": -0.30,
            },
            {"symbol": "AAPL", "factor_name": "article_count_30d", "factor_value": 6.0},
            {
                "symbol": "AAPL",
                "factor_name": "rating_downgrade_count_daily",
                "factor_value": 3.0,
            },
            {
                "symbol": "MSFT",
                "factor_name": "earnings_negative_news_count_daily",
                "factor_value": 2.0,
            },
            {
                "symbol": "MSFT",
                "factor_name": "earnings_publication_flag",
                "factor_value": 1.0,
            },
        ]
    )

    summary = update_mod._event_trigger_summary(
        engine,
        run_date=date(2026, 4, 30),
        signal_as_of_date=date(2026, 4, 29),
        config={
            "backtest": {
                "intraday_triggers": {
                    "event_driven_enabled": True,
                    "news_sentiment_shock_enabled": True,
                    "earnings_event_enabled": True,
                    "rating_downgrade_event_enabled": True,
                }
            }
        },
        symbols=["AAPL", "MSFT", "AAPL", ""],
    )

    assert summary == {
        "run_date": "2026-04-30",
        "signal_as_of_date": "2026-04-29",
        "portfolio_symbol_count": 2,
        "news_trigger_count": 1,
        "earnings_trigger_count": 1,
        "rating_trigger_count": 1,
        "trigger_symbol_count": 2,
        "trigger_symbols": ["AAPL", "MSFT"],
    }


def test_event_trigger_summary_short_circuits_without_enabled_events():
    summary = update_mod._event_trigger_summary(
        object(),
        run_date=date(2026, 4, 30),
        signal_as_of_date=date(2026, 4, 29),
        config={"backtest": {"intraday_triggers": {"event_driven_enabled": False}}},
        symbols=["AAPL"],
    )

    assert summary == {
        "run_date": "2026-04-30",
        "signal_as_of_date": "2026-04-29",
        "portfolio_symbol_count": 1,
        "news_trigger_count": 0,
        "earnings_trigger_count": 0,
        "rating_trigger_count": 0,
        "trigger_symbol_count": 0,
        "trigger_symbols": [],
    }


def test_event_trigger_summary_short_circuits_without_signal_as_of_date():
    summary = update_mod._event_trigger_summary(
        object(),
        run_date=date(2026, 4, 30),
        signal_as_of_date=None,
        config={"backtest": {"intraday_triggers": {"event_driven_enabled": True}}},
        symbols=["AAPL"],
    )

    assert summary == {
        "run_date": "2026-04-30",
        "signal_as_of_date": None,
        "portfolio_symbol_count": 1,
        "news_trigger_count": 0,
        "earnings_trigger_count": 0,
        "rating_trigger_count": 0,
        "trigger_symbol_count": 0,
        "trigger_symbols": [],
    }


def test_resolve_signal_as_of_date_prefers_price_anchor_and_falls_back(monkeypatch):
    rows = [
        {"signal_as_of_date": date(2026, 4, 14)},
        {"signal_as_of_date": date(2026, 4, 13)},
    ]

    class _SignalMappingsResult:
        def __init__(self, row):
            self._row = row

        def first(self):
            return self._row

    class _SignalExecuteResult:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return _SignalMappingsResult(self._row)

    class _SignalConn:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        def execute(self, stmt, params=None):
            self.calls.append((str(stmt), params))
            row = rows[len(self.calls) - 1] if len(self.calls) <= len(rows) else None
            return _SignalExecuteResult(row)

    class _SignalEngine:
        def __init__(self):
            self.conn = _SignalConn()

        def connect(self):
            return self.conn

    engine = _SignalEngine()

    resolved = update_mod._resolve_signal_as_of_date(
        engine,
        run_date=date(2026, 4, 15),
        symbols=["AAPL", "MSFT"],
    )

    assert resolved == date(2026, 4, 14)
    assert "factor_name = 'adjusted_close_price'" in engine.conn.calls[0][0]
