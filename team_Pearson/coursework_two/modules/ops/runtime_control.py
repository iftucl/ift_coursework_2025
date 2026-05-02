from __future__ import annotations

"""Shared runtime control helpers for scheduler-driven CW2 workflows.

This module keeps PostgreSQL as the canonical analytical store while giving
Redis, Kafka, and quality snapshots clearer operational responsibilities:

- Redis: distributed runtime locks for long-running orchestration stages.
- Kafka: structured scheduler-stage lifecycle events for independent consumers.
- SQL quality snapshots: stage-level execution evidence.
"""

import hashlib
import json
import logging
import os
import socket
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

from sqlalchemy.engine import Engine

try:
    from team_Pearson.coursework_one.modules.utils.kafka import (
        publish_json_events,
        resolve_kafka_config,
    )
    from team_Pearson.coursework_one.modules.utils.resilience import _get_redis
    from team_Pearson.coursework_two.modules.ops.monitoring import (
        record_ops_event,
        record_pipeline_run,
        record_stage_run,
    )
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot
except ModuleNotFoundError:  # pragma: no cover - import-path fallback
    import sys

    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_one.modules.utils.kafka import (
        publish_json_events,
        resolve_kafka_config,
    )
    from team_Pearson.coursework_one.modules.utils.resilience import _get_redis
    from team_Pearson.coursework_two.modules.ops.monitoring import (
        record_ops_event,
        record_pipeline_run,
        record_stage_run,
    )
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot

logger = logging.getLogger(__name__)

_RUNTIME_STAGE_SCHEMA_VERSION = "cw2_runtime_stage.v1"
_DEFAULT_CONTRACT_VERSION = "cw2_runtime_control.v1"
_DEFAULT_LOCK_TTL_SECONDS = 6 * 60 * 60
_LOCK_KEY_PREFIX = "cw2:runtime:lock:"
_LOCK_METADATA_KEY_PREFIX = "cw2:runtime:lockmeta:"
_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
""".strip()
_RECLAIM_STALE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  redis.call('del', KEYS[1])
  redis.call('del', KEYS[2])
  return 1
end
return 0
""".strip()


@dataclass(frozen=True)
class RuntimeLockHandle:
    """Represents one runtime lock acquisition attempt."""

    requested_name: str
    redis_key: str
    token: str
    ttl_seconds: int
    backend: str
    acquired: bool
    metadata_key: Optional[str] = None
    heartbeat_interval_seconds: Optional[int] = None
    owner_metadata: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SchedulerRuntimeMetadata:
    """Resolved scheduler/runtime identity for SQL control-plane rows."""

    trigger_source: str
    airflow_dag_id: Optional[str]
    airflow_dag_run_id: Optional[str]
    airflow_task_id: Optional[str]


def _stable_short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _normalized_lock_name(lock_name: str) -> str:
    text_value = str(lock_name or "").strip()
    if not text_value:
        raise ValueError("lock_name is required")
    safe = []
    for char in text_value.lower():
        if char.isalnum():
            safe.append(char)
        elif char in {"-", "_", ":"}:
            safe.append(char)
        else:
            safe.append("_")
    normalized = "".join(safe).strip("_")
    if len(normalized) <= 120:
        return normalized
    return f"{normalized[:96]}_{_stable_short_hash(normalized)}"


def _runtime_quality_run_id(stage_name: str, execution_key: str) -> str:
    raw = f"{stage_name}:{execution_key}"
    return f"cw2rt_{_stable_short_hash(raw)}"


def _default_heartbeat_interval(ttl_seconds: int) -> int:
    ttl = max(10, int(ttl_seconds))
    return max(5, min(60, ttl // 3))


def _parse_runtime_timestamp(value: Any) -> datetime | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decode_lock_metadata(raw_value: Any) -> Dict[str, Any]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, Mapping):
        return dict(raw_value)
    try:
        decoded = json.loads(str(raw_value))
    except Exception:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _stale_lock_threshold_seconds(metadata: Mapping[str, Any], *, ttl_seconds: int) -> int:
    heartbeat_interval = int(
        metadata.get("heartbeat_interval_seconds") or _default_heartbeat_interval(ttl_seconds)
    )
    return max(15, heartbeat_interval * 3)


def _is_lock_metadata_stale(metadata: Mapping[str, Any], *, ttl_seconds: int) -> bool:
    if not metadata:
        return False
    latest = _parse_runtime_timestamp(
        metadata.get("last_heartbeat_at_utc") or metadata.get("acquired_at_utc")
    )
    if latest is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - latest).total_seconds()
    return age_seconds > float(_stale_lock_threshold_seconds(metadata, ttl_seconds=ttl_seconds))


