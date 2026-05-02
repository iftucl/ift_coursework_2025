"""Unit tests for CW2 analysis run-context reconstruction."""

from __future__ import annotations

import json
from datetime import date

from team_Pearson.coursework_two.modules import analysis as analysis_mod
from team_Pearson.coursework_two.modules.analysis import (
    _build_analysis_quality_report,
    _build_external_benchmark_nav,
    _load_run_row,
    _normalize_bind_value,
    _upsert_rows,
    load_analysis_run_context,
)


def test_load_analysis_run_context_trims_terminal_incomplete_period(monkeypatch):
    run_row = {
        "run_id": "run-1",
        "start_date": date(2026, 2, 1),
        "end_date": date(2026, 4, 14),
        "execution_lag": 1,
        "benchmark_ticker": "SPY",
        "transaction_cost_bps": 15,
        "config_snapshot": {"backtest": {}},
    }
    monkeypatch.setattr(analysis_mod, "_load_run_row", lambda run_id, db_engine: run_row)
    monkeypatch.setattr(
        analysis_mod,
        "load_trading_calendar",
        lambda *args, **kwargs: [
            date(2026, 2, 27),
            date(2026, 2, 28),
            date(2026, 3, 31),
            date(2026, 4, 1),
            date(2026, 4, 13),
        ],
    )
    monkeypatch.setattr(
        analysis_mod,
        "get_month_end_trading_days",
        lambda trading_calendar: [
            date(2026, 2, 27),
            date(2026, 3, 31),
            date(2026, 4, 13),
        ],
    )

    def _fake_shift(calendar, dt, lag):
        if dt == date(2026, 4, 13):
            raise ValueError("calendar exhausted")
        return date(2026, 2, 28) if dt == date(2026, 2, 27) else date(2026, 4, 1)

    monkeypatch.setattr(analysis_mod, "shift_trading_day", _fake_shift)
    monkeypatch.setattr(
        analysis_mod,
        "_load_strategy_performance",
        lambda run_id, db_engine: {
            date(2026, 4, 1): {
                "net_return": 0.01,
                "gross_return": 0.011,
                "portfolio_nav": 1.01,
            }
        },
    )

    context = load_analysis_run_context("run-1", db_engine=object(), config={"backtest": {}})

    assert len(context["periods"]) == 1
    assert context["periods"][0]["rebalance_date"] == date(2026, 2, 27)
    assert context["periods"][0]["period_end_date"] == date(2026, 4, 1)


def test_normalize_bind_value_serializes_json_payloads():
    payload = {
        "threshold": 0.0,
        "as_of_date": date(2026, 4, 14),
        "nested": {"passed": True},
    }

    encoded = _normalize_bind_value(payload)

    assert isinstance(encoded, str)
    assert '"threshold": 0.0' in encoded
    assert '"as_of_date": "2026-04-14"' in encoded


def test_build_analysis_quality_report_flags_materialized_outputs():
    report = _build_analysis_quality_report(
        run_id="run-123",
        result={
            "universe_ew_periods": 12,
            "static_baseline_periods": 12,
            "covariance_metric_rows": 8,
            "covariance_contribution_rows": 24,
            "scorecard_passed": 4,
            "scorecard_total": 5,
        },
    )

    assert report["run_id"] == "run-123"
    assert report["scorecard_total"] == 5
    assert report["passed"] is True


class _AnalysisMappingsResult:
    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]

    def first(self):
        return dict(self._rows[0]) if self._rows else None

    def all(self):
        return [dict(row) for row in self._rows]


class _AnalysisResult:
    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]

    def mappings(self):
        return _AnalysisMappingsResult(self._rows)


class _AnalysisConn:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, sql, params=None):
        self.executed.append({"sql": str(sql), "params": params})
        return _AnalysisResult(self._rows)


class _AnalysisEngine:
    def __init__(self, rows):
        self._rows = rows
        self.begin_calls = []

    def connect(self):
        return _AnalysisConn(self._rows)

    def begin(self):
        engine = self

        class _Begin:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):  # noqa: ARG002
                return False

            def execute(self_inner, sql, params):
                engine.begin_calls.append(
                    {
                        "sql": str(sql),
                        "params": [dict(row) for row in params],
                    }
                )

        return _Begin()


