from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from team_Pearson.coursework_two.scripts import backfill_monthly_snapshots as snapshot_script
from team_Pearson.coursework_two.scripts import orchestration as orch
from team_Pearson.coursework_two.scripts import (
    run_backtest_analysis_report as backtest_report_script,
)
from team_Pearson.coursework_two.scripts import run_kafka_event_audit as kafka_audit_script
from team_Pearson.coursework_two.scripts import (
    run_kafka_event_audit_daemon as kafka_audit_daemon_script,
)
from team_Pearson.coursework_two.scripts import run_operated_flow as operate_script
from team_Pearson.coursework_two.scripts import run_readiness_audit as audit_script
from team_Pearson.coursework_two.scripts import run_update_decision as update_script


def test_coerce_optional_helpers():
    assert orch.coerce_optional_str("") is None
    assert orch.coerce_optional_str("null") is None
    assert orch.coerce_optional_str("x") == "x"
    assert orch.coerce_optional_int("7") == 7
    assert orch.coerce_optional_float("15.5") == 15.5
    assert orch.coerce_bool("true") is True
    assert orch.coerce_bool("false") is False


def test_is_month_end_trading_day_uses_month_window(monkeypatch):
    captured = {}

    def fake_month_end_trading_days(*, start_date, end_date, cw2_config_path, db_engine=None):
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["cw2_config_path"] = cw2_config_path
        return [date(2026, 4, 30)]

    monkeypatch.setattr(orch, "month_end_trading_days", fake_month_end_trading_days)

    assert (
        orch.is_month_end_trading_day(
            run_date=date(2026, 4, 30),
            cw2_config_path="cw2.yaml",
        )
        is True
    )
    assert captured["start_date"] == date(2026, 4, 1)
    assert captured["end_date"] == date(2026, 4, 30)
    assert captured["cw2_config_path"] == "cw2.yaml"


def test_scheduled_rebalance_trading_days_filters_by_frequency(monkeypatch):
    monkeypatch.setattr(
        orch,
        "month_end_trading_days",
        lambda **kwargs: [  # noqa: ARG005
            date(2026, 1, 30),
            date(2026, 2, 27),
            date(2026, 3, 31),
            date(2026, 4, 30),
            date(2026, 6, 30),
        ],
    )
    monkeypatch.setattr(
        orch, "resolve_rebalance_frequency", lambda path: "quarterly"  # noqa: ARG005
    )

    assert orch.scheduled_rebalance_trading_days(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        cw2_config_path="cw2.yaml",
    ) == [date(2026, 3, 31), date(2026, 6, 30)]


def test_is_rebalance_trading_day_uses_configured_schedule(monkeypatch):
    captured = {}

    def fake_scheduled_rebalance_trading_days(
        *, start_date, end_date, cw2_config_path, db_engine=None, include_first=False
    ):
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["cw2_config_path"] = cw2_config_path
        captured["include_first"] = include_first
        return [date(2026, 6, 30)]

    monkeypatch.setattr(
        orch,
        "scheduled_rebalance_trading_days",
        fake_scheduled_rebalance_trading_days,
    )

    assert (
        orch.is_rebalance_trading_day(
            run_date=date(2026, 6, 30),
            cw2_config_path="cw2.yaml",
        )
        is True
    )
    assert captured["start_date"] == date(2026, 6, 1)
    assert captured["end_date"] == date(2026, 6, 30)
    assert captured["cw2_config_path"] == "cw2.yaml"
    assert captured["include_first"] is False


def test_build_main_cmd_with_optional_args():
    class Args:
        run_date = "2026-04-30"
        cw1_config = "cw1.yaml"
        cw2_config = "cw2.yaml"
        company_limit = "70"
        recommendation_name = "rec"
        briefing_dir = "briefings"
        decision_actor = "airflow_cw2"
        auto_approve = True
        auto_publish = False

    cmd = operate_script._build_main_cmd(Args())
    assert "--mode" in cmd and "operate" in cmd
    assert "--company-limit" in cmd and "70" in cmd
    assert "--recommendation-name" in cmd and "rec" in cmd
    assert "--briefing-dir" in cmd and "briefings" in cmd
    assert "--auto-approve" in cmd
    assert "--auto-publish" not in cmd