def _reclaim_stale_lock_if_needed(
    client: Any,
    *,
    redis_key: str,
    metadata_key: str,
    ttl_seconds: int,
) -> Dict[str, Any]:
    current_token = client.get(redis_key)
    metadata = _decode_lock_metadata(client.get(metadata_key))
    if not current_token or not metadata:
        return {"reclaimed": False, "owner_metadata": metadata}
    owner_token = str(metadata.get("token") or "").strip()
    if owner_token != str(current_token):
        return {"reclaimed": False, "owner_metadata": metadata}
    if not _is_lock_metadata_stale(metadata, ttl_seconds=ttl_seconds):
        return {"reclaimed": False, "owner_metadata": metadata}
    try:
        reclaimed = bool(
            client.eval(
                _RECLAIM_STALE_LOCK_LUA,
                2,
                redis_key,
                metadata_key,
                str(current_token),
            )
        )
    except Exception:  # pragma: no cover - operational fallback only
        logger.warning(
            "cw2_runtime: failed to reclaim stale runtime lock key=%s",
            redis_key,
            exc_info=True,
        )
        reclaimed = False
    if reclaimed:
        logger.warning(
            "cw2_runtime: reclaimed stale runtime lock key=%s last_heartbeat_at=%s",
            redis_key,
            metadata.get("last_heartbeat_at_utc") or metadata.get("acquired_at_utc"),
        )
    return {"reclaimed": reclaimed, "owner_metadata": metadata}


def _resolved_scheduler_runtime_metadata() -> SchedulerRuntimeMetadata:
    dag_id = _normalize_optional_text(os.getenv("AIRFLOW_CTX_DAG_ID"))
    dag_run_id = _normalize_optional_text(os.getenv("AIRFLOW_CTX_DAG_RUN_ID"))
    task_id = _normalize_optional_text(os.getenv("AIRFLOW_CTX_TASK_ID"))
    trigger_source = "airflow" if dag_id or dag_run_id or task_id else "script"
    return SchedulerRuntimeMetadata(
        trigger_source=trigger_source,
        airflow_dag_id=dag_id,
        airflow_dag_run_id=dag_run_id,
        airflow_task_id=task_id,
    )


def _build_lock_owner_metadata(
    *,
    lock_name: str,
    redis_key: str,
    token: str,
    ttl_seconds: int,
    heartbeat_interval_seconds: int,
) -> Dict[str, Any]:
    runtime = _resolved_scheduler_runtime_metadata()
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "token": token,
        "requested_name": lock_name,
        "redis_key": redis_key,
        "hostname": socket.gethostname(),
        "process_id": os.getpid(),
        "thread_id": threading.get_ident(),
        "trigger_source": runtime.trigger_source,
        "airflow_dag_id": runtime.airflow_dag_id,
        "airflow_dag_run_id": runtime.airflow_dag_run_id,
        "airflow_task_id": runtime.airflow_task_id,
        "acquired_at_utc": timestamp,
        "last_heartbeat_at_utc": timestamp,
        "ttl_seconds": int(ttl_seconds),
        "heartbeat_interval_seconds": int(heartbeat_interval_seconds),
    }


