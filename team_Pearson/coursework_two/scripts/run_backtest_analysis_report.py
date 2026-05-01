from __future__ import annotations

"""Scheduler-safe CW2 backtest -> analysis -> report orchestration."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.modules.analysis import run_analysis_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.backtest import run_backtest_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.ops.runtime_control import (  # noqa: E402
    build_runtime_context_snapshot,
    build_runtime_metrics_snapshot,
    emit_scheduler_stage_event,
    load_stage_context,
    merge_stage_context,
    record_runtime_quality_snapshot,
    record_scheduler_pipeline_state,
    record_scheduler_stage_state,
    runtime_lock,
)
from team_Pearson.coursework_two.modules.reporting import (  # noqa: E402
    generate_backtest_report_from_config,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    coerce_bool,
    coerce_optional_float,
    coerce_optional_str,
    default_cw1_config,
    default_cw2_config,
    load_env_layers,
    load_yaml,
    print_json,
)
from team_Pearson.coursework_two.scripts.verify_reference_metrics import (  # noqa: E402
    DEFAULT_REFERENCE,
    verify_summary_against_reference,
)

_DEFAULT_LOCK_TTL_SECONDS = 6 * 60 * 60


def build_parser() -> argparse.ArgumentParser:
    """Construct the parser for staged or bundled backtest/report orchestration."""
    parser = argparse.ArgumentParser(
        description="Run the CW2 backtest -> analysis -> report bundle."
    )
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument(
        "--stage",
        default="bundle",
        choices=("bundle", "backtest", "analysis", "report", "verify"),
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--transaction-cost-bps", default=None)
    parser.add_argument("--robustness-run-id", default=None)
    parser.add_argument("--report-name", default=None)
    parser.add_argument("--report-output-dir", default=None)
    parser.add_argument("--summary-path", default=None)
    parser.add_argument("--context-path", default=None)
    parser.add_argument("--pipeline-name", default="cw2_backtest_analysis_report")
    parser.add_argument("--reference-json", default=str(DEFAULT_REFERENCE))
    parser.add_argument("--verify-tolerance", type=float, default=0.001)
    parser.add_argument(
        "--verify-reference",
        default="false",
        help="true/false. Only used in bundle mode.",
    )
    parser.add_argument(
        "--runtime-lock-ttl-seconds",
        type=int,
        default=_DEFAULT_LOCK_TTL_SECONDS,
    )
    return parser


def _default_run_name() -> str:
    """Generate a timestamped fallback run name for new backtests."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"cw2_airflow_backtest_{ts}"


def _optional_db_engine():
    """Return a DB engine when available, otherwise ``None`` for degraded mode."""
    try:
        return get_db_engine()
    except Exception:
        return None


