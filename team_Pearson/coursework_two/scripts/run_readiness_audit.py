from __future__ import annotations

"""Scheduler-safe CW2 readiness audit wrapper with runtime telemetry."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.modules.ops import run_audit_from_config  # noqa: E402
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
    coerce_bool,
    default_cw1_config,
    default_cw2_config,
    load_env_layers,
    load_yaml,
    print_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the CW2 readiness audit under scheduler control."
    )
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument("--context-path", default=None)
    parser.add_argument("--pipeline-name", default="cw2_readiness_audit")
    parser.add_argument("--stage-name", default="cw2_readiness_audit")
    parser.add_argument(
        "--readiness-profile",
        default="strict",
        help=(
            "strict | backtest_preflight | post_backfill. "
            "Controls which readiness signals must pass for scheduler gating."
        ),
    )
    parser.add_argument(
        "--require-ready",
        default="true",
        help="true/false. Exit non-zero when readiness does not pass.",
    )
    return parser


def _semantic_status_ok(report: dict[str, object] | None) -> bool:
    status = str((report or {}).get("status") or "").lower()
    return status in {"", "ok", "warning", "not_applicable", "no_data"}


def _evaluate_readiness_gate(
    *,
    readiness: dict[str, object],
    semantic_checks: dict[str, object],
    profile: str,
) -> bool:
    normalized = str(profile or "strict").strip().lower()
    if normalized == "strict":
        return str(readiness.get("overall_status") or "").lower() == "ready"
    if normalized == "backtest_preflight":
        return (
            bool(readiness.get("core_sql_ready"))
            and bool(readiness.get("feature_pipeline_ready"))
            and bool(readiness.get("backtest_ready"))
            and _semantic_status_ok(
                dict(semantic_checks).get("portfolio_target_positions")  # type: ignore[arg-type]
            )
        )
    if normalized == "post_backfill":
        return (
            bool(readiness.get("core_sql_ready"))
            and bool(readiness.get("feature_pipeline_ready"))
            and _semantic_status_ok(
                dict(semantic_checks).get("portfolio_target_positions")  # type: ignore[arg-type]
            )
        )
    raise ValueError(f"Unsupported readiness profile: {profile!r}")


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()
    engine = get_db_engine()
    cw2_cfg = load_yaml(str(args.cw2_config))
    stage_name = str(args.stage_name or "cw2_readiness_audit").strip() or "cw2_readiness_audit"
    pipeline_name = (
        str(getattr(args, "pipeline_name", "") or "cw2_readiness_audit").strip()
        or "cw2_readiness_audit"
    )
    require_ready = coerce_bool(args.require_ready, default=True)
    readiness_profile = (
        str(getattr(args, "readiness_profile", "strict") or "strict").strip() or "strict"
    )
    context_token = (
        Path(str(args.context_path)).name
        if str(args.context_path or "").strip()
        else Path(str(args.cw2_config)).name
    )
    pipeline_execution_key = f"{pipeline_name}:{context_token}"
    execution_key = f"{pipeline_execution_key}:{stage_name}"
    started_at = datetime.now(timezone.utc)
    base_payload = {
        "pipeline_name": pipeline_name,
        "cw1_config": str(args.cw1_config),
        "cw2_config": str(args.cw2_config),
        "require_ready": require_ready,
        "readiness_profile": readiness_profile,
        "context_path": str(args.context_path or ""),
    }

    record_scheduler_pipeline_state(
        engine=engine,
        pipeline_name=pipeline_name,
        execution_key=pipeline_execution_key,
        status="running",
        stage_name=stage_name,
        started_at=started_at,
        context=base_payload,
    )
    record_scheduler_stage_state(
        engine=engine,
        pipeline_name=pipeline_name,
        stage_name=stage_name,
        execution_key=execution_key,
        stage_status="started",
        started_at=started_at,
        payload=base_payload,
    )

    emit_scheduler_stage_event(
        cw2_cfg,
        engine=engine,
        producer_component="cw2.scheduler.readiness_audit",
        stage_name=stage_name,
        stage_status="started",
        execution_key=execution_key,
        payload=base_payload,
    )

    audit_report = run_audit_from_config(
        cw1_config_path=str(args.cw1_config),
        cw2_config_path=str(args.cw2_config),
        db_engine=engine,
    )
    readiness = dict(audit_report.get("readiness") or {})
    semantic_checks = dict(audit_report.get("semantic_checks") or {})
    ready = _evaluate_readiness_gate(
        readiness=readiness,
        semantic_checks=semantic_checks,
        profile=readiness_profile,
    )
    status = "completed" if ready or not require_ready else "failed"
    row_count = len(dict(audit_report.get("sql_tables") or {}))
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage_name": stage_name,
        "require_ready": require_ready,
        "ready": ready,
        "readiness": readiness,
        "storage": audit_report.get("storage"),
        "semantic_checks": semantic_checks,
        "config_contract": audit_report.get("config_contract"),
        "readiness_profile": readiness_profile,
    }
    merged_context = merge_stage_context(str(args.context_path), {stage_name: payload})
    record_runtime_quality_snapshot(
        engine=engine,
        stage_name=stage_name,
        execution_key=execution_key,
        run_date=datetime.now(timezone.utc),
        passed=ready or not require_ready,
        failures=[] if ready or not require_ready else ["readiness_audit_not_ready"],
        warnings=list(readiness.get("warnings") or []),
        row_count=row_count,
        extra={
            "overall_status": readiness.get("overall_status"),
            "next_step": readiness.get("next_step"),
            "readiness_profile": readiness_profile,
        },
    )
    finished_at = datetime.now(timezone.utc)
    record_scheduler_stage_state(
        engine=engine,
        pipeline_name=pipeline_name,
        stage_name=stage_name,
        execution_key=execution_key,
        stage_status=status,
        started_at=started_at,
        completed_at=finished_at,
        payload=base_payload,
        result={
            "ready": ready,
            "overall_status": readiness.get("overall_status"),
            "next_step": readiness.get("next_step"),
            "readiness_profile": readiness_profile,
        },
        error_text=None if ready or not require_ready else "readiness_audit_not_ready",
    )
    record_scheduler_pipeline_state(
        engine=engine,
        pipeline_name=pipeline_name,
        execution_key=pipeline_execution_key,
        status="completed" if ready or not require_ready else "failed",
        stage_name=stage_name,
        started_at=started_at,
        completed_at=finished_at,
        context=build_runtime_context_snapshot(
            merged_context,
            context_path=str(args.context_path or ""),
            stage_name=stage_name,
            extra={"pipeline_name": pipeline_name},
        ),
        metrics=build_runtime_metrics_snapshot(
            {
                "ready": ready,
                "overall_status": readiness.get("overall_status"),
                "sql_table_count": row_count,
                "readiness_profile": readiness_profile,
            }
        ),
        error_text=None if ready or not require_ready else "readiness_audit_not_ready",
    )
    emit_scheduler_stage_event(
        cw2_cfg,
        engine=engine,
        producer_component="cw2.scheduler.readiness_audit",
        stage_name=stage_name,
        stage_status=status,
        execution_key=execution_key,
        severity="critical" if status == "failed" else "info",
        payload={
            "ready": ready,
            "require_ready": require_ready,
            "overall_status": readiness.get("overall_status"),
            "next_step": readiness.get("next_step"),
            "readiness_profile": readiness_profile,
        },
    )
    print_json(payload)
    return 0 if ready or not require_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
