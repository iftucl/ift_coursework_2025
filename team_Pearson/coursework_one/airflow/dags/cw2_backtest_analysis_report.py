from __future__ import annotations

from datetime import datetime, timedelta

try:
    from airflow.sdk import DAG
except ImportError:
    try:
        from airflow.models.dag import DAG
    except ImportError:
        from airflow import DAG
from airflow.models.param import Param
from airflow.operators.bash import BashOperator

CW2_ROOT = "/opt/airflow/team_Pearson/coursework_two"
_CONTEXT_PATH_TEMPLATE = (
    "/tmp/cw2_backtest_analysis_report_{{ ts_nodash | replace('+', '_') }}.json"
)
TRANSIENT_RETRY_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
}
VALIDATION_RETRY_ARGS = {"retries": 0}
CLEANUP_RETRY_ARGS = {
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="cw2_backtest_analysis_report",
    description=(
        "Scheduled CW2 research bundle with explicit readiness gate, "
        "stage-level backtest/analysis/report tasks, reference verification, "
        "and Kafka event audit."
    ),
    start_date=datetime(2026, 4, 1),
    schedule="30 11 1 * *",
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "team_pearson",
        "depends_on_past": False,
    },
    params={
        "run_id": Param("", type=["null", "string"]),
        "run_name": Param("", type=["null", "string"]),
        "transaction_cost_bps": Param("", type=["null", "string"]),
        "robustness_run_id": Param("", type=["null", "string"]),
        "report_name": Param("", type=["null", "string"]),
        "report_output_dir": Param("", type=["null", "string"]),
        "cw1_config": Param(
            "/opt/airflow/team_Pearson/coursework_one/config/conf.yaml", type="string"
        ),
        "cw2_config": Param(
            "/opt/airflow/team_Pearson/coursework_two/config/conf.yaml", type="string"
        ),
        "reference_json": Param(
            "/opt/airflow/team_Pearson/coursework_two/repro/reference_run_20260420.json",
            type="string",
        ),
        "verify_tolerance": Param("0.001", type="string"),
        "runtime_lock_ttl_seconds": Param("21600", type="string"),
        "kafka_audit_max_messages": Param("50", type="string"),
        "kafka_audit_poll_timeout_ms": Param("1000", type="string"),
        "kafka_audit_max_idle_polls": Param("2", type="string"),
    },
    tags=["cw2", "backtest", "analysis", "reporting", "airflow"],
) as dag:
    run_preflight_readiness_audit = BashOperator(
        task_id="run_preflight_readiness_audit",
        cwd=CW2_ROOT,
        bash_command=f"""
python scripts/run_readiness_audit.py \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --pipeline-name 'cw2_backtest_analysis_report' \
  --stage-name 'cw2_backtest_preflight_audit' \
  --readiness-profile 'backtest_preflight' \
  --require-ready 'true'
""",
        append_env=True,
        execution_timeout=timedelta(minutes=20),
        **VALIDATION_RETRY_ARGS,
    )

    run_backtest_stage = BashOperator(
        task_id="run_backtest_stage",
        cwd=CW2_ROOT,
        bash_command=f"""
python scripts/run_backtest_analysis_report.py \
  --stage backtest \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --pipeline-name 'cw2_backtest_analysis_report' \
  --runtime-lock-ttl-seconds '{{{{ params.runtime_lock_ttl_seconds }}}}' \
{{% if params.run_id %}}  --run-id '{{{{ params.run_id }}}}' \
{{% endif %}}{{% if params.run_name %}}  --run-name '{{{{ params.run_name }}}}' \
{{% endif %}}{{% if params.transaction_cost_bps %}}  --transaction-cost-bps '{{{{ params.transaction_cost_bps }}}}' \
{{% endif %}}
""",
        append_env=True,
        execution_timeout=timedelta(hours=3),
        **TRANSIENT_RETRY_ARGS,
    )

    run_analysis_stage = BashOperator(
        task_id="run_analysis_stage",
        cwd=CW2_ROOT,
        bash_command=f"""
python scripts/run_backtest_analysis_report.py \
  --stage analysis \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --pipeline-name 'cw2_backtest_analysis_report' \
  --runtime-lock-ttl-seconds '{{{{ params.runtime_lock_ttl_seconds }}}}' \
{{% if params.robustness_run_id %}}  --robustness-run-id '{{{{ params.robustness_run_id }}}}' \
{{% endif %}}
""",
        append_env=True,
        execution_timeout=timedelta(hours=2),
        **TRANSIENT_RETRY_ARGS,
    )

    run_report_stage = BashOperator(
        task_id="run_report_stage",
        cwd=CW2_ROOT,
        bash_command=f"""
python scripts/run_backtest_analysis_report.py \
  --stage report \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --pipeline-name 'cw2_backtest_analysis_report' \
  --runtime-lock-ttl-seconds '{{{{ params.runtime_lock_ttl_seconds }}}}' \
{{% if params.report_name %}}  --report-name '{{{{ params.report_name }}}}' \
{{% endif %}}{{% if params.report_output_dir %}}  --report-output-dir '{{{{ params.report_output_dir }}}}' \
{{% endif %}}
""",
        append_env=True,
        execution_timeout=timedelta(hours=1),
        **TRANSIENT_RETRY_ARGS,
    )

    verify_reference_contract = BashOperator(
        task_id="verify_reference_contract",
        cwd=CW2_ROOT,
        bash_command=f"""
python scripts/run_backtest_analysis_report.py \
  --stage verify \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --pipeline-name 'cw2_backtest_analysis_report' \
  --reference-json '{{{{ params.reference_json }}}}' \
  --verify-tolerance '{{{{ params.verify_tolerance }}}}' \
  --runtime-lock-ttl-seconds '{{{{ params.runtime_lock_ttl_seconds }}}}'
""",
        append_env=True,
        execution_timeout=timedelta(minutes=20),
        **VALIDATION_RETRY_ARGS,
    )

    audit_kafka_event_bus = BashOperator(
        task_id="audit_kafka_event_bus",
        cwd=CW2_ROOT,
        bash_command=f"""
python scripts/run_kafka_event_audit.py \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --pipeline-name 'cw2_backtest_analysis_report' \
  --stage-name 'audit_kafka_event_bus' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --max-messages '{{{{ params.kafka_audit_max_messages }}}}' \
  --poll-timeout-ms '{{{{ params.kafka_audit_poll_timeout_ms }}}}' \
  --max-idle-polls '{{{{ params.kafka_audit_max_idle_polls }}}}'
""",
        append_env=True,
        execution_timeout=timedelta(minutes=15),
        trigger_rule="all_done",
        **TRANSIENT_RETRY_ARGS,
    )

    cleanup_stage_context = BashOperator(
        task_id="cleanup_stage_context",
        cwd=CW2_ROOT,
        bash_command=f"rm -f '{_CONTEXT_PATH_TEMPLATE}'",
        append_env=True,
        execution_timeout=timedelta(minutes=5),
        trigger_rule="all_done",
        **CLEANUP_RETRY_ARGS,
    )

    (
        run_preflight_readiness_audit
        >> run_backtest_stage
        >> run_analysis_stage
        >> run_report_stage
        >> verify_reference_contract
        >> audit_kafka_event_bus
        >> cleanup_stage_context
    )
