from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _require_real_airflow():
    try:
        from airflow.models.dag import DAG as _dag  # noqa: F401
        return
    except Exception:
        pass
    try:
        from airflow.sdk import DAG as _sdk_dag  # noqa: F401
        return
    except Exception:
        pass
    pytest.skip("Apache Airflow is not installed in the current test environment.")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schedule_text(dag) -> str:
    return str(
        getattr(dag, "schedule_interval", None)
        or getattr(getattr(dag, "timetable", None), "summary", None)
    )


def test_cw1_pipeline_and_docs_dag_imports():
    _require_real_airflow()
    module = _load_module(
        Path("team_Pearson/coursework_one/airflow/dags/cw1_pipeline_and_docs.py"),
        "cw1_pipeline_and_docs_test",
    )
    task_ids = {task.task_id for task in module.dag.tasks}
    assert "run_daily_pipeline" in task_ids
    assert "validate_curated_data" in task_ids
    assert "build_sphinx_docs" in task_ids
    assert "check_cw2_operate_rebalance_anchor" in task_ids
    assert "run_cw2_operate_on_rebalance_anchor" in task_ids


def test_cw2_manual_dags_import():
    _require_real_airflow()
    backtest_module = _load_module(
        Path("team_Pearson/coursework_one/airflow/dags/cw2_backtest_analysis_report.py"),
        "cw2_backtest_analysis_report_test",
    )
    backfill_module = _load_module(
        Path("team_Pearson/coursework_one/airflow/dags/cw2_monthly_snapshot_backfill.py"),
        "cw2_monthly_snapshot_backfill_test",
    )
    assert {task.task_id for task in backtest_module.dag.tasks} == {
        "run_preflight_readiness_audit",
        "run_backtest_stage",
        "run_analysis_stage",
        "run_report_stage",
        "verify_reference_contract",
        "audit_kafka_event_bus",
        "cleanup_stage_context",
    }
    assert {task.task_id for task in backfill_module.dag.tasks} == {
        "backfill_monthly_snapshots",
        "run_post_backfill_readiness_audit",
        "audit_kafka_event_bus",
        "cleanup_stage_context",
    }
    assert _schedule_text(backtest_module.dag) == "30 11 1 * *"
    assert _schedule_text(backfill_module.dag) == "30 9 1 * *"
    assert backtest_module.dag.max_active_runs == 1
    assert backfill_module.dag.max_active_runs == 1
    assert backtest_module.audit_kafka_event_bus.trigger_rule == "all_done"
    assert backfill_module.audit_kafka_event_bus.trigger_rule == "all_done"
    assert backtest_module.cleanup_stage_context.trigger_rule == "all_done"
    assert backfill_module.cleanup_stage_context.trigger_rule == "all_done"
    assert "{{ params.cw1_config }}" in backtest_module.audit_kafka_event_bus.bash_command
    assert "{{ params.cw2_config }}" in backfill_module.audit_kafka_event_bus.bash_command