def test_run_full_analysis_materializes_all_outputs(monkeypatch):
    upserts = []
    quality = {}
    run_context = {
        "run_id": "run-1",
        "run_row": {"end_date": date(2026, 4, 30)},
        "config": {"backtest": {"analysis": {"secondary_benchmark": "universe_ew"}}},
        "analysis_config": {
            "stress_vix_threshold": 30.0,
            "secondary_benchmark": "universe_ew",
        },
        "periods": [
            {
                "period_end_date": date(2026, 3, 31),
                "benchmark_nav": 1.01,
                "benchmark_return": 0.01,
            },
            {
                "period_end_date": date(2026, 4, 30),
                "benchmark_nav": 1.02,
                "benchmark_return": 0.02,
            },
        ],
    }

    monkeypatch.setattr(analysis_mod, "ensure_analysis_schema", lambda engine: None)
    monkeypatch.setattr(
        analysis_mod,
        "load_analysis_run_context",
        lambda run_id, db_engine, config: run_context,
    )
    monkeypatch.setattr(
        analysis_mod,
        "classify_period_regimes",
        lambda db_engine, periods, threshold: {  # noqa: ARG005
            date(2026, 3, 31): {"regime": "normal"},
            date(2026, 4, 30): {"regime": "stress"},
        },
    )
    monkeypatch.setattr(
        analysis_mod,
        "build_universe_ew_path",
        lambda run_context, db_engine, period_regimes: (  # noqa: ARG005
            [
                {
                    "run_id": "run-1",
                    "period_end_date": date(2026, 3, 31),
                    "series_name": "universe_ew",
                    "nav": 1.0,
                    "period_return": 0.01,
                    "num_holdings": 20,
                    "regime": "normal",
                }
            ],
            {"universe": "weights"},
        ),
    )
    monkeypatch.setattr(
        analysis_mod,
        "build_static_baseline_path",
        lambda run_context, db_engine, period_regimes: (  # noqa: ARG005
            [
                {
                    "run_id": "run-1",
                    "period_end_date": date(2026, 3, 31),
                    "series_name": "static_baseline",
                    "nav": 0.99,
                    "period_return": 0.0,
                    "num_holdings": 5,
                    "regime": "normal",
                }
            ],
            {"static": "weights"},
        ),
    )
    monkeypatch.setattr(
        analysis_mod,
        "load_weight_sets",
        lambda run_context, db_engine, universe_weights, static_weights: {  # noqa: ARG005
            "strategy": {"AAPL": 0.5},
            "universe_ew": universe_weights,
            "static_baseline": static_weights,
        },
    )
    monkeypatch.setattr(
        analysis_mod,
        "compute_benchmark_absolute_metrics",
        lambda *args, **kwargs: [  # noqa: ARG005
            {
                "run_id": "run-1",
                "series_name": "SPY",
                "metric_name": "annualized_return",
                "metric_value": 1.2,
                "metric_unit": "%",
            }
        ],
    )
    monkeypatch.setattr(
        analysis_mod,
        "compute_covariance_diagnostics",
        lambda *args, **kwargs: (  # noqa: ARG005
            [{"metric_name": "tracking_error", "metric_value": 0.1}],
            [{"dimension_name": "Tech", "risk_contribution_pct": 0.4}],
        ),
    )
    monkeypatch.setattr(
        analysis_mod,
        "compute_relative_metrics",
        lambda *args, **kwargs: [
            {"metric_name": "information_ratio", "metric_value": 0.5}
        ],  # noqa: ARG005,E501
    )
    monkeypatch.setattr(
        analysis_mod,
        "compute_regime_attribution",
        lambda *args, **kwargs: [
            {"regime": "normal", "versus_series": "universe_ew"}
        ],  # noqa: ARG005,E501
    )
    monkeypatch.setattr(
        analysis_mod,
        "compute_factor_attribution",
        lambda *args, **kwargs: [
            {"factor_name": "quality", "active_exposure": 0.1}
        ],  # noqa: ARG005,E501
    )
    monkeypatch.setattr(
        analysis_mod,
        "compute_scorecard",
        lambda *args, **kwargs: [  # noqa: ARG005
            {"criterion_id": "c1", "passed": True},
            {"criterion_id": "c2", "passed": False},
        ],
    )
    monkeypatch.setattr(
        analysis_mod,
        "_upsert_rows",
        lambda engine, **kwargs: upserts.append(kwargs) or len(kwargs["rows"]),
    )
    monkeypatch.setattr(
        analysis_mod,
        "record_quality_snapshot",
        lambda **kwargs: quality.update(kwargs),
    )

    result = analysis_mod.run_full_analysis(
        run_id="run-1",
        db_engine=object(),
        config={"backtest": {"analysis": {"secondary_benchmark": "universe_ew"}}},
        robustness_run_id_25bps="robust-1",
    )

    assert result == {
        "universe_ew_periods": 1,
        "static_baseline_periods": 1,
        "benchmark_metric_rows": 1,
        "covariance_metric_rows": 1,
        "covariance_contribution_rows": 1,
        "factor_attribution_rows": 1,
        "scorecard_passed": 1,
        "scorecard_total": 2,
    }
    assert [call["table_name"] for call in upserts] == [
        "backtest_benchmark_nav",
        "backtest_benchmark_metrics",
        "backtest_covariance_metrics",
        "backtest_covariance_contributions",
        "backtest_relative_metrics",
        "backtest_regime_attribution",
        "backtest_factor_attribution",
        "backtest_scorecard",
    ]
    assert quality["dataset_name"] == "backtest_scorecard"
    assert quality["quality_report"]["passed"] is True
    assert quality["run_date"] == date(2026, 4, 30)