def _load_json(path: str) -> Dict[str, Any]:
    """Load one JSON file into a dictionary."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolved_run_id(args: argparse.Namespace, context: Dict[str, Any]) -> str | None:
    """Resolve the active ``run_id`` from CLI args or persisted stage context."""
    return coerce_optional_str(args.run_id) or coerce_optional_str(context.get("run_id"))


def _resolved_run_name(args: argparse.Namespace, context: Dict[str, Any]) -> str | None:
    """Resolve the active run name from CLI args or persisted stage context."""
    return coerce_optional_str(args.run_name) or coerce_optional_str(context.get("run_name"))


def _resolved_report_json_path(args: argparse.Namespace, context: Dict[str, Any]) -> str | None:
    """Resolve the report summary JSON path from args or saved context."""
    explicit = coerce_optional_str(args.summary_path)
    if explicit is not None:
        return explicit
    report = dict(context.get("report") or {})
    return coerce_optional_str(report.get("json_path"))


def _pipeline_name(args: argparse.Namespace) -> str:
    """Resolve the logical pipeline name used in control-plane records."""
    return (
        coerce_optional_str(getattr(args, "pipeline_name", None)) or "cw2_backtest_analysis_report"
    )


def _pipeline_execution_key(args: argparse.Namespace, context: Dict[str, Any]) -> str:
    """Build a stable pipeline execution key from context path, run, or report identity."""
    parts = [_pipeline_name(args)]
    context_path = coerce_optional_str(args.context_path)
    if context_path:
        parts.append(Path(context_path).name)
        return ":".join(parts)
    run_identity = _resolved_run_id(args, context) or _resolved_run_name(args, context)
    if run_identity:
        parts.append(run_identity)
    report_identity = coerce_optional_str(args.report_name) or coerce_optional_str(
        dict(context.get("report") or {}).get("report_name")
    )
    if report_identity:
        parts.append(report_identity)
    if len(parts) == 1:
        parts.append(Path(str(args.cw2_config)).stem)
    return ":".join(parts)


def _execution_key(
    *,
    stage: str,
    args: argparse.Namespace,
    context: Dict[str, Any],
) -> str:
    """Build the stage-specific execution key used by locks and SQL trace rows."""
    return f"{_pipeline_execution_key(args, context)}:{stage}"


def _stage_order(stage: str) -> int:
    """Return the numeric ordering used by control-plane stage rows."""
    return {
        "backtest": 10,
        "analysis": 20,
        "report": 30,
        "verify": 40,
        "bundle": 0,
    }.get(stage, 999)


def _stage_dataset_name(stage: str) -> str:
    """Return the quality-snapshot dataset label for one scheduler stage."""
    return f"cw2_scheduler_{stage}"


def _emit_stage_event(
    *,
    cw2_cfg: Dict[str, Any],
    engine,
    stage: str,
    status: str,
    execution_key: str,
    payload: Dict[str, Any],
    severity: str = "info",
) -> None:
    """Publish one structured scheduler stage lifecycle event."""
    emit_scheduler_stage_event(
        cw2_cfg,
        engine=engine,
        producer_component="cw2.scheduler.backtest_analysis_report",
        stage_name=stage,
        stage_status=status,
        execution_key=execution_key,
        severity=severity,
        payload=payload,
    )


def _record_stage_quality(
    *,
    engine,
    stage: str,
    execution_key: str,
    passed: bool,
    failures: list[str] | None = None,
    warnings: list[str] | None = None,
    row_count: int | None = None,
    run_id: str | None = None,
    extra: Dict[str, Any] | None = None,
) -> None:
    """Persist one quality snapshot for the current scheduler stage."""
    record_runtime_quality_snapshot(
        engine=engine,
        stage_name=_stage_dataset_name(stage),
        execution_key=execution_key,
        run_date=datetime.now(timezone.utc),
        passed=passed,
        failures=failures,
        warnings=warnings,
        row_count=row_count,
        run_id=run_id,
        extra=extra,
    )


def _record_control_plane_start(
    *,
    engine,
    pipeline_name: str,
    pipeline_execution_key: str,
    stage: str,
    execution_key: str,
    lock_name: str,
    lock_handle,
    run_id: str | None,
    payload: Dict[str, Any],
) -> None:
    """Persist SQL control-plane rows marking the start of one stage execution."""
    record_scheduler_pipeline_state(
        engine=engine,
        pipeline_name=pipeline_name,
        execution_key=pipeline_execution_key,
        status="running",
        stage_name=stage,
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        context=build_runtime_context_snapshot(payload, stage_name=stage),
        metrics={"stage_order": _stage_order(stage)},
    )
    record_scheduler_stage_state(
        engine=engine,
        pipeline_name=pipeline_name,
        stage_name=stage,
        execution_key=execution_key,
        stage_status="started",
        stage_order=_stage_order(stage),
        run_id=run_id,
        lock_handle=lock_handle,
        lock_name=lock_name,
        idempotency_key=f"{pipeline_name}:{execution_key}:started",
        started_at=datetime.now(timezone.utc),
        payload=payload,
    )


def _record_control_plane_finish(
    *,
    engine,
    pipeline_name: str,
    pipeline_execution_key: str,
    stage: str,
    execution_key: str,
    run_id: str | None,
    report_id: str | None,
    status: str,
    result_payload: Dict[str, Any] | None = None,
    context_snapshot: Dict[str, Any] | None = None,
    metrics_snapshot: Dict[str, Any] | None = None,
    error_text: str | None = None,
) -> None:
    """Persist SQL control-plane rows marking stage completion or failure."""
    finished_at = datetime.now(timezone.utc)
    record_scheduler_stage_state(
        engine=engine,
        pipeline_name=pipeline_name,
        stage_name=stage,
        execution_key=execution_key,
        stage_status=status,
        stage_order=_stage_order(stage),
        run_id=run_id,
        report_id=report_id,
        completed_at=finished_at,
        result=result_payload or {},
        error_text=error_text,
        idempotency_key=f"{pipeline_name}:{execution_key}:{status}",
    )
    record_scheduler_pipeline_state(
        engine=engine,
        pipeline_name=pipeline_name,
        execution_key=pipeline_execution_key,
        status="completed" if status == "completed" else "failed",
        stage_name=stage,
        run_id=run_id,
        report_id=report_id,
        completed_at=finished_at,
        context=context_snapshot or {"stage_name": stage},
        metrics=metrics_snapshot or {"result_keys": sorted((result_payload or {}).keys())},
        error_text=error_text,
    )


def _run_backtest_stage(
    *,
    args: argparse.Namespace,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute or reuse the backtest stage and merge its run identity into context."""
    existing_run_id = _resolved_run_id(args, context)
    config_override = None
    transaction_cost_bps = coerce_optional_float(args.transaction_cost_bps)
    if transaction_cost_bps is not None:
        config_override = {
            "backtest": {
                "transaction_cost_bps": transaction_cost_bps,
                "intraday_triggers": {
                    "transaction_cost_bps": transaction_cost_bps,
                },
            }
        }

    if existing_run_id is not None:
        if config_override is not None:
            raise ValueError(
                "--transaction-cost-bps cannot be used together with --run-id because "
                "the backtest already exists."
            )
        run_id = existing_run_id
        run_name = _resolved_run_name(args, context)
        execution_mode = "existing_run"
    else:
        run_name = _resolved_run_name(args, context) or _default_run_name()
        run_id = run_backtest_from_config(
            run_name=run_name,
            config_path=str(args.cw2_config),
            config_override=config_override,
        )
        execution_mode = "new_backtest"

    return {
        **context,
        "execution_mode": execution_mode,
        "run_id": run_id,
        "run_name": run_name,
    }


