from __future__ import annotations

"""Scheduler-safe wrapper for the CW2 Kafka end-to-end audit consumer."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.modules.ops import run_kafka_event_audit_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.ops.runtime_control import (  # noqa: E402
    build_runtime_context_snapshot,
    build_runtime_metrics_snapshot,
    emit_scheduler_stage_event,
    merge_stage_context,
    record_runtime_quality_snapshot,
    record_scheduler_pipeline_state,
    record_scheduler_stage_state,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    default_cw1_config,
    default_cw2_config,
    load_env_layers,
    load_yaml,
    print_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CW2 Kafka audit consumer under scheduler control."
    )
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument("--pipeline-name", default="cw2_kafka_event_audit")
    parser.add_argument("--stage-name", default="audit_kafka_event_bus")
    parser.add_argument("--context-path", default=None)
    parser.add_argument("--max-messages", type=int, default=None)
    parser.add_argument("--poll-timeout-ms", type=int, default=None)
    parser.add_argument("--max-idle-polls", type=int, default=None)
    return parser


def _is_nonfatal_audit_status(status: object) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in {
        "",
        "ok",
        "warning",
        "skipped",
        "disabled",
        "audit_disabled",
        "no_recent_activity",
    }


def run_audit_cycle(
    *,
    engine: object,
    cw1_config: str,
    cw2_config: str,
    pipeline_name: str,
    stage_name: str,
    context_path: str | None = None,
    max_messages: int | None = None,
    poll_timeout_ms: int | None = None,
    max_idle_polls: int | None = None,
    audit_overrides: dict[str, object] | None = None,
    producer_component: str = "cw2.scheduler.kafka_event_audit",
) -> tuple[int, dict[str, object]]:
    cw2_cfg = load_yaml(str(cw2_config))
    pipeline_name = str(pipeline_name or "cw2_kafka_event_audit").strip() or "cw2_kafka_event_audit"
    stage_name = str(stage_name or "audit_kafka_event_bus").strip() or "audit_kafka_event_bus"
    context_token = (
        Path(str(context_path)).name
        if str(context_path or "").strip()
        else Path(str(cw2_config)).name
    )
    pipeline_execution_key = f"{pipeline_name}:{context_token}"
    execution_key = f"{pipeline_execution_key}:{stage_name}"
    started_at = datetime.now(timezone.utc)
    payload = {
        "pipeline_name": pipeline_name,
        "context_path": str(context_path or ""),
        "max_messages": max_messages,
        "poll_timeout_ms": poll_timeout_ms,
        "max_idle_polls": max_idle_polls,
        "audit_overrides": dict(audit_overrides or {}),
    }
    record_scheduler_pipeline_state(
        engine=engine,
        pipeline_name=pipeline_name,
        execution_key=pipeline_execution_key,
        status="running",
        stage_name=stage_name,
        started_at=started_at,
        context=payload,
    )
    record_scheduler_stage_state(
        engine=engine,
        pipeline_name=pipeline_name,
        stage_name=stage_name,
        execution_key=execution_key,
        stage_status="started",
        started_at=started_at,
        payload=payload,
    )
    emit_scheduler_stage_event(
        cw2_cfg,
        engine=engine,
        producer_component=producer_component,
        stage_name=stage_name,
        stage_status="started",
        execution_key=execution_key,
        payload=payload,
    )
    finished_at = datetime.now(timezone.utc)
    summary: dict[str, object]
    error_text: str | None = None
    try:
        summary = run_kafka_event_audit_from_config(
            cw1_config_path=str(Path(cw1_config).resolve()),
            cw2_config_path=str(Path(cw2_config).resolve()),
            db_engine=engine,
            max_messages=max_messages,
            poll_timeout_ms=poll_timeout_ms,
            max_idle_polls=max_idle_polls,
            audit_overrides=audit_overrides,
        )
        exit_code = 0 if _is_nonfatal_audit_status(summary.get("status")) else 1
    except Exception as exc:  # pragma: no cover - runtime service dependent
        summary = {
            "status": "error",
            "reason": repr(exc),
            "consumer_group": "team_pearson_cw2_audit",
            "consumed_count": 0,
            "processed_count": 0,
            "failed_count": 0,
            "dead_letter_count": 0,
            "committed_count": 0,
            "lag_snapshot_count": 0,
        }
        exit_code = 1
        error_text = repr(exc)
    merged_context = merge_stage_context(str(context_path), {stage_name: summary})
    stage_status = "completed" if exit_code == 0 else "failed"
    record_runtime_quality_snapshot(
        engine=engine,
        stage_name=stage_name,
        execution_key=execution_key,
        run_date=finished_at,
        passed=exit_code == 0,
        failures=(
            []
            if exit_code == 0
            else [f"kafka_event_audit_{str(summary.get('status') or 'failed').lower()}"]
        ),
        row_count=int(summary.get("processed_count") or 0),
        warnings=(
            []
            if str(summary.get("status") or "").lower() != "warning"
            else [str(summary.get("reason") or "kafka_event_audit_warning")]
        ),
        extra={"summary": summary, "return_code": exit_code},
    )
    record_scheduler_stage_state(
        engine=engine,
        pipeline_name=pipeline_name,
        stage_name=stage_name,
        execution_key=execution_key,
        stage_status=stage_status,
        started_at=started_at,
        completed_at=finished_at,
        payload=payload,
        result=summary,
        error_text=error_text if exit_code != 0 else None,
    )
    record_scheduler_pipeline_state(
        engine=engine,
        pipeline_name=pipeline_name,
        execution_key=pipeline_execution_key,
        status="completed" if exit_code == 0 else "failed",
        stage_name=stage_name,
        started_at=started_at,
        completed_at=finished_at,
        context=build_runtime_context_snapshot(
            merged_context,
            context_path=str(context_path or ""),
            stage_name=stage_name,
            extra={"pipeline_name": pipeline_name},
        ),
        metrics=build_runtime_metrics_snapshot(
            summary,
            extra={"stage_status": stage_status, "return_code": exit_code},
        ),
        error_text=error_text if exit_code != 0 else None,
    )
    emit_scheduler_stage_event(
        cw2_cfg,
        engine=engine,
        producer_component=producer_component,
        stage_name=stage_name,
        stage_status=stage_status,
        execution_key=execution_key,
        severity=(
            "critical"
            if exit_code != 0
            else ("warning" if str(summary.get("status") or "").lower() == "warning" else "info")
        ),
        payload={**payload, "return_code": exit_code, "summary": summary},
    )
    return exit_code, summary


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()
    engine = get_db_engine()
    exit_code, summary = run_audit_cycle(
        engine=engine,
        cw1_config=str(args.cw1_config),
        cw2_config=str(args.cw2_config),
        pipeline_name=str(args.pipeline_name or "cw2_kafka_event_audit"),
        stage_name=str(args.stage_name or "audit_kafka_event_bus"),
        context_path=str(args.context_path or ""),
        max_messages=args.max_messages,
        poll_timeout_ms=args.poll_timeout_ms,
        max_idle_polls=args.max_idle_polls,
    )
    print_json(summary)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
