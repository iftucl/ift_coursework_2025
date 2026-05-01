from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from airflow.sdk import DAG
except ImportError:
    try:
        from airflow.models.dag import DAG
    except ImportError:
        from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import ShortCircuitOperator

def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "team_Pearson" / "coursework_two").exists():
            return candidate
    return Path("/opt/airflow")


REPO_ROOT = _resolve_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    is_rebalance_trading_day,
)

CW1_ROOT = "/opt/airflow/team_Pearson/coursework_one"
CW2_ROOT = "/opt/airflow/team_Pearson/coursework_two"
CW2_CONFIG = "/opt/airflow/team_Pearson/coursework_two/config/conf.yaml"
TRANSIENT_RETRY_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
}
VALIDATION_RETRY_ARGS = {"retries": 0}


def _should_run_cw2_operate(*, run_date: str, cw2_config_path: str = CW2_CONFIG) -> bool:
    return is_rebalance_trading_day(
        run_date=date.fromisoformat(str(run_date)),
        cw2_config_path=str(cw2_config_path),
    )

with DAG(
    dag_id="cw1_pipeline_and_docs",
    description="Daily CW1 pipeline run plus Sphinx docs, CW2 update decision, and configured-rebalance-anchor CW2 operate orchestration.",
    start_date=datetime(2026, 4, 1),
    schedule="0 6 * * *",
    catchup=False,
    default_args={"owner": "team_pearson"},
    tags=["cw1", "cw2", "team_pearson", "airflow"],
) as dag:
    run_pipeline = BashOperator(
        task_id="run_daily_pipeline",
        cwd=CW1_ROOT,
        bash_command=(
            "python scripts/run_scheduled_pipeline.py "
            "--run-date {{ ds }} "
            "--only daily "
            "--backfill-years 5 "
            "--company-limit 0"
        ),
        append_env=True,
        **TRANSIENT_RETRY_ARGS,
    )

    validate_data = BashOperator(
        task_id="validate_curated_data",
        cwd=CW1_ROOT,
        bash_command=(
            "python scripts/validate_pipeline_data.py "
            "--tolerance 1e-6 "
            "--start-date {{ macros.ds_add(ds, -40) }} "
            "--end-date {{ ds }}"
        ),
        append_env=True,
        **VALIDATION_RETRY_ARGS,
    )

    build_docs = BashOperator(
        task_id="build_sphinx_docs",
        cwd=CW1_ROOT,
        bash_command="python scripts/build_sphinx_docs.py --clean",
        append_env=True,
        **TRANSIENT_RETRY_ARGS,
    )

    run_cw2_update_decision = BashOperator(
        task_id="run_cw2_update_decision",
        cwd=CW2_ROOT,
        bash_command=(
            "python scripts/run_update_decision.py "
            "--run-date {{ ds }}"
        ),
        append_env=True,
        **TRANSIENT_RETRY_ARGS,
    )

    check_cw2_operate_rebalance_anchor = ShortCircuitOperator(
        task_id="check_cw2_operate_rebalance_anchor",
        python_callable=_should_run_cw2_operate,
        op_kwargs={
            "run_date": "{{ ds }}",
            "cw2_config_path": CW2_CONFIG,
        },
        **VALIDATION_RETRY_ARGS,
    )

    run_cw2_operate = BashOperator(
        task_id="run_cw2_operate_on_rebalance_anchor",
        cwd=CW2_ROOT,
        bash_command=(
            "python scripts/run_operated_flow.py "
            "--run-date {{ ds }} "
            "--no-require-rebalance-anchor"
        ),
        append_env=True,
        **TRANSIENT_RETRY_ARGS,
    )

    run_pipeline >> validate_data
    validate_data >> build_docs
    validate_data >> run_cw2_update_decision
    run_cw2_update_decision >> check_cw2_operate_rebalance_anchor >> run_cw2_operate