def acquire_runtime_lock(
    *,
    lock_name: str,
    ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS,
    heartbeat_interval_seconds: int | None = None,
    raise_on_locked: bool = True,
) -> RuntimeLockHandle:
    """Acquire a Redis-backed runtime lock when Redis is available."""

    normalized_name = _normalized_lock_name(lock_name)
    redis_key = f"{_LOCK_KEY_PREFIX}{normalized_name}"
    metadata_key = f"{_LOCK_METADATA_KEY_PREFIX}{normalized_name}"
    token = str(uuid.uuid4())
    ttl = max(1, int(ttl_seconds))
    heartbeat_interval = (
        int(heartbeat_interval_seconds)
        if heartbeat_interval_seconds is not None
        else _default_heartbeat_interval(ttl)
    )
    owner_metadata = _build_lock_owner_metadata(
        lock_name=lock_name,
        redis_key=redis_key,
        token=token,
        ttl_seconds=ttl,
        heartbeat_interval_seconds=heartbeat_interval,
    )
    client = _get_redis()
    if client is None:
        return RuntimeLockHandle(
            requested_name=lock_name,
            redis_key=redis_key,
            token=token,
            ttl_seconds=ttl,
            backend="disabled",
            acquired=True,
            metadata_key=metadata_key,
            heartbeat_interval_seconds=heartbeat_interval,
            owner_metadata=owner_metadata,
        )

    acquired = bool(client.set(redis_key, token, nx=True, ex=ttl))
    owner_metadata_on_conflict: Dict[str, Any] | None = None
    if not acquired:
        reclaim_result = _reclaim_stale_lock_if_needed(
            client,
            redis_key=redis_key,
            metadata_key=metadata_key,
            ttl_seconds=ttl,
        )
        owner_metadata_on_conflict = dict(reclaim_result.get("owner_metadata") or {})
        if bool(reclaim_result.get("reclaimed")):
            acquired = bool(client.set(redis_key, token, nx=True, ex=ttl))
    if acquired:
        try:
            client.set(
                metadata_key,
                json.dumps(owner_metadata, ensure_ascii=False, sort_keys=True),
                ex=ttl,
            )
        except Exception:  # pragma: no cover - metadata is best-effort
            logger.warning(
                "cw2_runtime: failed to persist lock metadata key=%s",
                metadata_key,
                exc_info=True,
            )
    handle = RuntimeLockHandle(
        requested_name=lock_name,
        redis_key=redis_key,
        token=token,
        ttl_seconds=ttl,
        backend="redis",
        acquired=acquired,
        metadata_key=metadata_key,
        heartbeat_interval_seconds=heartbeat_interval,
        owner_metadata=owner_metadata if acquired else owner_metadata_on_conflict,
    )
    if not acquired and raise_on_locked:
        owner = dict(owner_metadata_on_conflict or {})
        owner_details = ""
        if owner:
            owner_details = (
                f" owner_dag={owner.get('airflow_dag_id')!r}"
                f" owner_task={owner.get('airflow_task_id')!r}"
                f" last_heartbeat_at={owner.get('last_heartbeat_at_utc')!r}"
            )
        raise RuntimeError(
            f"CW2 runtime lock already held: requested={lock_name!r} redis_key={redis_key!r}{owner_details}"
        )
    return handle


def release_runtime_lock(handle: RuntimeLockHandle) -> None:
    """Best-effort release of a runtime lock."""

    if handle.backend != "redis" or not handle.acquired:
        return
    client = _get_redis()
    if client is None:
        return
    try:
        released = client.eval(_RELEASE_LOCK_LUA, 1, handle.redis_key, handle.token)
        if released and handle.metadata_key:
            client.delete(handle.metadata_key)
    except Exception:  # pragma: no cover - operational cleanup only
        try:
            current_value = client.get(handle.redis_key)
            if current_value == handle.token:
                client.delete(handle.redis_key)
                if handle.metadata_key:
                    client.delete(handle.metadata_key)
        except Exception:
            logger.warning(
                "cw2_runtime: failed to release runtime lock key=%s",
                handle.redis_key,
                exc_info=True,
            )


def refresh_runtime_lock(handle: RuntimeLockHandle) -> bool:
    """Refresh one runtime lock TTL when Redis is available."""

    if handle.backend != "redis" or not handle.acquired:
        return True
    client = _get_redis()
    if client is None:
        return False
    try:
        current_value = client.get(handle.redis_key)
        if current_value != handle.token:
            return False
        ttl = max(1, int(handle.ttl_seconds))
        if hasattr(client, "expire"):
            client.expire(handle.redis_key, ttl)
            if handle.metadata_key:
                client.expire(handle.metadata_key, ttl)
        if handle.metadata_key and handle.owner_metadata is not None:
            refreshed_metadata = dict(handle.owner_metadata)
            refreshed_metadata["last_heartbeat_at_utc"] = datetime.now(timezone.utc).isoformat()
            client.set(
                handle.metadata_key,
                json.dumps(refreshed_metadata, ensure_ascii=False, sort_keys=True),
                ex=ttl,
            )
        return True
    except Exception:  # pragma: no cover - operational refresh only
        logger.warning(
            "cw2_runtime: failed to refresh runtime lock key=%s",
            handle.redis_key,
            exc_info=True,
        )
        return False


