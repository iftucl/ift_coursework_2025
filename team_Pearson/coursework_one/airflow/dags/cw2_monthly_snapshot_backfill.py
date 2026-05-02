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
    "/tmp/cw2_monthly_snapshot_backfill_{{ ts_nodash | replace('+', '_') }}.json"
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
    dag_id="cw2_monthly_snapshot_backfill",
    description=(
        "Scheduled CW2 month-end snapshot maintenance with explicit post-backfill "
        "readiness validation and Kafka event audit."
    ),
    start_date=datetime(2026, 4, 1),
    schedule="30 9 1 * *",
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "team_pearson",
        "depends_on_past": False,
    },
    params={
        "start_date": Param("", type=["null", "string"]),
        "end_date": Param("", type=["null", "string"]),
        "company_limit": Param("", type=["null", "string"]),
        "skip_existing": Param("true", type="string"),
        "cw1_config": Param(
            "/opt/airflow/team_Pearson/coursework_one/config/conf.yaml", type="string"
        ),
        "cw2_config": Param(
            "/opt/airflow/team_Pearson/coursework_two/config/conf.yaml", type="string"
        ),
        "runtime_lock_ttl_seconds": Param("21600", type="string"),
        "kafka_audit_max_messages": Param("25", type="string"),
        "kafka_audit_poll_timeout_ms": Param("1000", type="string"),
        "kafka_audit_max_idle_polls": Param("2", type="string"),
    },
    tags=["cw2", "backfill", "airflow"],
) as dag:
    backfill_monthly_snapshots = BashOperator(
        task_id="backfill_monthly_snapshots",
        cwd=CW2_ROOT,
        bash_command=f"""
{{% set effective_start_date = params.start_date if params.start_date else macros.ds_add(ds, -40) %}}
{{% set effective_end_date = params.end_date if params.end_date else ds %}}
python scripts/backfill_monthly_snapshots.py \
  --start-date '{{{{ effective_start_date }}}}' \
  --end-date '{{{{ effective_end_date }}}}' \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --skip-existing '{{{{ params.skip_existing }}}}' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --pipeline-name 'cw2_monthly_snapshot_backfill' \
  --runtime-lock-ttl-seconds '{{{{ params.runtime_lock_ttl_seconds }}}}' \
{{% if params.company_limit %}}  --company-limit '{{{{ params.company_limit }}}}' \
{{% endif %}}
""",
        append_env=True,
        execution_timeout=timedelta(hours=3),
        **TRANSIENT_RETRY_ARGS,
    )

    run_post_backfill_readiness_audit = BashOperator(
        task_id="run_post_backfill_readiness_audit",
        cwd=CW2_ROOT,
        bash_command=f"""
python scripts/run_readiness_audit.py \
  --cw1-config '{{{{ params.cw1_config }}}}' \
  --cw2-config '{{{{ params.cw2_config }}}}' \
  --context-path '{_CONTEXT_PATH_TEMPLATE}' \
  --pipeline-name 'cw2_monthly_snapshot_backfill' \
  --stage-name 'cw2_post_backfill_audit' \
  --readiness-profile 'post_backfill' \
  --require-ready 'true'
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
  --pipeline-name 'cw2_monthly_snapshot_backfill' \
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
        backfill_monthly_snapshots
        >> run_post_backfill_readiness_audit
        >> audit_kafka_event_bus
        >> cleanup_stage_context
    )