def test_operate_main_skips_when_not_rebalance_anchor(monkeypatch):
    monkeypatch.setattr(operate_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(
        operate_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        run_date="2026-04-30",
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        company_limit=None,
                        recommendation_name=None,
                        briefing_dir=None,
                        decision_actor="airflow_cw2",
                        auto_approve=False,
                        auto_publish=False,
                        require_rebalance_anchor=True,
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        operate_script,
        "is_rebalance_trading_day",
        lambda **kwargs: False,  # noqa: ARG005
    )
    payloads = []
    monkeypatch.setattr(
        operate_script,
        "print_json",
        lambda payload: payloads.append(payload),
    )

    assert operate_script.main() == 0
    assert payloads == [
        {
            "status": "skipped",
            "reason": "run_date is not the configured trading rebalance anchor",
            "run_date": "2026-04-30",
        }
    ]


def test_build_update_decision_cmd():
    class Args:
        run_date = "2026-04-15"
        cw1_config = "cw1.yaml"
        cw2_config = "cw2.yaml"
        with_upstream = True

    cmd = update_script._build_main_cmd(Args())
    assert "--mode" in cmd and "update-decision" in cmd
    assert "--run-date" in cmd and "2026-04-15" in cmd
    assert "--with-upstream" in cmd


def test_backtest_analysis_report_uses_existing_run_id(monkeypatch):
    monkeypatch.setattr(backtest_report_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(backtest_report_script, "load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(backtest_report_script, "_optional_db_engine", lambda: None)
    monkeypatch.setattr(
        backtest_report_script, "load_stage_context", lambda path: {}
    )  # noqa: ARG005
    monkeypatch.setattr(
        backtest_report_script,
        "merge_stage_context",
        lambda path, updates: dict(updates),
    )  # noqa: ARG005,E501
    monkeypatch.setattr(
        backtest_report_script, "runtime_lock", lambda **kwargs: _NullCtx()
    )  # noqa: ARG005
    monkeypatch.setattr(backtest_report_script, "_emit_stage_event", lambda **kwargs: None)
    monkeypatch.setattr(backtest_report_script, "_record_stage_quality", lambda **kwargs: None)
    monkeypatch.setattr(
        backtest_report_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw2_config="cw2.yaml",
                        run_id="6905e84b-9e16-4106-8c0f-cd9ecce56728",
                        run_name="ignored_name",
                        transaction_cost_bps=None,
                        robustness_run_id="robust-1",
                        report_name="report-1",
                        report_output_dir="reports",
                        summary_path=None,
                        context_path=None,
                        reference_json="reference.json",
                        verify_tolerance=0.001,
                        verify_reference="false",
                        runtime_lock_ttl_seconds=60,
                        stage="bundle",
                        cw1_config="cw1.yaml",
                    )
                )
            },
        )(),
    )
    payloads = []
    monkeypatch.setattr(backtest_report_script, "print_json", payloads.append)
    monkeypatch.setattr(
        backtest_report_script,
        "run_backtest_from_config",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not backtest")),
    )
    monkeypatch.setattr(
        backtest_report_script,
        "run_analysis_from_config",
        lambda **kwargs: {"analysis_run_id": kwargs["run_id"]},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "generate_backtest_report_from_config",
        lambda **kwargs: {"report_run_id": kwargs["run_id"]},
    )

    assert backtest_report_script.main() == 0
    assert payloads == [
        {
            "execution_mode": "existing_run",
            "run_id": "6905e84b-9e16-4106-8c0f-cd9ecce56728",
            "run_name": "ignored_name",
            "analysis": {"analysis_run_id": "6905e84b-9e16-4106-8c0f-cd9ecce56728"},
            "report": {"report_run_id": "6905e84b-9e16-4106-8c0f-cd9ecce56728"},
        }
    ]