def _run_analysis_stage(
    *,
    args: argparse.Namespace,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute the analysis stage for the current backtest run."""
    run_id = _resolved_run_id(args, context)
    if run_id is None:
        raise ValueError("analysis stage requires run_id or a context file with run_id")
    analysis_result = run_analysis_from_config(
        run_id=run_id,
        config_path=str(args.cw2_config),
        robustness_run_id_25bps=coerce_optional_str(args.robustness_run_id),
    )
    return {
        **context,
        "run_id": run_id,
        "analysis": analysis_result,
    }


def _run_report_stage(
    *,
    args: argparse.Namespace,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute the reporting stage for the current backtest run."""
    run_id = _resolved_run_id(args, context)
    if run_id is None:
        raise ValueError("report stage requires run_id or a context file with run_id")
    report_result = generate_backtest_report_from_config(
        run_id=run_id,
        config_path=str(args.cw2_config),
        report_name=coerce_optional_str(args.report_name),
        output_dir=coerce_optional_str(args.report_output_dir),
    )
    return {
        **context,
        "run_id": run_id,
        "report": report_result,
    }


def _run_verify_stage(
    *,
    args: argparse.Namespace,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Verify the generated report summary against the tracked reference contract."""
    summary_path = _resolved_report_json_path(args, context)
    if summary_path is None:
        raise ValueError(
            "verify stage requires --summary-path or a context file with report.json_path"
        )
    summary = _load_json(summary_path)
    reference = _load_json(str(args.reference_json))
    failures, layer_status = verify_summary_against_reference(
        summary=summary,
        reference=reference,
        tolerance=float(args.verify_tolerance),
    )
    verification = {
        "passed": not failures,
        "summary_path": summary_path,
        "reference_json": str(args.reference_json),
        "tolerance": float(args.verify_tolerance),
        "layer_status": layer_status,
        "failures": failures,
    }
    if failures:
        raise ValueError("; ".join(failures))
    return {
        **context,
        "verification": verification,
    }


def _persist_context(args: argparse.Namespace, context: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the latest stage output into the optional persisted context file."""
    return merge_stage_context(coerce_optional_str(args.context_path), context)


def _run_single_stage(
    *,
    stage: str,
    args: argparse.Namespace,
    cw2_cfg: Dict[str, Any],
    engine,
) -> int:
    """Run exactly one named scheduler stage with locks, quality, and events."""
    context = load_stage_context(coerce_optional_str(args.context_path))
    pipeline_name = _pipeline_name(args)
    pipeline_execution_key = _pipeline_execution_key(args, context)
    execution_key = _execution_key(stage=stage, args=args, context=context)
    lock_name = f"cw2:{stage}:{execution_key}"

    with runtime_lock(
        lock_name=lock_name,
        ttl_seconds=int(args.runtime_lock_ttl_seconds),
        raise_on_locked=True,
    ) as lock_handle:
        start_payload = {
            "pipeline_name": pipeline_name,
            "pipeline_execution_key": pipeline_execution_key,
            "context_path": coerce_optional_str(args.context_path),
            "lock_name": lock_name,
            "run_id": _resolved_run_id(args, context),
        }
        _record_control_plane_start(
            engine=engine,
            pipeline_name=pipeline_name,
            pipeline_execution_key=pipeline_execution_key,
            stage=stage,
            execution_key=execution_key,
            lock_name=lock_name,
            lock_handle=lock_handle,
            run_id=_resolved_run_id(args, context),
            payload=start_payload,
        )
        _emit_stage_event(
            cw2_cfg=cw2_cfg,
            engine=engine,
            stage=stage,
            status="started",
            execution_key=execution_key,
            payload=start_payload,
        )
        try:
            if stage == "backtest":
                updated = _run_backtest_stage(args=args, context=context)
                result_payload = {
                    "execution_mode": updated.get("execution_mode"),
                    "run_id": updated.get("run_id"),
                    "run_name": updated.get("run_name"),
                }
                row_count = 1
                warnings: list[str] = []
            elif stage == "analysis":
                updated = _run_analysis_stage(args=args, context=context)
                result_payload = dict(updated.get("analysis") or {})
                row_count = len(result_payload)
                warnings = []
            elif stage == "report":
                updated = _run_report_stage(args=args, context=context)
                result_payload = dict(updated.get("report") or {})
                row_count = int(result_payload.get("artifact_count") or 0)
                warnings = []
            elif stage == "verify":
                updated = _run_verify_stage(args=args, context=context)
                result_payload = dict(updated.get("verification") or {})
                row_count = sum(
                    1 for passed in (result_payload.get("layer_status") or {}).values() if passed
                )
                warnings = []
            else:  # pragma: no cover - parser choices guard this
                raise ValueError(f"Unsupported stage: {stage}")

            merged = _persist_context(args, updated)
            report_id = coerce_optional_str(dict(merged.get("report") or {}).get("report_id"))
            context_snapshot = build_runtime_context_snapshot(
                merged,
                context_path=coerce_optional_str(args.context_path),
                stage_name=stage,
                extra={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                },
            )
            metrics_snapshot = build_runtime_metrics_snapshot(
                result_payload,
                extra={
                    "stage_order": _stage_order(stage),
                    "stage_status": "completed",
                },
            )
            _record_stage_quality(
                engine=engine,
                stage=stage,
                execution_key=execution_key,
                passed=True,
                warnings=warnings,
                row_count=row_count,
                run_id=_resolved_run_id(args, merged),
                extra={"result_keys": sorted(result_payload.keys())},
            )
            _record_control_plane_finish(
                engine=engine,
                pipeline_name=pipeline_name,
                pipeline_execution_key=pipeline_execution_key,
                stage=stage,
                execution_key=execution_key,
                run_id=_resolved_run_id(args, merged),
                report_id=report_id,
                status="completed",
                result_payload=result_payload,
                context_snapshot=context_snapshot,
                metrics_snapshot=metrics_snapshot,
            )
            _emit_stage_event(
                cw2_cfg=cw2_cfg,
                engine=engine,
                stage=stage,
                status="completed",
                execution_key=execution_key,
                payload={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                    "run_id": _resolved_run_id(args, merged),
                    "result_keys": sorted(result_payload.keys()),
                    "context_path": coerce_optional_str(args.context_path),
                },
            )
            print_json(result_payload)
            return 0
        except Exception as exc:
            failure_context_snapshot = build_runtime_context_snapshot(
                context,
                context_path=coerce_optional_str(args.context_path),
                stage_name=stage,
                extra={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                    "error_text": str(exc),
                },
            )
            failure_metrics_snapshot = build_runtime_metrics_snapshot(
                {},
                extra={
                    "stage_order": _stage_order(stage),
                    "stage_status": "failed",
                },
            )
            _record_stage_quality(
                engine=engine,
                stage=stage,
                execution_key=execution_key,
                passed=False,
                failures=[str(exc)],
                row_count=0,
                run_id=_resolved_run_id(args, context),
            )
            _record_control_plane_finish(
                engine=engine,
                pipeline_name=pipeline_name,
                pipeline_execution_key=pipeline_execution_key,
                stage=stage,
                execution_key=execution_key,
                run_id=_resolved_run_id(args, context),
                report_id=coerce_optional_str(dict(context.get("report") or {}).get("report_id")),
                status="failed",
                context_snapshot=failure_context_snapshot,
                metrics_snapshot=failure_metrics_snapshot,
                error_text=str(exc),
            )
            _emit_stage_event(
                cw2_cfg=cw2_cfg,
                engine=engine,
                stage=stage,
                status="failed",
                execution_key=execution_key,
                severity="critical",
                payload={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                    "run_id": _resolved_run_id(args, context),
                    "error_text": str(exc),
                    "context_path": coerce_optional_str(args.context_path),
                },
            )
            raise


def _run_bundle(
    *,
    args: argparse.Namespace,
    cw2_cfg: Dict[str, Any],
    engine,
) -> int:
    """Run backtest, analysis, report, and optional verify as one locked bundle."""
    context = load_stage_context(coerce_optional_str(args.context_path))
    pipeline_name = _pipeline_name(args)
    pipeline_execution_key = _pipeline_execution_key(args, context)
    execution_key = _execution_key(stage="bundle", args=args, context=context)
    lock_name = f"cw2:bundle:{execution_key}"
    verify_reference = coerce_bool(args.verify_reference, default=False)

    with runtime_lock(
        lock_name=lock_name,
        ttl_seconds=int(args.runtime_lock_ttl_seconds),
        raise_on_locked=True,
    ) as lock_handle:
        start_payload = {
            "pipeline_name": pipeline_name,
            "pipeline_execution_key": pipeline_execution_key,
            "context_path": coerce_optional_str(args.context_path),
            "verify_reference": verify_reference,
            "lock_name": lock_name,
        }
        _record_control_plane_start(
            engine=engine,
            pipeline_name=pipeline_name,
            pipeline_execution_key=pipeline_execution_key,
            stage="bundle",
            execution_key=execution_key,
            lock_name=lock_name,
            lock_handle=lock_handle,
            run_id=_resolved_run_id(args, context),
            payload=start_payload,
        )
        _emit_stage_event(
            cw2_cfg=cw2_cfg,
            engine=engine,
            stage="bundle",
            status="started",
            execution_key=execution_key,
            payload=start_payload,
        )
        try:
            context = _persist_context(args, _run_backtest_stage(args=args, context=context))
            context = _persist_context(args, _run_analysis_stage(args=args, context=context))
            context = _persist_context(args, _run_report_stage(args=args, context=context))
            if verify_reference:
                context = _persist_context(args, _run_verify_stage(args=args, context=context))
            result = {
                "execution_mode": context.get("execution_mode"),
                "run_id": context.get("run_id"),
                "run_name": context.get("run_name"),
                "analysis": context.get("analysis"),
                "report": context.get("report"),
            }
            if "verification" in context:
                result["verification"] = context["verification"]
            report_id = coerce_optional_str(dict(context.get("report") or {}).get("report_id"))
            context_snapshot = build_runtime_context_snapshot(
                context,
                context_path=coerce_optional_str(args.context_path),
                stage_name="bundle",
                extra={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                    "verify_reference": verify_reference,
                },
            )
            metrics_snapshot = build_runtime_metrics_snapshot(
                result,
                extra={
                    "stage_order": _stage_order("bundle"),
                    "stage_status": "completed",
                    "verify_reference": verify_reference,
                },
            )
            _record_stage_quality(
                engine=engine,
                stage="bundle",
                execution_key=execution_key,
                passed=True,
                row_count=len(result),
                run_id=_resolved_run_id(args, context),
                extra={"verify_reference": verify_reference},
            )
            _record_control_plane_finish(
                engine=engine,
                pipeline_name=pipeline_name,
                pipeline_execution_key=pipeline_execution_key,
                stage="bundle",
                execution_key=execution_key,
                run_id=_resolved_run_id(args, context),
                report_id=report_id,
                status="completed",
                result_payload=result,
                context_snapshot=context_snapshot,
                metrics_snapshot=metrics_snapshot,
            )
            _emit_stage_event(
                cw2_cfg=cw2_cfg,
                engine=engine,
                stage="bundle",
                status="completed",
                execution_key=execution_key,
                payload={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                    "run_id": _resolved_run_id(args, context),
                    "report_id": report_id,
                    "verify_reference": verify_reference,
                },
            )
            print_json(result)
            return 0
        except Exception as exc:
            failure_context_snapshot = build_runtime_context_snapshot(
                context,
                context_path=coerce_optional_str(args.context_path),
                stage_name="bundle",
                extra={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                    "verify_reference": verify_reference,
                    "error_text": str(exc),
                },
            )
            failure_metrics_snapshot = build_runtime_metrics_snapshot(
                {},
                extra={
                    "stage_order": _stage_order("bundle"),
                    "stage_status": "failed",
                    "verify_reference": verify_reference,
                },
            )
            _record_stage_quality(
                engine=engine,
                stage="bundle",
                execution_key=execution_key,
                passed=False,
                failures=[str(exc)],
                row_count=0,
                run_id=_resolved_run_id(args, context),
                extra={"verify_reference": verify_reference},
            )
            _record_control_plane_finish(
                engine=engine,
                pipeline_name=pipeline_name,
                pipeline_execution_key=pipeline_execution_key,
                stage="bundle",
                execution_key=execution_key,
                run_id=_resolved_run_id(args, context),
                report_id=coerce_optional_str(dict(context.get("report") or {}).get("report_id")),
                status="failed",
                context_snapshot=failure_context_snapshot,
                metrics_snapshot=failure_metrics_snapshot,
                error_text=str(exc),
            )
            _emit_stage_event(
                cw2_cfg=cw2_cfg,
                engine=engine,
                stage="bundle",
                status="failed",
                execution_key=execution_key,
                severity="critical",
                payload={
                    "pipeline_name": pipeline_name,
                    "pipeline_execution_key": pipeline_execution_key,
                    "run_id": _resolved_run_id(args, context),
                    "error_text": str(exc),
                    "verify_reference": verify_reference,
                },
            )
            raise


def main() -> int:
    """Parse args and dispatch to either one stage or the full scheduler bundle."""
    args = build_parser().parse_args()
    load_env_layers()
    cw2_cfg = load_yaml(str(args.cw2_config))
    engine = _optional_db_engine()
    stage = str(args.stage or "bundle").strip().lower()
    if stage == "bundle":
        return _run_bundle(args=args, cw2_cfg=cw2_cfg, engine=engine)
    return _run_single_stage(stage=stage, args=args, cw2_cfg=cw2_cfg, engine=engine)


if __name__ == "__main__":
    raise SystemExit(main())
