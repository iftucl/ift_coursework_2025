from __future__ import annotations

"""Operational monitoring helpers for the CW2 event/ops layer."""

import json
import logging
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

try:
    from team_Pearson.coursework_one.modules.utils.kafka import resolve_kafka_config
except ModuleNotFoundError:  # pragma: no cover - import-path fallback
    import sys

    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_one.modules.utils.kafka import resolve_kafka_config

logger = logging.getLogger(__name__)

_SCHEMA = "systematic_equity"
_SCHEMA_READY_ENGINES: set[int] = set()


def ensure_ops_monitoring_schema(engine: Engine) -> None:
    """Create or migrate the operational monitoring schema objects."""

    schema_path = Path(__file__).resolve().parents[2] / "sql" / "cw2_ops_schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()
    finally:
        raw_conn.close()


def _ensure_ops_monitoring_schema_once(engine: Engine) -> None:
    cache_key = id(engine)
    if cache_key in _SCHEMA_READY_ENGINES:
        return
    ensure_ops_monitoring_schema(engine)
    _SCHEMA_READY_ENGINES.add(cache_key)


def record_pipeline_run(
    *,
    engine: Engine,
    pipeline_name: str,
    execution_key: str,
    status: str,
    trigger_source: str = "manual",
    airflow_dag_id: Optional[str] = None,
    airflow_dag_run_id: Optional[str] = None,
    latest_task_id: Optional[str] = None,
    latest_stage_name: Optional[str] = None,
    run_id: Optional[str] = None,
    report_id: Optional[str] = None,
    started_at: Any = None,
    completed_at: Any = None,
    context: Optional[Mapping[str, Any]] = None,
    metrics: Optional[Mapping[str, Any]] = None,
    error_text: Optional[str] = None,
) -> bool:
    """Upsert one pipeline-level runtime control-plane row."""

    _ensure_ops_monitoring_schema_once(engine)
    started_ts = _normalize_event_time(started_at) if started_at is not None else None
    completed_ts = _normalize_event_time(completed_at) if completed_at is not None else None
    duration_ms = _duration_ms(started_ts, completed_ts)
    sql = text(f"""
        INSERT INTO {_SCHEMA}.ops_pipeline_runs (
            pipeline_name,
            execution_key,
            trigger_source,
            airflow_dag_id,
            airflow_dag_run_id,
            latest_task_id,
            latest_stage_name,
            run_id,
            report_id,
            status,
            started_at,
            completed_at,
            duration_ms,
            context_json,
            metrics_json,
            error_text,
            created_at,
            updated_at
        ) VALUES (
            :pipeline_name,
            :execution_key,
            :trigger_source,
            :airflow_dag_id,
            :airflow_dag_run_id,
            :latest_task_id,
            :latest_stage_name,
            :run_id,
            :report_id,
            :status,
            :started_at,
            :completed_at,
            :duration_ms,
            CAST(:context_json AS JSONB),
            CAST(:metrics_json AS JSONB),
            :error_text,
            NOW(),
            NOW()
        )
        ON CONFLICT (pipeline_name, execution_key)
        DO UPDATE SET
            trigger_source = EXCLUDED.trigger_source,
            airflow_dag_id = EXCLUDED.airflow_dag_id,
            airflow_dag_run_id = EXCLUDED.airflow_dag_run_id,
            latest_task_id = EXCLUDED.latest_task_id,
            latest_stage_name = EXCLUDED.latest_stage_name,
            run_id = COALESCE(EXCLUDED.run_id, {_SCHEMA}.ops_pipeline_runs.run_id),
            report_id = COALESCE(EXCLUDED.report_id, {_SCHEMA}.ops_pipeline_runs.report_id),
            status = EXCLUDED.status,
            started_at = COALESCE({_SCHEMA}.ops_pipeline_runs.started_at, EXCLUDED.started_at),
            completed_at = EXCLUDED.completed_at,
            duration_ms = COALESCE(EXCLUDED.duration_ms, {_SCHEMA}.ops_pipeline_runs.duration_ms),
            context_json = EXCLUDED.context_json,
            metrics_json = EXCLUDED.metrics_json,
            error_text = EXCLUDED.error_text,
            updated_at = NOW()
        """)
    params = {
        "pipeline_name": str(pipeline_name),
        "execution_key": str(execution_key),
        "trigger_source": _normalize_trigger_source(trigger_source),
        "airflow_dag_id": _normalize_optional_text(airflow_dag_id),
        "airflow_dag_run_id": _normalize_optional_text(airflow_dag_run_id),
        "latest_task_id": _normalize_optional_text(latest_task_id),
        "latest_stage_name": _normalize_optional_text(latest_stage_name),
        "run_id": _normalize_optional_text(run_id),
        "report_id": _normalize_optional_text(report_id),
        "status": _normalize_pipeline_status(status),
        "started_at": started_ts,
        "completed_at": completed_ts,
        "duration_ms": duration_ms,
        "context_json": json.dumps(
            dict(context or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
        "metrics_json": json.dumps(
            dict(metrics or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
        "error_text": _normalize_optional_text(error_text),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
        return True
    except Exception:  # pragma: no cover - monitoring must stay non-brittle
        logger.warning(
            "cw2_monitoring: failed to persist pipeline run pipeline=%s execution_key=%s",
            pipeline_name,
            execution_key,
            exc_info=True,
        )
        return False


def record_stage_run(
    *,
    engine: Engine,
    pipeline_name: str,
    stage_name: str,
    execution_key: str,
    stage_status: str,
    stage_order: Optional[int] = None,
    trigger_source: str = "manual",
    airflow_dag_id: Optional[str] = None,
    airflow_dag_run_id: Optional[str] = None,
    airflow_task_id: Optional[str] = None,
    run_id: Optional[str] = None,
    report_id: Optional[str] = None,
    lock_name: Optional[str] = None,
    lock_backend: Optional[str] = None,
    lock_key: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    started_at: Any = None,
    completed_at: Any = None,
    payload: Optional[Mapping[str, Any]] = None,
    result: Optional[Mapping[str, Any]] = None,
    error_text: Optional[str] = None,
) -> bool:
    """Upsert one stage-level runtime control-plane row."""

    _ensure_ops_monitoring_schema_once(engine)
    started_ts = _normalize_event_time(started_at) if started_at is not None else None
    completed_ts = _normalize_event_time(completed_at) if completed_at is not None else None
    duration_ms = _duration_ms(started_ts, completed_ts)
    sql = text(f"""
        INSERT INTO {_SCHEMA}.ops_stage_runs (
            pipeline_name,
            stage_name,
            execution_key,
            stage_order,
            trigger_source,
            airflow_dag_id,
            airflow_dag_run_id,
            airflow_task_id,
            run_id,
            report_id,
            stage_status,
            lock_name,
            lock_backend,
            lock_key,
            idempotency_key,
            started_at,
            completed_at,
            duration_ms,
            payload_json,
            result_json,
            error_text,
            created_at,
            updated_at
        ) VALUES (
            :pipeline_name,
            :stage_name,
            :execution_key,
            :stage_order,
            :trigger_source,
            :airflow_dag_id,
            :airflow_dag_run_id,
            :airflow_task_id,
            :run_id,
            :report_id,
            :stage_status,
            :lock_name,
            :lock_backend,
            :lock_key,
            :idempotency_key,
            :started_at,
            :completed_at,
            :duration_ms,
            CAST(:payload_json AS JSONB),
            CAST(:result_json AS JSONB),
            :error_text,
            NOW(),
            NOW()
        )
        ON CONFLICT (pipeline_name, stage_name, execution_key)
        DO UPDATE SET
            stage_order = EXCLUDED.stage_order,
            trigger_source = EXCLUDED.trigger_source,
            airflow_dag_id = EXCLUDED.airflow_dag_id,
            airflow_dag_run_id = EXCLUDED.airflow_dag_run_id,
            airflow_task_id = EXCLUDED.airflow_task_id,
            run_id = COALESCE(EXCLUDED.run_id, {_SCHEMA}.ops_stage_runs.run_id),
            report_id = COALESCE(EXCLUDED.report_id, {_SCHEMA}.ops_stage_runs.report_id),
            stage_status = EXCLUDED.stage_status,
            lock_name = EXCLUDED.lock_name,
            lock_backend = EXCLUDED.lock_backend,
            lock_key = EXCLUDED.lock_key,
            idempotency_key = EXCLUDED.idempotency_key,
            started_at = COALESCE({_SCHEMA}.ops_stage_runs.started_at, EXCLUDED.started_at),
            completed_at = EXCLUDED.completed_at,
            duration_ms = COALESCE(EXCLUDED.duration_ms, {_SCHEMA}.ops_stage_runs.duration_ms),
            payload_json = EXCLUDED.payload_json,
            result_json = EXCLUDED.result_json,
            error_text = EXCLUDED.error_text,
            updated_at = NOW()
        """)
    params = {
        "pipeline_name": str(pipeline_name),
        "stage_name": str(stage_name),
        "execution_key": str(execution_key),
        "stage_order": int(stage_order) if stage_order is not None else None,
        "trigger_source": _normalize_trigger_source(trigger_source),
        "airflow_dag_id": _normalize_optional_text(airflow_dag_id),
        "airflow_dag_run_id": _normalize_optional_text(airflow_dag_run_id),
        "airflow_task_id": _normalize_optional_text(airflow_task_id),
        "run_id": _normalize_optional_text(run_id),
        "report_id": _normalize_optional_text(report_id),
        "stage_status": _normalize_stage_status(stage_status),
        "lock_name": _normalize_optional_text(lock_name),
        "lock_backend": _normalize_optional_text(lock_backend),
        "lock_key": _normalize_optional_text(lock_key),
        "idempotency_key": _normalize_optional_text(idempotency_key),
        "started_at": started_ts,
        "completed_at": completed_ts,
        "duration_ms": duration_ms,
        "payload_json": json.dumps(
            dict(payload or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
        "result_json": json.dumps(
            dict(result or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
        "error_text": _normalize_optional_text(error_text),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
        return True
    except Exception:  # pragma: no cover - monitoring must stay non-brittle
        logger.warning(
            "cw2_monitoring: failed to persist stage run pipeline=%s stage=%s execution_key=%s",
            pipeline_name,
            stage_name,
            execution_key,
            exc_info=True,
        )
        return False


def record_ops_event(
    *,
    engine: Engine,
    event_id: Optional[str],
    event_type: str,
    producer_component: str,
    payload: Mapping[str, Any],
    topic_key: Optional[str] = None,
    topic_name: Optional[str] = None,
    run_id: Optional[str] = None,
    symbol: Optional[str] = None,
    severity: str = "info",
    publish_status: str = "recorded",
    event_time: Any = None,
) -> None:
    """Persist a mirrored operational event without breaking the main flow."""

    sql = text(f"""
        INSERT INTO {_SCHEMA}.ops_event_log (
            event_id,
            event_time,
            event_type,
            producer_component,
            topic_key,
            topic_name,
            run_id,
            symbol,
            severity,
            publish_status,
            payload_json,
            created_at,
            updated_at
        ) VALUES (
            :event_id,
            :event_time,
            :event_type,
            :producer_component,
            :topic_key,
            :topic_name,
            :run_id,
            :symbol,
            :severity,
            :publish_status,
            CAST(:payload_json AS JSONB),
            NOW(),
            NOW()
        )
        ON CONFLICT (event_id, producer_component)
        DO UPDATE SET
            event_time = EXCLUDED.event_time,
            topic_key = EXCLUDED.topic_key,
            topic_name = EXCLUDED.topic_name,
            run_id = EXCLUDED.run_id,
            symbol = EXCLUDED.symbol,
            severity = EXCLUDED.severity,
            publish_status = EXCLUDED.publish_status,
            payload_json = EXCLUDED.payload_json,
            updated_at = NOW()
        """)
    params = {
        "event_id": str(event_id or _derive_event_id(event_type, payload)),
        "event_time": _normalize_event_time(
            event_time
            or payload.get("created_at_utc")
            or payload.get("event_date")
            or payload.get("trigger_date")
        ),
        "event_type": str(event_type),
        "producer_component": str(producer_component),
        "topic_key": _normalize_optional_text(topic_key),
        "topic_name": _normalize_optional_text(topic_name),
        "run_id": _normalize_optional_text(run_id or payload.get("run_id")),
        "symbol": _normalize_optional_text(symbol or payload.get("symbol")),
        "severity": _normalize_severity(severity),
        "publish_status": _normalize_publish_status(publish_status),
        "payload_json": json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, default=_json_default
        ),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
    except Exception:  # pragma: no cover - monitoring must stay non-brittle
        logger.warning(
            "cw2_monitoring: failed to persist ops event event_type=%s producer=%s",
            event_type,
            producer_component,
            exc_info=True,
        )


def record_kafka_consumer_ack(
    *,
    engine: Engine,
    event_id: str,
    topic_name: str,
    consumer_group: str,
    consumer_component: str,
    kafka_partition: int,
    kafka_offset: int,
    payload: Mapping[str, Any],
    message_key: Optional[str] = None,
    headers: Optional[Mapping[str, Any]] = None,
    event_type: Optional[str] = None,
    run_id: Optional[str] = None,
    symbol: Optional[str] = None,
    ack_status: str = "consumed",
    retry_count: int = 0,
    last_error: Optional[str] = None,
    consumed_at: Any = None,
    processed_at: Any = None,
) -> bool:
    """Upsert one consumer-side acknowledgement record for a Kafka event."""

    sql = text(f"""
        INSERT INTO {_SCHEMA}.ops_kafka_consumer_ack (
            event_id,
            topic_name,
            consumer_group,
            consumer_component,
            kafka_partition,
            kafka_offset,
            message_key,
            event_type,
            run_id,
            symbol,
            consumed_at,
            processed_at,
            ack_status,
            retry_count,
            last_error,
            payload_json,
            headers_json,
            created_at,
            updated_at
        ) VALUES (
            :event_id,
            :topic_name,
            :consumer_group,
            :consumer_component,
            :kafka_partition,
            :kafka_offset,
            :message_key,
            :event_type,
            :run_id,
            :symbol,
            :consumed_at,
            :processed_at,
            :ack_status,
            :retry_count,
            :last_error,
            CAST(:payload_json AS JSONB),
            CAST(:headers_json AS JSONB),
            NOW(),
            NOW()
        )
        ON CONFLICT (topic_name, consumer_group, kafka_partition, kafka_offset)
        DO UPDATE SET
            event_id = EXCLUDED.event_id,
            consumer_component = EXCLUDED.consumer_component,
            message_key = EXCLUDED.message_key,
            event_type = EXCLUDED.event_type,
            run_id = EXCLUDED.run_id,
            symbol = EXCLUDED.symbol,
            consumed_at = LEAST(
                {_SCHEMA}.ops_kafka_consumer_ack.consumed_at,
                EXCLUDED.consumed_at
            ),
            processed_at = COALESCE(EXCLUDED.processed_at, {_SCHEMA}.ops_kafka_consumer_ack.processed_at),
            ack_status = EXCLUDED.ack_status,
            retry_count = GREATEST({_SCHEMA}.ops_kafka_consumer_ack.retry_count, EXCLUDED.retry_count),
            last_error = EXCLUDED.last_error,
            payload_json = EXCLUDED.payload_json,
            headers_json = EXCLUDED.headers_json,
            updated_at = NOW()
        """)
    params = {
        "event_id": str(event_id),
        "topic_name": str(topic_name),
        "consumer_group": str(consumer_group),
        "consumer_component": str(consumer_component),
        "kafka_partition": int(kafka_partition),
        "kafka_offset": int(kafka_offset),
        "message_key": _normalize_optional_text(message_key),
        "event_type": _normalize_optional_text(event_type or payload.get("event_type")),
        "run_id": _normalize_optional_text(run_id or payload.get("run_id")),
        "symbol": _normalize_optional_text(symbol or payload.get("symbol")),
        "consumed_at": _normalize_event_time(
            consumed_at or payload.get("consumed_at") or datetime.now(timezone.utc)
        ),
        "processed_at": (_normalize_event_time(processed_at) if processed_at is not None else None),
        "ack_status": _normalize_ack_status(ack_status),
        "retry_count": max(0, int(retry_count)),
        "last_error": _normalize_optional_text(last_error),
        "payload_json": json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, default=_json_default
        ),
        "headers_json": json.dumps(
            dict(headers or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
        return True
    except Exception:  # pragma: no cover - monitoring must stay non-brittle
        logger.warning(
            "cw2_monitoring: failed to persist kafka consumer ack topic=%s group=%s partition=%s offset=%s",
            topic_name,
            consumer_group,
            kafka_partition,
            kafka_offset,
            exc_info=True,
        )
        return False


def record_kafka_dead_letter(
    *,
    engine: Engine,
    event_id: str,
    topic_name: str,
    consumer_group: str,
    consumer_component: str,
    kafka_partition: int,
    kafka_offset: int,
    dead_letter_reason: str,
    payload: Mapping[str, Any],
    message_key: Optional[str] = None,
    headers: Optional[Mapping[str, Any]] = None,
    event_type: Optional[str] = None,
    run_id: Optional[str] = None,
    symbol: Optional[str] = None,
    error_text: Optional[str] = None,
) -> bool:
    """Persist one SQL-backed dead-letter record."""

    sql = text(f"""
        INSERT INTO {_SCHEMA}.ops_kafka_dead_letter (
            event_id,
            topic_name,
            consumer_group,
            consumer_component,
            kafka_partition,
            kafka_offset,
            message_key,
            event_type,
            run_id,
            symbol,
            dead_letter_reason,
            error_text,
            payload_json,
            headers_json,
            created_at
        ) VALUES (
            :event_id,
            :topic_name,
            :consumer_group,
            :consumer_component,
            :kafka_partition,
            :kafka_offset,
            :message_key,
            :event_type,
            :run_id,
            :symbol,
            :dead_letter_reason,
            :error_text,
            CAST(:payload_json AS JSONB),
            CAST(:headers_json AS JSONB),
            NOW()
        )
        ON CONFLICT (topic_name, consumer_group, kafka_partition, kafka_offset)
        DO UPDATE SET
            event_id = EXCLUDED.event_id,
            consumer_component = EXCLUDED.consumer_component,
            message_key = EXCLUDED.message_key,
            event_type = EXCLUDED.event_type,
            run_id = EXCLUDED.run_id,
            symbol = EXCLUDED.symbol,
            dead_letter_reason = EXCLUDED.dead_letter_reason,
            error_text = EXCLUDED.error_text,
            payload_json = EXCLUDED.payload_json,
            headers_json = EXCLUDED.headers_json,
            created_at = NOW()
        """)
    params = {
        "event_id": str(event_id),
        "topic_name": str(topic_name),
        "consumer_group": str(consumer_group),
        "consumer_component": str(consumer_component),
        "kafka_partition": int(kafka_partition),
        "kafka_offset": int(kafka_offset),
        "message_key": _normalize_optional_text(message_key),
        "event_type": _normalize_optional_text(event_type or payload.get("event_type")),
        "run_id": _normalize_optional_text(run_id or payload.get("run_id")),
        "symbol": _normalize_optional_text(symbol or payload.get("symbol")),
        "dead_letter_reason": str(dead_letter_reason or "processing_failed"),
        "error_text": _normalize_optional_text(error_text),
        "payload_json": json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, default=_json_default
        ),
        "headers_json": json.dumps(
            dict(headers or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
        return True
    except Exception:  # pragma: no cover - monitoring must stay non-brittle
        logger.warning(
            "cw2_monitoring: failed to persist kafka dead letter topic=%s group=%s partition=%s offset=%s",
            topic_name,
            consumer_group,
            kafka_partition,
            kafka_offset,
            exc_info=True,
        )
        return False


def record_kafka_lag_snapshot(
    *,
    engine: Engine,
    consumer_group: str,
    topic_name: str,
    partition_id: int,
    committed_offset: Optional[int],
    high_watermark: int,
    lag: int,
    lag_status: str = "ok",
    sampled_at: Any = None,
) -> bool:
    """Persist one Kafka lag snapshot row."""

    sql = text(f"""
        INSERT INTO {_SCHEMA}.ops_kafka_lag_snapshots (
            consumer_group,
            topic_name,
            partition_id,
            committed_offset,
            high_watermark,
            lag,
            lag_status,
            sampled_at
        ) VALUES (
            :consumer_group,
            :topic_name,
            :partition_id,
            :committed_offset,
            :high_watermark,
            :lag,
            :lag_status,
            :sampled_at
        )
        """)
    params = {
        "consumer_group": str(consumer_group),
        "topic_name": str(topic_name),
        "partition_id": int(partition_id),
        "committed_offset": (None if committed_offset is None else max(0, int(committed_offset))),
        "high_watermark": max(0, int(high_watermark)),
        "lag": max(0, int(lag)),
        "lag_status": _normalize_lag_status(lag_status),
        "sampled_at": _normalize_event_time(sampled_at),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
        return True
    except Exception:  # pragma: no cover - monitoring must stay non-brittle
        logger.warning(
            "cw2_monitoring: failed to persist kafka lag snapshot topic=%s group=%s partition=%s",
            topic_name,
            consumer_group,
            partition_id,
            exc_info=True,
        )
        return False


def record_health_snapshot(
    *,
    engine: Engine,
    snapshot_type: str,
    component: str,
    status: str,
    summary: Mapping[str, Any],
    details: Optional[Mapping[str, Any]] = None,
    run_date: Any = None,
) -> str:
    """Persist one operational health snapshot and return its snapshot id."""

    snapshot_id = str(uuid.uuid4())
    sql = text(f"""
        INSERT INTO {_SCHEMA}.ops_health_snapshots (
            ops_health_snapshot_id,
            snapshot_type,
            component,
            run_date,
            status,
            summary_json,
            details_json
        ) VALUES (
            :snapshot_id,
            :snapshot_type,
            :component,
            :run_date,
            :status,
            CAST(:summary_json AS JSONB),
            CAST(:details_json AS JSONB)
        )
        """)
    params = {
        "snapshot_id": snapshot_id,
        "snapshot_type": str(snapshot_type),
        "component": str(component),
        "run_date": _normalize_run_date(run_date),
        "status": _normalize_health_status(status),
        "summary_json": json.dumps(
            dict(summary), ensure_ascii=False, sort_keys=True, default=_json_default
        ),
        "details_json": json.dumps(
            dict(details or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        ),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
    except Exception:  # pragma: no cover - monitoring must stay non-brittle
        logger.warning(
            "cw2_monitoring: failed to persist health snapshot snapshot_type=%s component=%s",
            snapshot_type,
            component,
            exc_info=True,
        )
    return snapshot_id


def build_kafka_topic_name(
    config: Optional[Mapping[str, Any]],
    *,
    topic_key: str,
    default_topic: str,
    default_client_id: str,
) -> str:
    """Resolve the effective Kafka topic name used by the current config."""

    resolved = resolve_kafka_config(config, default_client_id=default_client_id)
    return str(resolved.topics.get(topic_key, default_topic))


def summarize_recent_monitoring(engine: Engine, *, lookback_hours: int = 24) -> Dict[str, Any]:
    """Return a compact SQL-backed operational summary for the recent window."""

    safe_lookback = max(1, int(lookback_hours))
    counts_sql = text(f"""
        SELECT event_type, publish_status, COUNT(*) AS event_count
        FROM {_SCHEMA}.ops_event_log
        WHERE event_time >= NOW() - INTERVAL '{safe_lookback} hours'
        GROUP BY event_type, publish_status
        ORDER BY event_type, publish_status
        """)
    latest_snapshot_sql = text(f"""
        SELECT component, snapshot_type, status, created_at
        FROM {_SCHEMA}.ops_health_snapshots
        ORDER BY created_at DESC
        LIMIT 1
        """)
    consumer_counts_sql = text(f"""
        SELECT ack_status, COUNT(*) AS event_count
        FROM {_SCHEMA}.ops_kafka_consumer_ack
        WHERE consumed_at >= NOW() - INTERVAL '{safe_lookback} hours'
        GROUP BY ack_status
        ORDER BY ack_status
        """)
    dead_letter_sql = text(f"""
        SELECT COUNT(*) AS dead_letter_count
        FROM {_SCHEMA}.ops_kafka_dead_letter
        WHERE created_at >= NOW() - INTERVAL '{safe_lookback} hours'
        """)
    latest_lag_sql = text(f"""
        WITH latest_sample AS (
            SELECT MAX(sampled_at) AS sampled_at
            FROM {_SCHEMA}.ops_kafka_lag_snapshots
        )
        SELECT consumer_group,
               MAX(sampled_at) AS sampled_at,
               COUNT(*) AS partition_count,
               MAX(lag) AS max_lag,
               SUM(lag) AS total_lag
        FROM {_SCHEMA}.ops_kafka_lag_snapshots
        WHERE sampled_at = (SELECT sampled_at FROM latest_sample)
        GROUP BY consumer_group
        ORDER BY consumer_group
        """)
    try:
        with engine.connect() as conn:
            event_rows = [dict(row._mapping) for row in conn.execute(counts_sql)]
            consumer_rows = [dict(row._mapping) for row in conn.execute(consumer_counts_sql)]
            dead_letter_row = conn.execute(dead_letter_sql).mappings().first()
            lag_rows = [dict(row._mapping) for row in conn.execute(latest_lag_sql)]
            latest_snapshot = conn.execute(latest_snapshot_sql).mappings().first()
    except Exception:  # pragma: no cover - depends on runtime DB state
        logger.warning("cw2_monitoring: failed to summarize monitoring state", exc_info=True)
        return {
            "lookback_hours": safe_lookback,
            "recent_event_counts": [],
            "recent_consumer_ack_counts": [],
            "recent_dead_letter_count": 0,
            "latest_kafka_lag": [],
            "latest_health_snapshot": None,
        }

    return {
        "lookback_hours": safe_lookback,
        "recent_event_counts": event_rows,
        "recent_consumer_ack_counts": consumer_rows,
        "recent_dead_letter_count": int((dead_letter_row or {}).get("dead_letter_count") or 0),
        "latest_kafka_lag": [
            {
                **row,
                "sampled_at": (
                    row["sampled_at"].isoformat()
                    if isinstance(row.get("sampled_at"), datetime)
                    else row.get("sampled_at")
                ),
            }
            for row in lag_rows
        ],
        "latest_health_snapshot": (dict(latest_snapshot) if latest_snapshot is not None else None),
    }


def summarize_kafka_event_audit(
    engine: Engine,
    *,
    kafka_config: Optional[Mapping[str, Any]] = None,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """Summarize producer/consumer Kafka audit state for one consumer group."""

    safe_lookback = max(1, int(lookback_hours))
    kafka_cfg = dict((kafka_config or {}).get("kafka") or {})
    audit_cfg = dict(kafka_cfg.get("audit_consumer") or {})
    kafka_enabled = _coerce_boolish(kafka_cfg.get("enabled"), default=False)
    audit_enabled = _coerce_boolish(audit_cfg.get("enabled"), default=True)
    consumer_group = (
        str(audit_cfg.get("consumer_group") or "team_pearson_cw2_audit").strip()
        or "team_pearson_cw2_audit"
    )
    lag_warning_threshold = max(0, int(audit_cfg.get("lag_warning_threshold", 100)))
    freshness_warning_minutes = max(1, int(audit_cfg.get("freshness_warning_minutes", 60)))
    pending_grace_minutes = max(0, int(audit_cfg.get("pending_grace_minutes", 2)))
    orphan_reconcile_minutes = max(
        pending_grace_minutes + 1,
        int(audit_cfg.get("orphan_reconcile_minutes", 60)),
    )
    if not kafka_enabled:
        return {
            "consumer_group": consumer_group,
            "status": "disabled",
            "processing_scope": "kafka_disabled",
            "external_executor_present": False,
            "confirms_external_execution": False,
            "published_count": 0,
            "consumed_count": 0,
            "processed_count": 0,
            "failed_count": 0,
            "dead_letter_count": 0,
            "pending_count": 0,
            "latest_lag_sampled_at": None,
            "max_lag": 0,
            "total_lag": 0,
        }
    if not audit_enabled:
        return {
            "consumer_group": consumer_group,
            "status": "audit_disabled",
            "processing_scope": "audit_consumer_disabled",
            "external_executor_present": False,
            "confirms_external_execution": False,
            "published_count": 0,
            "consumed_count": 0,
            "processed_count": 0,
            "failed_count": 0,
            "dead_letter_count": 0,
            "pending_count": 0,
            "latest_lag_sampled_at": None,
            "max_lag": 0,
            "total_lag": 0,
        }

    published_sql = text(f"""
        SELECT COUNT(*) AS published_count
        FROM (
            SELECT DISTINCT event_id
            FROM {_SCHEMA}.ops_event_log
            WHERE publish_status = 'published'
              AND event_time >= NOW() - INTERVAL '{safe_lookback} hours'
        ) AS published_events
        """)
    ack_sql = text(f"""
        SELECT ack_status, COUNT(*) AS event_count
        FROM {_SCHEMA}.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{safe_lookback} hours'
        GROUP BY ack_status
        ORDER BY ack_status
        """)
    component_sql = text(f"""
        SELECT consumer_component, MAX(updated_at) AS last_seen_at
        FROM {_SCHEMA}.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{safe_lookback} hours'
        GROUP BY consumer_component
        ORDER BY MAX(updated_at) DESC, consumer_component
        """)
    pending_sql = text(f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM {_SCHEMA}.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS pending_count
        FROM {_SCHEMA}.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{safe_lookback} hours'
          AND e.event_time < NOW() - INTERVAL '{pending_grace_minutes} minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """)
    stale_pending_sql = text(f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM {_SCHEMA}.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS stale_pending_count
        FROM {_SCHEMA}.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{safe_lookback} hours'
          AND e.event_time < NOW() - INTERVAL '{orphan_reconcile_minutes} minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """)
    self_audit_pending_sql = text(f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM {_SCHEMA}.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS self_audit_pending_count
        FROM {_SCHEMA}.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_type = 'cw2_scheduler_stage'
          AND e.producer_component = 'cw2.scheduler.kafka_event_audit'
          AND e.event_time >= NOW() - INTERVAL '{safe_lookback} hours'
          AND e.event_time < NOW() - INTERVAL '{pending_grace_minutes} minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """)
    dead_letter_sql = text(f"""
        SELECT COUNT(*) AS dead_letter_count
        FROM {_SCHEMA}.ops_kafka_dead_letter
        WHERE consumer_group = :consumer_group
          AND created_at >= NOW() - INTERVAL '{safe_lookback} hours'
        """)
    latest_lag_sql = text(f"""
        WITH latest_sample AS (
            SELECT MAX(sampled_at) AS sampled_at
            FROM {_SCHEMA}.ops_kafka_lag_snapshots
            WHERE consumer_group = :consumer_group
        )
        SELECT MAX(sampled_at) AS sampled_at,
               COUNT(*) AS partition_count,
               MAX(lag) AS max_lag,
               SUM(lag) AS total_lag,
               SUM(CASE WHEN lag_status = 'warning' THEN 1 ELSE 0 END) AS warning_partitions,
               SUM(CASE WHEN lag_status = 'error' THEN 1 ELSE 0 END) AS error_partitions
        FROM {_SCHEMA}.ops_kafka_lag_snapshots
        WHERE consumer_group = :consumer_group
          AND sampled_at = (SELECT sampled_at FROM latest_sample)
        """)
    try:
        with engine.connect() as conn:
            published_row = conn.execute(published_sql).mappings().first() or {}
            ack_rows = conn.execute(ack_sql, {"consumer_group": consumer_group}).mappings().all()
            component_rows = (
                conn.execute(component_sql, {"consumer_group": consumer_group}).mappings().all()
            )
            pending_row = (
                conn.execute(pending_sql, {"consumer_group": consumer_group}).mappings().first()
                or {}
            )
            stale_pending_row = (
                conn.execute(stale_pending_sql, {"consumer_group": consumer_group})
                .mappings()
                .first()
                or {}
            )
            self_audit_pending_row = (
                conn.execute(self_audit_pending_sql, {"consumer_group": consumer_group})
                .mappings()
                .first()
                or {}
            )
            dead_letter_row = (
                conn.execute(dead_letter_sql, {"consumer_group": consumer_group}).mappings().first()
                or {}
            )
            lag_row = (
                conn.execute(latest_lag_sql, {"consumer_group": consumer_group}).mappings().first()
                or {}
            )
    except Exception:  # pragma: no cover - depends on runtime DB state
        logger.warning("cw2_monitoring: failed to summarize kafka event audit", exc_info=True)
        return {
            "consumer_group": consumer_group,
            "status": "error",
            "processing_scope": "internal_audit_consumer",
            "external_executor_present": False,
            "confirms_external_execution": False,
            "published_count": 0,
            "consumed_count": 0,
            "processed_count": 0,
            "failed_count": 0,
            "dead_letter_count": 0,
            "pending_count": 0,
            "raw_pending_count": 0,
            "reconciled_orphan_count": 0,
            "reconciled_self_audit_count": 0,
            "latest_lag_sampled_at": None,
            "max_lag": 0,
            "total_lag": 0,
        }

    ack_counts = {
        str(row.get("ack_status") or ""): int(row.get("event_count") or 0) for row in ack_rows
    }
    consumer_components = [
        str(row.get("consumer_component") or "").strip()
        for row in component_rows
        if str(row.get("consumer_component") or "").strip()
    ]
    daemon_present = "cw2.kafka_audit_daemon" in consumer_components
    processing_scope = "dedicated_audit_consumer" if daemon_present else "internal_audit_consumer"
    published_count = int(published_row.get("published_count") or 0)
    consumed_count = sum(ack_counts.values())
    processed_count = int(ack_counts.get("processed") or 0)
    failed_count = int(ack_counts.get("failed") or 0)
    dead_letter_count = int(dead_letter_row.get("dead_letter_count") or 0)
    raw_pending_count = int(pending_row.get("pending_count") or 0)
    stale_pending_count = int(stale_pending_row.get("stale_pending_count") or 0)
    self_audit_pending_count = int(self_audit_pending_row.get("self_audit_pending_count") or 0)
    latest_lag_sampled_at = lag_row.get("sampled_at")
    max_lag = int(lag_row.get("max_lag") or 0)
    total_lag = int(lag_row.get("total_lag") or 0)
    reconciled_orphan_count = 0
    reconciled_self_audit_count = 0
    if (
        consumer_components
        and latest_lag_sampled_at is not None
        and max_lag == 0
        and dead_letter_count == 0
    ):
        reconciled_orphan_count = min(raw_pending_count, stale_pending_count)
        remaining_after_orphans = max(0, raw_pending_count - reconciled_orphan_count)
        reconciled_self_audit_count = min(
            remaining_after_orphans,
            self_audit_pending_count,
        )
    pending_count = max(
        0,
        raw_pending_count - reconciled_orphan_count - reconciled_self_audit_count,
    )

    if latest_lag_sampled_at is None and published_count == 0 and consumed_count == 0:
        status = "no_recent_activity"
    elif latest_lag_sampled_at is None:
        status = "missing_lag_snapshot"
    else:
        sampled_at_dt = _normalize_event_time(latest_lag_sampled_at)
        age_minutes = (
            datetime.now(timezone.utc) - sampled_at_dt.astimezone(timezone.utc)
        ).total_seconds() / 60.0
        if dead_letter_count > 0:
            status = "warning"
        elif max_lag > lag_warning_threshold or pending_count > 0:
            status = "warning"
        elif age_minutes > float(freshness_warning_minutes):
            status = "warning"
        else:
            status = "ok"

    return {
        "consumer_group": consumer_group,
        "status": status,
        "processing_scope": processing_scope,
        "external_executor_present": False,
        "confirms_external_execution": False,
        "consumer_components": consumer_components,
        "published_count": published_count,
        "consumed_count": consumed_count,
        "processed_count": processed_count,
        "failed_count": failed_count,
        "dead_letter_count": dead_letter_count,
        "pending_count": pending_count,
        "raw_pending_count": raw_pending_count,
        "reconciled_orphan_count": reconciled_orphan_count,
        "reconciled_self_audit_count": reconciled_self_audit_count,
        "ack_counts": ack_counts,
        "latest_lag_sampled_at": (
            latest_lag_sampled_at.isoformat()
            if isinstance(latest_lag_sampled_at, datetime)
            else latest_lag_sampled_at
        ),
        "max_lag": max_lag,
        "total_lag": total_lag,
    }


def run_monitor_from_config(
    *,
    cw1_config_path: str,
    cw2_config_path: str,
    db_engine: Engine | None = None,
) -> Dict[str, Any]:
    """Persist one operational health snapshot based on the current readiness audit."""

    from team_Pearson.coursework_two.modules.backtest.engine import _load_shared_db_engine

    from .audit import run_audit_from_config

    engine = db_engine or _load_shared_db_engine()
    ensure_ops_monitoring_schema(engine)
    audit_report = run_audit_from_config(
        cw1_config_path=cw1_config_path,
        cw2_config_path=cw2_config_path,
        db_engine=engine,
    )
    readiness = dict(audit_report.get("readiness") or {})
    snapshot_id = record_health_snapshot(
        engine=engine,
        snapshot_type="readiness_audit",
        component="platform",
        status=str(readiness.get("overall_status") or "partial"),
        run_date=datetime.now(timezone.utc).date(),
        summary={
            "overall_status": readiness.get("overall_status"),
            "core_sql_ready": readiness.get("core_sql_ready"),
            "feature_pipeline_ready": readiness.get("feature_pipeline_ready"),
            "storage_ready": readiness.get("storage_ready"),
            "kafka_ready": readiness.get("kafka_ready"),
            "kafka_event_audit_ready": readiness.get("kafka_event_audit_ready"),
            "backtest_ready": readiness.get("backtest_ready"),
        },
        details=audit_report,
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ops_health_snapshot_id": snapshot_id,
        "audit": audit_report,
        "recent_monitoring": summarize_recent_monitoring(engine),
    }


def _derive_event_id(event_type: str, payload: Mapping[str, Any]) -> str:
    run_id = _normalize_optional_text(payload.get("run_id")) or "na"
    symbol = _normalize_optional_text(payload.get("symbol")) or "na"
    time_value = str(
        payload.get("created_at_utc")
        or payload.get("event_date")
        or payload.get("trigger_date")
        or datetime.now(timezone.utc).isoformat()
    )
    return f"{event_type}:{run_id}:{symbol}:{time_value}"


def _normalize_event_time(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    text_value = str(value).strip()
    if not text_value:
        return datetime.now(timezone.utc)
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text_value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        if len(text_value) == 10:
            return datetime.combine(date.fromisoformat(text_value), time.min, tzinfo=timezone.utc)
        return datetime.now(timezone.utc)


def _normalize_run_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value).strip()
    if not text_value:
        return None
    return text_value[:10]


def _normalize_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _normalize_severity(value: str) -> str:
    normalized = str(value or "info").strip().lower()
    if normalized in {"critical", "warning", "info"}:
        return normalized
    if normalized in {"high", "urgent"}:
        return "warning"
    return "info"


def _normalize_publish_status(value: str) -> str:
    normalized = str(value or "recorded").strip().lower()
    if normalized in {"recorded", "published", "suppressed", "disabled"}:
        return normalized
    return "recorded"


def _normalize_trigger_source(value: str) -> str:
    normalized = str(value or "manual").strip().lower()
    if normalized in {"manual", "airflow", "script", "api"}:
        return normalized
    return "manual"


def _normalize_pipeline_status(value: str) -> str:
    normalized = str(value or "running").strip().lower()
    if normalized in {"queued", "running", "completed", "failed", "skipped", "warning"}:
        return normalized
    return "running"


def _normalize_stage_status(value: str) -> str:
    normalized = str(value or "started").strip().lower()
    if normalized in {
        "started",
        "running",
        "completed",
        "failed",
        "skipped",
        "warning",
    }:
        return normalized
    return "started"


def _normalize_ack_status(value: str) -> str:
    normalized = str(value or "consumed").strip().lower()
    if normalized in {"consumed", "processed", "failed", "dead_lettered"}:
        return normalized
    return "consumed"


def _normalize_lag_status(value: str) -> str:
    normalized = str(value or "ok").strip().lower()
    if normalized in {"ok", "warning", "error"}:
        return normalized
    return "ok"


def _normalize_health_status(value: str) -> str:
    normalized = str(value or "partial").strip().lower()
    if normalized in {"ok", "partial", "error", "warning"}:
        return normalized
    if normalized == "ready":
        return "ok"
    return "partial"


def _coerce_boolish(value: Any, *, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _duration_ms(started_at: Optional[datetime], completed_at: Optional[datetime]) -> Optional[int]:
    if started_at is None or completed_at is None:
        return None
    try:
        delta = completed_at - started_at
    except Exception:
        return None
    return max(0, int(delta.total_seconds() * 1000.0))


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