def test_backtest_analysis_report_rejects_existing_run_with_cost_override(monkeypatch):
    monkeypatch.setattr(backtest_report_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(backtest_report_script, "load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(backtest_report_script, "_optional_db_engine", lambda: None)
    monkeypatch.setattr(
        backtest_report_script, "load_stage_context", lambda path: {}
    )  # noqa: ARG005
    monkeypatch.setattr(
        backtest_report_script,
        "merge_stage_context",
        lambda path, updates: dict(updates),
    )  # noqa: ARG005,E501
    monkeypatch.setattr(
        backtest_report_script, "runtime_lock", lambda **kwargs: _NullCtx()
    )  # noqa: ARG005
    monkeypatch.setattr(backtest_report_script, "_emit_stage_event", lambda **kwargs: None)
    monkeypatch.setattr(backtest_report_script, "_record_stage_quality", lambda **kwargs: None)
    monkeypatch.setattr(
        backtest_report_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw2_config="cw2.yaml",
                        run_id="run-1",
                        run_name=None,
                        transaction_cost_bps="25",
                        robustness_run_id=None,
                        report_name=None,
                        report_output_dir=None,
                        summary_path=None,
                        context_path=None,
                        reference_json="reference.json",
                        verify_tolerance=0.001,
                        verify_reference="false",
                        runtime_lock_ttl_seconds=60,
                        stage="bundle",
                        cw1_config="cw1.yaml",
                    )
                )
            },
        )(),
    )

    try:
        backtest_report_script.main()
    except ValueError as exc:
        assert "--transaction-cost-bps cannot be used together with --run-id" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_materialize_market_factor_history_uses_cw1_benchmark(monkeypatch):
    captured = {}

    monkeypatch.setattr(snapshot_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(
        snapshot_script,
        "load_yaml",
        lambda path: {"market_factors": {"benchmark_ticker": "QQQ"}},
    )

    def fake_build_market_factors(
        symbols, *, start_date, end_date, output_frequency, benchmark_ticker
    ):
        captured["symbols"] = symbols
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["output_frequency"] = output_frequency
        captured["benchmark_ticker"] = benchmark_ticker
        return [
            {
                "symbol": "AAPL",
                "observation_date": "2026-01-30",
                "factor_name": "momentum_6m",
                "factor_value": 0.12,
                "source": "factor_transform_market",
                "metric_frequency": "daily",
                "source_report_date": "2026-01-30",
                "publish_date": "2026-01-30",
            }
        ]

    def fake_load_curated(rows, *, dry_run, stats_out):
        captured["dry_run"] = dry_run
        stats_out["inserted"] = len(rows)
        return len(rows)

    monkeypatch.setattr(
        snapshot_script,
        "_market_factor_dependencies",
        lambda: (
            fake_build_market_factors,
            lambda records: list(records),
            fake_load_curated,
        ),
    )

    result = snapshot_script._materialize_market_factor_history(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        symbols=["AAPL", "MSFT"],
        cw1_config_path="cw1.yaml",
    )

    assert captured["symbols"] == ["AAPL", "MSFT"]
    assert captured["start_date"] == date(2026, 1, 1)
    assert captured["end_date"] == date(2026, 3, 31)
    assert captured["output_frequency"] == "daily"
    assert captured["benchmark_ticker"] == "QQQ"
    assert captured["dry_run"] is False
    assert result == {
        "computed_rows": 1,
        "loaded_rows": 1,
        "benchmark_ticker": "QQQ",
        "stats": {"inserted": 1},
    }


def test_backfill_main_uses_portfolio_name_from_cw2_config_for_skip_existing(
    monkeypatch,
):
    monkeypatch.setattr(snapshot_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(snapshot_script, "get_db_engine", lambda: object())
    monkeypatch.setattr(
        snapshot_script, "runtime_lock", lambda **kwargs: _NullCtx()
    )  # noqa: ARG005
    monkeypatch.setattr(snapshot_script, "emit_scheduler_stage_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(snapshot_script, "record_runtime_quality_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(snapshot_script, "record_scheduler_pipeline_state", lambda **kwargs: None)
    monkeypatch.setattr(snapshot_script, "record_scheduler_stage_state", lambda **kwargs: None)
    captured_context = {}
    monkeypatch.setattr(
        snapshot_script,
        "merge_stage_context",
        lambda path, updates: captured_context.update({"path": path}) or {},
    )
    monkeypatch.setattr(
        snapshot_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        start_date="2026-01-01",
                        end_date="2026-01-31",
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        company_limit=None,
                        skip_existing="true",
                        refresh_market_factors="false",
                        context_path=None,
                        runtime_lock_ttl_seconds=60,
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(snapshot_script, "coerce_bool", orch.coerce_bool)
    monkeypatch.setattr(snapshot_script, "coerce_optional_int", lambda value: None)
    monkeypatch.setattr(
        snapshot_script,
        "_cw2_feature_builder",
        lambda: lambda **kwargs: {"portfolio_targets": 0},
    )  # noqa: ARG005,E501
    monkeypatch.setattr(
        snapshot_script,
        "validate_shared_runtime_contract",
        lambda *args: {"status": "ok"},
    )  # noqa: ARG005
    monkeypatch.setattr(
        snapshot_script,
        "load_yaml",
        lambda path: (
            {"pipeline": {"company_limit": 0}}
            if path == "cw1.yaml"
            else {"portfolio_construction": {"portfolio_name": "cw2_test_portfolio"}}
        ),
    )
    monkeypatch.setattr(
        snapshot_script,
        "load_scheduler_symbols",
        lambda **kwargs: ["AAPL"],  # noqa: ARG005
    )
    monkeypatch.setattr(
        snapshot_script,
        "month_end_trading_days",
        lambda **kwargs: [date(2026, 1, 30)],  # noqa: ARG005
    )
    captured = {}

    def _fake_existing_count(**kwargs):
        captured["portfolio_name"] = kwargs["portfolio_name"]
        return 2

    monkeypatch.setattr(
        snapshot_script,
        "existing_portfolio_target_count",
        _fake_existing_count,
    )
    payloads = []
    monkeypatch.setattr(
        snapshot_script,
        "print_json",
        lambda payload: payloads.append(payload),
    )

    result = snapshot_script.main()

    assert result == 0
    assert captured["portfolio_name"] == "cw2_test_portfolio"
    assert captured_context["path"] is None
    assert payloads[0]["portfolio_name"] == "cw2_test_portfolio"
    assert payloads[0]["skipped_existing_count"] == 1


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_backtest_analysis_stage_reads_run_id_from_context(monkeypatch):
    monkeypatch.setattr(backtest_report_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(backtest_report_script, "load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(backtest_report_script, "_optional_db_engine", lambda: None)
    monkeypatch.setattr(
        backtest_report_script,
        "load_stage_context",
        lambda path: {"run_id": "run-from-context"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "merge_stage_context",
        lambda path, updates: dict(updates),  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script, "runtime_lock", lambda **kwargs: _NullCtx()
    )  # noqa: ARG005
    monkeypatch.setattr(backtest_report_script, "_emit_stage_event", lambda **kwargs: None)
    monkeypatch.setattr(backtest_report_script, "_record_stage_quality", lambda **kwargs: None)
    monkeypatch.setattr(
        backtest_report_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        run_id=None,
                        run_name=None,
                        transaction_cost_bps=None,
                        robustness_run_id=None,
                        report_name=None,
                        report_output_dir=None,
                        summary_path=None,
                        context_path="context.json",
                        reference_json="reference.json",
                        verify_tolerance=0.001,
                        verify_reference="false",
                        runtime_lock_ttl_seconds=60,
                        stage="analysis",
                    )
                )
            },
        )(),
    )
    payloads = []
    monkeypatch.setattr(backtest_report_script, "print_json", payloads.append)
    monkeypatch.setattr(
        backtest_report_script,
        "run_analysis_from_config",
        lambda **kwargs: {"analysis_run_id": kwargs["run_id"]},
    )

    assert backtest_report_script.main() == 0
    assert payloads == [{"analysis_run_id": "run-from-context"}]


def test_run_readiness_audit_exits_nonzero_when_not_ready(monkeypatch):
    monkeypatch.setattr(audit_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(audit_script, "get_db_engine", lambda: object())
    monkeypatch.setattr(audit_script, "load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(audit_script, "emit_scheduler_stage_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(audit_script, "record_runtime_quality_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(audit_script, "record_scheduler_pipeline_state", lambda **kwargs: None)
    monkeypatch.setattr(audit_script, "record_scheduler_stage_state", lambda **kwargs: None)
    monkeypatch.setattr(audit_script, "merge_stage_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        audit_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        context_path=None,
                        pipeline_name="cw2_readiness_audit",
                        stage_name="cw2_readiness_audit",
                        readiness_profile="strict",
                        require_ready="true",
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        audit_script,
        "run_audit_from_config",
        lambda **kwargs: {
            "readiness": {"is_ready": False, "overall_status": "error"}
        },  # noqa: ARG005
    )
    payloads = []
    monkeypatch.setattr(audit_script, "print_json", payloads.append)

    assert audit_script.main() == 1
    assert payloads[0]["ready"] is False


def test_run_readiness_audit_backfill_profile_allows_partial_storage(monkeypatch):
    monkeypatch.setattr(audit_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(audit_script, "get_db_engine", lambda: object())
    monkeypatch.setattr(audit_script, "load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(audit_script, "emit_scheduler_stage_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(audit_script, "record_runtime_quality_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(audit_script, "record_scheduler_pipeline_state", lambda **kwargs: None)
    monkeypatch.setattr(audit_script, "record_scheduler_stage_state", lambda **kwargs: None)
    monkeypatch.setattr(audit_script, "merge_stage_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        audit_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        context_path=None,
                        pipeline_name="cw2_monthly_snapshot_backfill",
                        stage_name="cw2_post_backfill_audit",
                        readiness_profile="post_backfill",
                        require_ready="true",
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        audit_script,
        "run_audit_from_config",
        lambda **kwargs: {  # noqa: ARG005
            "readiness": {
                "overall_status": "partial",
                "core_sql_ready": True,
                "feature_pipeline_ready": True,
                "storage_ready": False,
                "backtest_ready": False,
            },
            "semantic_checks": {
                "portfolio_target_positions": {"status": "ok"},
            },
        },
    )
    payloads = []
    monkeypatch.setattr(audit_script, "print_json", payloads.append)

    assert audit_script.main() == 0
    assert payloads[0]["ready"] is True
    assert payloads[0]["readiness_profile"] == "post_backfill"


def test_run_kafka_event_audit_warning_is_nonfatal(monkeypatch):
    monkeypatch.setattr(kafka_audit_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(kafka_audit_script, "get_db_engine", lambda: object())
    monkeypatch.setattr(kafka_audit_script, "load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(
        kafka_audit_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        pipeline_name="cw2_monthly_snapshot_backfill",
                        stage_name="audit_kafka_event_bus",
                        context_path="context.json",
                        max_messages=25,
                        poll_timeout_ms=1000,
                        max_idle_polls=2,
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        kafka_audit_script,
        "run_kafka_event_audit_from_config",
        lambda **kwargs: {  # noqa: ARG005
            "status": "warning",
            "reason": "consumer unavailable",
            "processed_count": 0,
            "consumed_count": 0,
        },
    )
    monkeypatch.setattr(
        kafka_audit_script, "emit_scheduler_stage_event", lambda *args, **kwargs: None
    )
    pipeline_state_calls = []
    monkeypatch.setattr(
        kafka_audit_script,
        "record_scheduler_pipeline_state",
        lambda **kwargs: pipeline_state_calls.append(kwargs),
    )
    monkeypatch.setattr(kafka_audit_script, "record_scheduler_stage_state", lambda **kwargs: None)
    monkeypatch.setattr(
        kafka_audit_script,
        "merge_stage_context",
        lambda path, updates: dict(updates),  # noqa: ARG005
    )
    captured_quality = {}
    monkeypatch.setattr(
        kafka_audit_script,
        "record_runtime_quality_snapshot",
        lambda **kwargs: captured_quality.update(kwargs),
    )
    payloads = []
    monkeypatch.setattr(kafka_audit_script, "print_json", payloads.append)

    assert kafka_audit_script.main() == 0
    assert payloads[0]["status"] == "warning"
    assert captured_quality["passed"] is True
    assert captured_quality["warnings"] == ["consumer unavailable"]
    assert pipeline_state_calls[-1]["context"]["audit_kafka_event_bus"]["status"] == "warning"
    assert pipeline_state_calls[-1]["metrics"]["return_code"] == 0


def test_run_kafka_event_audit_exception_fails(monkeypatch):
    monkeypatch.setattr(kafka_audit_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(kafka_audit_script, "get_db_engine", lambda: object())
    monkeypatch.setattr(kafka_audit_script, "load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(
        kafka_audit_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        pipeline_name="cw2_monthly_snapshot_backfill",
                        stage_name="audit_kafka_event_bus",
                        context_path="context.json",
                        max_messages=25,
                        poll_timeout_ms=1000,
                        max_idle_polls=2,
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        kafka_audit_script,
        "run_kafka_event_audit_from_config",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),  # noqa: ARG005
    )
    monkeypatch.setattr(
        kafka_audit_script, "emit_scheduler_stage_event", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        kafka_audit_script, "record_scheduler_pipeline_state", lambda **kwargs: None
    )
    monkeypatch.setattr(kafka_audit_script, "record_scheduler_stage_state", lambda **kwargs: None)
    monkeypatch.setattr(kafka_audit_script, "merge_stage_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        kafka_audit_script, "record_runtime_quality_snapshot", lambda **kwargs: None
    )
    payloads = []
    monkeypatch.setattr(kafka_audit_script, "print_json", payloads.append)

    assert kafka_audit_script.main() == 1
    assert payloads[0]["status"] == "error"


def test_run_kafka_event_audit_daemon_once_uses_dedicated_component(monkeypatch):
    monkeypatch.setattr(kafka_audit_daemon_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(kafka_audit_daemon_script, "get_db_engine", lambda: object())
    monkeypatch.setattr(
        kafka_audit_daemon_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        pipeline_name="cw2_kafka_audit_consumer",
                        stage_name="consume_and_audit",
                        poll_interval_seconds=30,
                        max_messages=200,
                        poll_timeout_ms=1000,
                        max_idle_polls=3,
                        runtime_lock_name="cw2_kafka_audit_consumer",
                        runtime_lock_ttl_seconds=300,
                        once=True,
                    )
                )
            },
        )(),
    )

    class _Handle:
        requested_name = "cw2_kafka_audit_consumer"
        redis_key = "cw2:runtime:lock:cw2_kafka_audit_consumer"
        acquired = True

    monkeypatch.setattr(
        kafka_audit_daemon_script,
        "acquire_runtime_lock",
        lambda **kwargs: _Handle(),
    )
    monkeypatch.setattr(
        kafka_audit_daemon_script,
        "release_runtime_lock",
        lambda handle: None,  # noqa: ARG005
    )
    monkeypatch.setattr(
        kafka_audit_daemon_script,
        "_register_signal_handlers",
        lambda: None,
    )
    captured = {}

    def _fake_run_audit_cycle(**kwargs):
        captured.update(kwargs)
        return 0, {"status": "ok", "processed_count": 1}

    monkeypatch.setattr(
        kafka_audit_daemon_script,
        "run_audit_cycle",
        _fake_run_audit_cycle,
    )
    payloads = []
    monkeypatch.setattr(kafka_audit_daemon_script, "print_json", payloads.append)

    assert kafka_audit_daemon_script.main() == 0
    assert captured["audit_overrides"] == {"consumer_component": "cw2.kafka_audit_daemon"}
    assert captured["producer_component"] == "cw2.kafka_audit_daemon"
    assert payloads[0]["status"] == "ok"


def test_orchestration_config_helpers_and_json_output(monkeypatch, tmp_path, capsys):
    env_calls = []
    monkeypatch.setattr(
        orch,
        "load_dotenv_if_exists",
        lambda path, override=False: env_calls.append((Path(path).name, override)),
    )
    orch.load_env_layers()
    assert env_calls == [(".env", False), (".env", True)]

    config_path = tmp_path / "custom.yaml"
    config_path.write_text("pipeline:\n  company_limit: 12\n", encoding="utf-8")
    assert orch.load_yaml(str(config_path))["pipeline"]["company_limit"] == 12

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.utils.config_validation.load_cw2_config",
        lambda path: {"loaded_from": path},
        raising=False,
    )
    assert orch.load_yaml(orch.default_cw2_config())["loaded_from"].endswith("conf.yaml")

    orch.print_json({"run_date": date(2026, 4, 21)})
    captured = capsys.readouterr()
    assert '"2026-04-21"' in captured.out


def test_orchestration_resolve_helpers_and_scheduler_queries(monkeypatch):
    monkeypatch.setattr(
        orch,
        "load_yaml",
        lambda path: {
            "pipeline": {"company_limit": 12},
            "universe": {"country_allowlist": ["US", "GB"]},
            "backtest": {"benchmark_ticker": "QQQ", "rebalance_frequency": "annual"},
            "portfolio_construction": {"target_generation_frequency": "quarterly"},
        },
    )
    assert orch.resolve_company_limit(None, "cw1.yaml") == 12
    assert orch.resolve_country_allowlist("cw1.yaml") == ["US", "GB"]
    assert orch.resolve_benchmark_ticker("cw2.yaml") == "QQQ"
    assert orch.resolve_rebalance_frequency("cw2.yaml") == "annual"

    monkeypatch.setattr(orch, "load_env_layers", lambda: None)
    monkeypatch.setattr(orch, "get_db_engine", lambda: "engine")
    monkeypatch.setattr(orch, "resolve_benchmark_ticker", lambda path: "SPY")
    monkeypatch.setattr(
        orch,
        "load_trading_calendar",
        lambda engine, start_date, end_date, benchmark_ticker: [
            start_date,
            end_date,
        ],  # noqa: ARG005,E501
    )
    monkeypatch.setattr(
        orch,
        "get_month_end_trading_days",
        lambda trading_days: [trading_days[-1]],
    )
    assert orch.month_end_trading_days(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
        cw2_config_path="cw2.yaml",
    ) == [date(2026, 4, 30)]


def test_scheduled_rebalance_include_first_and_existing_target_count(monkeypatch):
    monkeypatch.setattr(
        orch,
        "month_end_trading_days",
        lambda **kwargs: [
            date(2026, 1, 30),
            date(2026, 3, 31),
            date(2026, 12, 31),
        ],
    )
    monkeypatch.setattr(orch, "resolve_rebalance_frequency", lambda path: "annual")
    scheduled = orch.scheduled_rebalance_trading_days(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        cw2_config_path="cw2.yaml",
        include_first=True,
    )
    assert scheduled == [date(2026, 1, 30), date(2026, 12, 31)]

    monkeypatch.setattr(orch, "load_env_layers", lambda: None)

    class _ScalarConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        def execute(self, sql, params):
            return type("_Result", (), {"scalar_one": staticmethod(lambda: 7)})()

    monkeypatch.setattr(
        orch,
        "get_db_engine",
        lambda: type("_Engine", (), {"connect": staticmethod(lambda: _ScalarConn())})(),
    )
    assert (
        orch.existing_portfolio_target_count(
            as_of_date=date(2026, 4, 30),
            portfolio_name="cw2_core_equity",
        )
        == 7
    )


def test_update_and_operate_wrappers_execute_main_commands(monkeypatch):
    monkeypatch.setattr(update_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(
        update_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        run_date="2026-04-15",
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        with_upstream=False,
                    )
                )
            },
        )(),
    )
    update_captured = {}
    monkeypatch.setattr(
        update_script.subprocess,
        "run",
        lambda cmd, cwd, env, check: update_captured.update(
            {"cmd": cmd, "cwd": cwd}
        )  # noqa: ARG005,E501
        or type("Completed", (), {"returncode": 0})(),
    )
    assert update_script.main() == 0
    assert "--mode" in update_captured["cmd"] and "update-decision" in update_captured["cmd"]

    monkeypatch.setattr(operate_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(
        operate_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        run_date="2026-04-30",
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        company_limit="20",
                        recommendation_name="rec-demo",
                        briefing_dir="briefings",
                        decision_actor="airflow_cw2",
                        auto_approve=True,
                        auto_publish=True,
                        require_rebalance_anchor=False,
                    )
                )
            },
        )(),
    )
    operate_captured = {}
    monkeypatch.setattr(
        operate_script.subprocess,
        "run",
        lambda cmd, cwd, env, check: operate_captured.update(
            {"cmd": cmd, "cwd": cwd}
        )  # noqa: ARG005,E501
        or type("Completed", (), {"returncode": 0})(),
    )
    assert operate_script.main() == 0
    assert "--auto-publish" in operate_captured["cmd"]
    assert "--company-limit" in operate_captured["cmd"]