def test_build_external_benchmark_nav_uses_period_regime_lookup():
    rows = _build_external_benchmark_nav(
        {
            "run_id": "run-1",
            "analysis_config": {"primary_benchmark": "QQQ"},
            "periods": [
                {
                    "period_end_date": date(2026, 3, 31),
                    "benchmark_nav": 1.1,
                    "benchmark_return": 0.03,
                }
            ],
        },
        {date(2026, 3, 31): {"regime": "stress"}},
    )

    assert rows == [
        {
            "run_id": "run-1",
            "execution_date": None,
            "period_end_date": date(2026, 3, 31),
            "series_name": "QQQ",
            "nav": 1.1,
            "period_return": 0.03,
            "gross_return": None,
            "risk_free_return": None,
            "turnover": None,
            "gross_turnover": None,
            "transaction_cost": None,
            "num_holdings": None,
            "regime": "stress",
        }
    ]


def test_load_run_row_normalizes_config_snapshot_json():
    engine = _AnalysisEngine(
        [
            {
                "run_id": "run-1",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 4, 30),
                "rebalance_freq": "monthly",
                "execution_lag": 1,
                "transaction_cost_bps": 15,
                "weighting": "equal",
                "top_n": 25,
                "benchmark_ticker": "SPY",
                "config_snapshot": json.dumps({"backtest": {"lookback_years": 5}}),
            }
        ]
    )

    row = _load_run_row("run-1", engine)

    assert row["config_snapshot"]["backtest"]["lookback_years"] == 5
    assert row["benchmark_ticker"] == "SPY"


def test_upsert_rows_serializes_nested_payloads():
    engine = _AnalysisEngine([])

    inserted = _upsert_rows(
        engine,
        table_name="backtest_scorecard",
        rows=[
            {
                "run_id": "run-1",
                "criterion_id": "criterion-1",
                "criterion_name": "Quality",
                "passed": True,
                "evidence": {
                    "as_of_date": date(2026, 4, 30),
                    "details": [1, 2, {"ok": True}],
                },
            }
        ],
        allowed_cols=["run_id", "criterion_id", "criterion_name", "passed", "evidence"],
        conflict_cols=["run_id", "criterion_id"],
    )

    assert inserted == 1
    payload = engine.begin_calls[0]["params"][0]
    assert payload["run_id"] == "run-1"
    assert isinstance(payload["evidence"], str)
    assert '"as_of_date": "2026-04-30"' in payload["evidence"]


def test_run_analysis_from_config_uses_shared_engine_when_missing(monkeypatch):
    captured = {}
    fake_engine = object()
    monkeypatch.setattr(
        analysis_mod,
        "load_analysis_config",
        lambda path: {"config_path": path},
    )
    monkeypatch.setattr(
        analysis_mod,
        "run_full_analysis",
        lambda **kwargs: captured.update(kwargs) or {"status": "ok"},
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.backtest.engine._load_shared_db_engine",
        lambda: fake_engine,
        raising=False,
    )

    result = analysis_mod.run_analysis_from_config(
        run_id="run-1",
        config_path="cw2.yaml",
        robustness_run_id_25bps="robust-1",
    )

    assert result == {"status": "ok"}
    assert captured["run_id"] == "run-1"
    assert captured["db_engine"] is fake_engine
    assert captured["config"] == {"config_path": "cw2.yaml"}