def _run_lock_heartbeat(
    *,
    handle: RuntimeLockHandle,
    stop_event: threading.Event,
) -> None:
    interval = max(1, int(handle.heartbeat_interval_seconds or 0))
    if interval <= 0:
        return
    while not stop_event.wait(interval):
        if not refresh_runtime_lock(handle):
            logger.warning(
                "cw2_runtime: heartbeat lost runtime lock key=%s requested=%s",
                handle.redis_key,
                handle.requested_name,
            )
            return


@contextmanager
def runtime_lock(
    *,
    lock_name: str,
    ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS,
    heartbeat_interval_seconds: int | None = None,
    raise_on_locked: bool = True,
) -> Iterator[RuntimeLockHandle]:
    """Context manager around :func:`acquire_runtime_lock`."""

    handle = acquire_runtime_lock(
        lock_name=lock_name,
        ttl_seconds=ttl_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        raise_on_locked=raise_on_locked,
    )
    stop_event: threading.Event | None = None
    heartbeat_thread: threading.Thread | None = None
    if handle.backend == "redis" and handle.acquired:
        stop_event = threading.Event()
        heartbeat_thread = threading.Thread(
            target=_run_lock_heartbeat,
            kwargs={"handle": handle, "stop_event": stop_event},
            name=f"cw2-lock-{_stable_short_hash(handle.redis_key)}",
            daemon=True,
        )
        heartbeat_thread.start()
    try:
        yield handle
    finally:
        if stop_event is not None:
            stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=max(1.0, float(handle.heartbeat_interval_seconds or 1)))
        release_runtime_lock(handle)


def load_stage_context(path: str | None) -> Dict[str, Any]:
    """Load one orchestration context file when present."""

    text_path = str(path or "").strip()
    if not text_path:
        return {}
    target = Path(text_path)
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid stage context JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Stage context must be a JSON object: {target}")
    return dict(payload)