def test_wrapper_parsers_expose_expected_defaults():
    update_args = update_script.build_parser().parse_args(["--run-date", "2026-04-15"])
    assert update_args.with_upstream is False
    assert update_args.cw1_config.endswith("conf.yaml")

    operate_args = operate_script.build_parser().parse_args(["--run-date", "2026-04-30"])
    assert operate_args.require_rebalance_anchor is True
    assert operate_args.decision_actor == "airflow_cw2"

    audit_args = audit_script.build_parser().parse_args([])
    assert audit_args.readiness_profile == "strict"
    assert audit_args.require_ready == "true"

    kafka_args = kafka_audit_script.build_parser().parse_args([])
    assert kafka_args.pipeline_name == "cw2_kafka_event_audit"
    assert kafka_args.stage_name == "audit_kafka_event_bus"

    daemon_args = kafka_audit_daemon_script.build_parser().parse_args([])
    assert daemon_args.runtime_lock_name == "cw2_kafka_audit_consumer"
    assert daemon_args.once is False


def test_kafka_audit_daemon_signal_and_waiting_lock(monkeypatch):
    registered = []
    monkeypatch.setattr(
        kafka_audit_daemon_script.signal,
        "signal",
        lambda signum, handler: registered.append(signum),
    )
    kafka_audit_daemon_script._register_signal_handlers()
    assert len(registered) == 2

    payloads = []
    monkeypatch.setattr(kafka_audit_daemon_script, "print_json", payloads.append)
    kafka_audit_daemon_script._STOP_EVENT.clear()
    kafka_audit_daemon_script._handle_signal(15, None)
    assert payloads[0]["status"] == "stopping"
    assert kafka_audit_daemon_script._STOP_EVENT.is_set() is True

    monkeypatch.setattr(kafka_audit_daemon_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(kafka_audit_daemon_script, "_register_signal_handlers", lambda: None)
    monkeypatch.setattr(kafka_audit_daemon_script, "get_db_engine", lambda: object())
    monkeypatch.setattr(
        kafka_audit_daemon_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        pipeline_name="cw2_kafka_audit_consumer",
                        stage_name="consume_and_audit",
                        poll_interval_seconds=30,
                        max_messages=200,
                        poll_timeout_ms=1000,
                        max_idle_polls=3,
                        runtime_lock_name="cw2_kafka_audit_consumer",
                        runtime_lock_ttl_seconds=300,
                        once=True,
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        kafka_audit_daemon_script,
        "acquire_runtime_lock",
        lambda **kwargs: type(
            "_Handle",
            (),
            {
                "requested_name": "cw2_kafka_audit_consumer",
                "redis_key": "cw2:runtime:lock:cw2_kafka_audit_consumer",
                "acquired": False,
            },
        )(),
    )
    wait_payloads = []
    monkeypatch.setattr(kafka_audit_daemon_script, "print_json", wait_payloads.append)
    kafka_audit_daemon_script._STOP_EVENT.clear()
    assert kafka_audit_daemon_script.main() == 0
    assert wait_payloads[0]["status"] == "waiting_for_lock"


def test_backtest_report_helper_resolution_and_stage_metadata(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text('{"artifact_count": 4}', encoding="utf-8")
    context = {
        "run_id": "run-1",
        "run_name": "cw2-demo",
        "report": {"json_path": str(summary_path), "report_name": "cw2-report"},
    }
    args = backtest_report_script.build_parser().parse_args(
        [
            "--cw1-config",
            "cw1.yaml",
            "--cw2-config",
            "cw2.yaml",
            "--stage",
            "verify",
            "--run-id",
            "run-1",
            "--context-path",
            "context.json",
            "--pipeline-name",
            "cw2_pipeline",
        ]
    )

    assert backtest_report_script._load_json(str(summary_path))["artifact_count"] == 4
    assert backtest_report_script._resolved_run_id(args, context) == "run-1"
    assert backtest_report_script._resolved_run_name(args, context) == "cw2-demo"
    assert backtest_report_script._resolved_report_json_path(
        argparse.Namespace(summary_path=None), context
    ) == str(summary_path)
    assert backtest_report_script._pipeline_name(args) == "cw2_pipeline"
    assert (
        backtest_report_script._pipeline_execution_key(args, context) == "cw2_pipeline:context.json"
    )
    assert (
        backtest_report_script._execution_key(stage="verify", args=args, context=context)
        == "cw2_pipeline:context.json:verify"
    )
    assert backtest_report_script._stage_order("report") == 30
    assert backtest_report_script._stage_dataset_name("verify") == "cw2_scheduler_verify"


def test_backtest_report_stage_helpers(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(backtest_report_script, "_load_json", lambda path: {})
    monkeypatch.setattr(
        backtest_report_script, "run_backtest_from_config", lambda **kwargs: "run-2"
    )
    monkeypatch.setattr(
        backtest_report_script,
        "run_analysis_from_config",
        lambda **kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "generate_backtest_report_from_config",
        lambda **kwargs: {"report_id": "report-1", "json_path": str(summary_path)},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "verify_summary_against_reference",
        lambda **kwargs: ([], {"layer_1_metadata_and_metrics": True}),
    )

    backtest_context = backtest_report_script._run_backtest_stage(
        args=argparse.Namespace(
            run_id=None,
            run_name="cw2-demo",
            transaction_cost_bps="25",
            cw2_config="cw2.yaml",
        ),
        context={},
    )
    analysis_context = backtest_report_script._run_analysis_stage(
        args=argparse.Namespace(run_id=None, robustness_run_id="robust-1", cw2_config="cw2.yaml"),
        context={"run_id": "run-2"},
    )
    report_context = backtest_report_script._run_report_stage(
        args=argparse.Namespace(
            run_id=None,
            report_name="cw2-report",
            report_output_dir="reports",
            cw2_config="cw2.yaml",
        ),
        context={"run_id": "run-2"},
    )
    verify_context = backtest_report_script._run_verify_stage(
        args=argparse.Namespace(
            summary_path=str(summary_path),
            reference_json="reference.json",
            verify_tolerance=0.001,
        ),
        context={"report": {"json_path": str(summary_path)}},
    )

    assert backtest_context["execution_mode"] == "new_backtest"
    assert backtest_context["run_id"] == "run-2"
    assert analysis_context["analysis"]["status"] == "ok"
    assert report_context["report"]["report_id"] == "report-1"
    assert verify_context["verification"]["passed"] is True


def test_backtest_report_verify_stage_validates_summary_path_and_failures(monkeypatch):
    try:
        backtest_report_script._run_verify_stage(
            args=argparse.Namespace(
                summary_path=None,
                reference_json="reference.json",
                verify_tolerance=0.001,
            ),
            context={},
        )
    except ValueError as exc:
        assert "verify stage requires --summary-path" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    monkeypatch.setattr(backtest_report_script, "_load_json", lambda path: {"path": path})
    monkeypatch.setattr(
        backtest_report_script,
        "verify_summary_against_reference",
        lambda **kwargs: (["layer mismatch"], {"layer_1_metadata_and_metrics": False}),
    )

    try:
        backtest_report_script._run_verify_stage(
            args=argparse.Namespace(
                summary_path="summary.json",
                reference_json="reference.json",
                verify_tolerance=0.001,
            ),
            context={},
        )
    except ValueError as exc:
        assert str(exc) == "layer mismatch"
    else:
        raise AssertionError("expected ValueError")


def test_backtest_report_single_stage_backtest_and_verify_paths(monkeypatch):
    payloads = []
    monkeypatch.setattr(
        backtest_report_script,
        "load_stage_context",
        lambda path: {"run_name": "cw2-demo"},  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "runtime_lock",
        lambda **kwargs: _NullCtx(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_backtest_stage",
        lambda **kwargs: {  # noqa: ARG005
            "execution_mode": "new_backtest",
            "run_id": "run-1",
            "run_name": "cw2-demo",
        },
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_verify_stage",
        lambda **kwargs: {  # noqa: ARG005
            "run_id": "run-1",
            "verification": {
                "passed": True,
                "layer_status": {
                    "layer_1_metadata_and_metrics": True,
                    "layer_2_tearsheet": False,
                },
            },
        },
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_persist_context",
        lambda args, context: context,  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_context_snapshot",
        lambda *args, **kwargs: {"snapshot": "ok"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_metrics_snapshot",
        lambda *args, **kwargs: {"metrics": "ok"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_start",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_finish",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_stage_quality",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_emit_stage_event",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(backtest_report_script, "print_json", payloads.append)

    common_args = argparse.Namespace(
        context_path=None,
        runtime_lock_ttl_seconds=60,
        pipeline_name="cw2_pipeline",
        run_id=None,
        run_name="cw2-demo",
        report_name=None,
        summary_path=None,
        cw2_config="cw2.yaml",
    )
    assert (
        backtest_report_script._run_single_stage(
            stage="backtest", args=common_args, cw2_cfg={}, engine="engine"
        )
        == 0
    )
    assert (
        backtest_report_script._run_single_stage(
            stage="verify",
            args=argparse.Namespace(
                **(
                    {
                        **vars(common_args),
                        "summary_path": "summary.json",
                        "reference_json": "reference.json",
                        "verify_tolerance": 0.001,
                    }
                )
            ),
            cw2_cfg={},
            engine="engine",
        )
        == 0
    )

    assert payloads[0]["execution_mode"] == "new_backtest"
    assert payloads[1]["passed"] is True


def test_backtest_report_single_stage_report_payload_uses_artifact_count(monkeypatch):
    payloads = []
    monkeypatch.setattr(
        backtest_report_script,
        "load_stage_context",
        lambda path: {"run_id": "run-1"},  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "runtime_lock",
        lambda **kwargs: _NullCtx(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_report_stage",
        lambda **kwargs: {  # noqa: ARG005
            "run_id": "run-1",
            "report": {"report_id": "report-1", "artifact_count": 4},
        },
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_persist_context",
        lambda args, context: context,  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_context_snapshot",
        lambda *args, **kwargs: {"snapshot": "ok"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_metrics_snapshot",
        lambda *args, **kwargs: {"metrics": "ok"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_start",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_finish",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_stage_quality",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_emit_stage_event",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(backtest_report_script, "print_json", payloads.append)

    rc = backtest_report_script._run_single_stage(
        stage="report",
        args=argparse.Namespace(
            context_path=None,
            runtime_lock_ttl_seconds=60,
            pipeline_name="cw2_pipeline",
            run_id="run-1",
            run_name=None,
            report_name="cw2-report",
            summary_path=None,
            cw2_config="cw2.yaml",
        ),
        cw2_cfg={},
        engine="engine",
    )

    assert rc == 0
    assert payloads == [{"report_id": "report-1", "artifact_count": 4}]


def test_backtest_report_single_stage_failure_records_failed_state(monkeypatch):
    captured = {"quality": [], "finish": [], "events": []}
    monkeypatch.setattr(
        backtest_report_script,
        "load_stage_context",
        lambda path: {
            "run_id": "run-1",
            "report": {"report_id": "report-1"},
        },  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "runtime_lock",
        lambda **kwargs: _NullCtx(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_analysis_stage",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("analysis failed")),
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_context_snapshot",
        lambda *args, **kwargs: {"snapshot": "failed"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_metrics_snapshot",
        lambda *args, **kwargs: {"metrics": "failed"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_start",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_finish",
        lambda **kwargs: captured["finish"].append(kwargs),
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_stage_quality",
        lambda **kwargs: captured["quality"].append(kwargs),
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_emit_stage_event",
        lambda **kwargs: captured["events"].append(kwargs),
    )

    try:
        backtest_report_script._run_single_stage(
            stage="analysis",
            args=argparse.Namespace(
                context_path=None,
                runtime_lock_ttl_seconds=60,
                pipeline_name="cw2_pipeline",
                run_id="run-1",
                run_name=None,
                report_name=None,
                summary_path=None,
                cw2_config="cw2.yaml",
            ),
            cw2_cfg={},
            engine="engine",
        )
    except RuntimeError as exc:
        assert str(exc) == "analysis failed"
    else:
        raise AssertionError("expected RuntimeError")

    assert captured["quality"][0]["passed"] is False
    assert captured["finish"][0]["status"] == "failed"
    assert captured["events"][-1]["status"] == "failed"


def test_backtest_report_bundle_supports_verify_reference(monkeypatch):
    payloads = []
    monkeypatch.setattr(
        backtest_report_script,
        "load_stage_context",
        lambda path: {"run_name": "cw2-demo"},  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "runtime_lock",
        lambda **kwargs: _NullCtx(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_backtest_stage",
        lambda **kwargs: {
            **kwargs["context"],
            "execution_mode": "new_backtest",
            "run_id": "run-1",
            "run_name": "cw2-demo",
        },
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_analysis_stage",
        lambda **kwargs: {
            **kwargs["context"],
            "analysis": {"status": "ok"},
        },
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_report_stage",
        lambda **kwargs: {
            **kwargs["context"],
            "report": {"report_id": "report-1"},
        },
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_run_verify_stage",
        lambda **kwargs: {
            **kwargs["context"],
            "verification": {"passed": True},
        },
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_persist_context",
        lambda args, context: context,  # noqa: ARG005
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_context_snapshot",
        lambda *args, **kwargs: {"snapshot": "ok"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_runtime_metrics_snapshot",
        lambda *args, **kwargs: {"metrics": "ok"},
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_start",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_control_plane_finish",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_record_stage_quality",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "_emit_stage_event",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(backtest_report_script, "print_json", payloads.append)

    rc = backtest_report_script._run_bundle(
        args=argparse.Namespace(
            context_path=None,
            runtime_lock_ttl_seconds=60,
            pipeline_name="cw2_pipeline",
            run_id=None,
            run_name="cw2-demo",
            report_name=None,
            summary_path=None,
            verify_reference="true",
            cw2_config="cw2.yaml",
        ),
        cw2_cfg={},
        engine="engine",
    )

    assert rc == 0
    assert payloads == [
        {
            "execution_mode": "new_backtest",
            "run_id": "run-1",
            "run_name": "cw2-demo",
            "analysis": {"status": "ok"},
            "report": {"report_id": "report-1"},
            "verification": {"passed": True},
        }
    ]


def test_backtest_report_main_dispatches_single_stage(monkeypatch):
    captured = {}
    monkeypatch.setattr(backtest_report_script, "load_env_layers", lambda: None)
    monkeypatch.setattr(backtest_report_script, "load_yaml", lambda path: {"loaded": path})
    monkeypatch.setattr(backtest_report_script, "_optional_db_engine", lambda: "engine")
    monkeypatch.setattr(
        backtest_report_script,
        "_run_single_stage",
        lambda **kwargs: captured.update(kwargs) or 0,
    )
    monkeypatch.setattr(
        backtest_report_script,
        "build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: argparse.Namespace(stage="report", cw2_config="cw2.yaml")
                )
            },
        )(),
    )

    assert backtest_report_script.main() == 0
    assert captured["stage"] == "report"
    assert captured["cw2_cfg"] == {"loaded": "cw2.yaml"}