def merge_stage_context(path: str | None, updates: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge updates into a stage context file and return the merged payload."""

    current = load_stage_context(path)
    merged = {**current, **dict(updates)}
    text_path = str(path or "").strip()
    if text_path:
        target = Path(text_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(merged, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    return merged


def _context_json_safe(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        max_items = 24 if depth == 0 else 12
        items = list(value.items())
        compact: Dict[str, Any] = {}
        for index, (key, item_value) in enumerate(items[:max_items]):
            compact[str(key)] = _context_json_safe(item_value, depth=depth + 1)
        if len(items) > max_items:
            compact["__truncated__"] = f"{len(items) - max_items} keys omitted"
        return compact
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        max_items = 16 if depth == 0 else 8
        compact = [_context_json_safe(item, depth=depth + 1) for item in items[:max_items]]
        if len(items) > max_items:
            compact.append(f"... {len(items) - max_items} more")
        return compact
    return str(value)


def build_runtime_context_snapshot(
    context: Mapping[str, Any] | None,
    *,
    context_path: str | None = None,
    stage_name: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build one compact, JSON-safe runtime context snapshot for SQL control-plane rows."""

    context_dict = dict(context or {})
    snapshot: Dict[str, Any] = {}
    resolved_context_path = _normalize_optional_text(context_path) or _normalize_optional_text(
        context_dict.get("context_path")
    )
    if resolved_context_path is not None:
        snapshot["context_path"] = resolved_context_path
    if _normalize_optional_text(stage_name) is not None:
        snapshot["stage_name"] = str(stage_name)

    stage_keys = sorted(str(key) for key in context_dict.keys())
    if stage_keys:
        snapshot["stage_keys"] = stage_keys

    for key in ("execution_mode", "run_id", "run_name"):
        value = _normalize_optional_text(context_dict.get(key))
        if value is not None:
            snapshot[key] = value

    report_payload = context_dict.get("report")
    if isinstance(report_payload, Mapping):
        snapshot["report"] = _context_json_safe(report_payload)

    verification_payload = context_dict.get("verification")
    if isinstance(verification_payload, Mapping):
        snapshot["verification"] = _context_json_safe(verification_payload)

    analysis_payload = context_dict.get("analysis")
    if isinstance(analysis_payload, Mapping):
        analysis_dict = dict(analysis_payload)
        snapshot["analysis"] = {
            "keys": sorted(str(key) for key in analysis_dict.keys()),
            **{
                field: _context_json_safe(analysis_dict.get(field))
                for field in (
                    "analysis_run_id",
                    "run_id",
                    "summary_path",
                    "benchmark_name",
                )
                if analysis_dict.get(field) is not None
            },
        }

    handled_keys = {
        "execution_mode",
        "run_id",
        "run_name",
        "report",
        "verification",
        "analysis",
    }
    for key, value in context_dict.items():
        if key in handled_keys:
            continue
        snapshot[str(key)] = _context_json_safe(value)

    for key, value in dict(extra or {}).items():
        snapshot[str(key)] = _context_json_safe(value)

    return {
        key: value
        for key, value in snapshot.items()
        if value is not None and value != {} and value != []
    }


def build_runtime_metrics_snapshot(
    result: Mapping[str, Any] | None,
    *,
    extra: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build one compact metrics snapshot for pipeline-level SQL control-plane rows."""

    result_dict = dict(result or {})
    metrics: Dict[str, Any] = {}
    if result_dict:
        metrics["result_keys"] = sorted(str(key) for key in result_dict.keys())
    scalar_keys = (
        "processed_count",
        "skipped_existing_count",
        "symbol_count",
        "month_end_count",
        "sql_table_count",
        "artifact_count",
        "ready",
        "passed",
        "return_code",
        "consumed_count",
        "processed_count",
        "failed_count",
        "dead_letter_count",
        "committed_count",
        "lag_snapshot_count",
        "overall_status",
        "readiness_profile",
        "execution_mode",
    )
    for key in scalar_keys:
        if key in result_dict and result_dict.get(key) is not None:
            metrics[key] = _context_json_safe(result_dict.get(key))
    layer_status = result_dict.get("layer_status")
    if isinstance(layer_status, Mapping):
        metrics["verification_layers"] = _context_json_safe(layer_status)
        metrics["verification_layers_passed"] = sum(
            1 for passed in dict(layer_status).values() if bool(passed)
        )
    for key, value in dict(extra or {}).items():
        metrics[str(key)] = _context_json_safe(value)
    return {
        key: value
        for key, value in metrics.items()
        if value is not None and value != {} and value != []
    }


def emit_scheduler_stage_event(
    config: Mapping[str, Any] | None,
    *,
    engine: Engine | None,
    producer_component: str,
    stage_name: str,
    stage_status: str,
    execution_key: str,
    topic_key: str = "platform_run_status",
    default_topic: str = "platform.runs.status.v1",
    severity: str = "info",
    payload: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Emit a structured CW2 scheduler-stage event to Kafka and SQL audit."""

    payload_dict = dict(payload or {})
    created_at = datetime.now(timezone.utc)
    idempotency_key = payload_dict.get("idempotency_key") or (
        f"{producer_component}:{stage_name}:{stage_status}:{execution_key}"
    )
    event = {
        "event_id": payload_dict.get("event_id")
        or f"{stage_name}:{stage_status}:{_stable_short_hash(str(idempotency_key))}",
        "event_type": "cw2_scheduler_stage",
        "schema_version": _RUNTIME_STAGE_SCHEMA_VERSION,
        "stage_name": stage_name,
        "stage_status": stage_status,
        "producer_component": producer_component,
        "execution_key": execution_key,
        "idempotency_key": str(idempotency_key),
        "created_at_utc": created_at.isoformat(),
        **payload_dict,
    }
    published_count = publish_json_events(
        config,
        topic_key=topic_key,
        default_topic=default_topic,
        events=[event],
        key_field="run_id",
        default_client_id="team_pearson_cw2_scheduler",
    )
    resolved = resolve_kafka_config(config, default_client_id="team_pearson_cw2_scheduler")
    topic_name = resolved.topics.get(topic_key, default_topic)
    publish_status = (
        "published" if published_count > 0 else ("disabled" if not resolved.enabled else "recorded")
    )
    if engine is not None:
        record_ops_event(
            engine=engine,
            event_id=str(event["event_id"]),
            event_type=str(event["event_type"]),
            producer_component=producer_component,
            payload=event,
            topic_key=topic_key,
            topic_name=topic_name,
            run_id=_normalize_optional_text(event.get("run_id")),
            symbol=_normalize_optional_text(event.get("symbol")),
            severity=str(severity or "info"),
            publish_status=publish_status,
            event_time=created_at,
        )
    return {
        "event_id": str(event["event_id"]),
        "topic_name": topic_name,
        "publish_status": publish_status,
    }


def record_scheduler_pipeline_state(
    *,
    engine: Engine | None,
    pipeline_name: str,
    execution_key: str,
    status: str,
    stage_name: str | None = None,
    run_id: str | None = None,
    report_id: str | None = None,
    started_at: Any = None,
    completed_at: Any = None,
    context: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    error_text: str | None = None,
) -> None:
    """Persist pipeline-level scheduler state into SQL control-plane tables."""

    if engine is None:
        return
    runtime = _resolved_scheduler_runtime_metadata()
    record_pipeline_run(
        engine=engine,
        pipeline_name=str(pipeline_name),
        execution_key=str(execution_key),
        status=str(status),
        trigger_source=runtime.trigger_source,
        airflow_dag_id=runtime.airflow_dag_id,
        airflow_dag_run_id=runtime.airflow_dag_run_id,
        latest_task_id=runtime.airflow_task_id,
        latest_stage_name=_normalize_optional_text(stage_name),
        run_id=_normalize_optional_text(run_id),
        report_id=_normalize_optional_text(report_id),
        started_at=started_at,
        completed_at=completed_at,
        context=dict(context or {}),
        metrics=dict(metrics or {}),
        error_text=_normalize_optional_text(error_text),
    )


def record_scheduler_stage_state(
    *,
    engine: Engine | None,
    pipeline_name: str,
    stage_name: str,
    execution_key: str,
    stage_status: str,
    stage_order: int | None = None,
    run_id: str | None = None,
    report_id: str | None = None,
    lock_handle: RuntimeLockHandle | None = None,
    lock_name: str | None = None,
    idempotency_key: str | None = None,
    started_at: Any = None,
    completed_at: Any = None,
    payload: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    error_text: str | None = None,
) -> None:
    """Persist stage-level scheduler state into SQL control-plane tables."""

    if engine is None:
        return
    runtime = _resolved_scheduler_runtime_metadata()
    effective_lock_name = _normalize_optional_text(lock_name)
    effective_lock_backend = None
    effective_lock_key = None
    if lock_handle is not None:
        effective_lock_name = effective_lock_name or str(lock_handle.requested_name)
        effective_lock_backend = str(lock_handle.backend)
        effective_lock_key = str(lock_handle.redis_key)
    record_stage_run(
        engine=engine,
        pipeline_name=str(pipeline_name),
        stage_name=str(stage_name),
        execution_key=str(execution_key),
        stage_status=str(stage_status),
        stage_order=stage_order,
        trigger_source=runtime.trigger_source,
        airflow_dag_id=runtime.airflow_dag_id,
        airflow_dag_run_id=runtime.airflow_dag_run_id,
        airflow_task_id=runtime.airflow_task_id,
        run_id=_normalize_optional_text(run_id),
        report_id=_normalize_optional_text(report_id),
        lock_name=effective_lock_name,
        lock_backend=_normalize_optional_text(effective_lock_backend),
        lock_key=_normalize_optional_text(effective_lock_key),
        idempotency_key=_normalize_optional_text(idempotency_key),
        started_at=started_at,
        completed_at=completed_at,
        payload=dict(payload or {}),
        result=dict(result or {}),
        error_text=_normalize_optional_text(error_text),
    )


def record_runtime_quality_snapshot(
    *,
    engine: Engine | None,
    stage_name: str,
    execution_key: str,
    run_date: date | datetime | str,
    passed: bool,
    failures: list[str] | None = None,
    warnings: list[str] | None = None,
    row_count: int | None = None,
    run_id: str | None = None,
    contract_version: str = _DEFAULT_CONTRACT_VERSION,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Persist one standardized runtime quality snapshot."""

    if engine is None:
        return
    report = {
        "stage_name": stage_name,
        "contract_version": contract_version,
        "passed": bool(passed),
        "failures": list(failures or []),
        "warnings": list(warnings or []),
        "row_count": int(row_count) if row_count is not None else None,
        **dict(extra or {}),
    }
    record_quality_snapshot(
        engine=engine,
        dataset_name=stage_name,
        run_id=str(run_id or _runtime_quality_run_id(stage_name, execution_key)),
        run_date=run_date,
        quality_report=report,
    )


def _normalize_optional_text(value: Any) -> Optional[str]:
    text_value = str(value or "").strip()
    return text_value or None
