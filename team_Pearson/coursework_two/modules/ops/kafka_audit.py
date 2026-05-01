from __future__ import annotations

"""Kafka end-to-end audit consumer for CW2 event topics."""

import inspect
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

try:
    from team_Pearson.coursework_one.modules.utils.kafka import resolve_kafka_config
    from team_Pearson.coursework_two.modules.backtest.engine import _load_shared_db_engine
    from team_Pearson.coursework_two.modules.ops.monitoring import (
        ensure_ops_monitoring_schema,
        record_health_snapshot,
        record_kafka_consumer_ack,
        record_kafka_dead_letter,
        record_kafka_lag_snapshot,
        summarize_kafka_event_audit,
    )
    from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config
except ModuleNotFoundError:  # pragma: no cover - import-path fallback
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_one.modules.utils.kafka import resolve_kafka_config
    from team_Pearson.coursework_two.modules.backtest.engine import _load_shared_db_engine
    from team_Pearson.coursework_two.modules.ops.monitoring import (
        ensure_ops_monitoring_schema,
        record_health_snapshot,
        record_kafka_consumer_ack,
        record_kafka_dead_letter,
        record_kafka_lag_snapshot,
        summarize_kafka_event_audit,
    )
    from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config

logger = logging.getLogger(__name__)


def consume_kafka_events_with_audit(
    *,
    kafka_config: Mapping[str, Any],
    engine: Engine,
    max_messages: Optional[int] = None,
    poll_timeout_ms: Optional[int] = None,
    max_idle_polls: Optional[int] = None,
) -> Dict[str, Any]:
    """Consume configured Kafka topics and persist consumer-side audit state."""

    ensure_ops_monitoring_schema(engine)
    resolved = resolve_kafka_config(kafka_config, default_client_id="team_pearson_cw2_audit")
    audit_cfg = _resolve_audit_settings(kafka_config)
    topics = _resolve_audit_topics(resolved, audit_cfg["topic_keys"])

    summary: Dict[str, Any] = {
        "status": "skipped",
        "reason": "kafka disabled",
        "consumer_group": audit_cfg["consumer_group"],
        "consumer_component": audit_cfg["consumer_component"],
        "topics": list(topics),
        "consumed_count": 0,
        "processed_count": 0,
        "failed_count": 0,
        "dead_letter_count": 0,
        "committed_count": 0,
        "lag_snapshot_count": 0,
    }
    if not resolved.enabled:
        return summary
    if not audit_cfg["enabled"]:
        summary.update({"status": "skipped", "reason": "kafka audit consumer disabled"})
        return summary
    if not topics:
        summary.update({"status": "warning", "reason": "no audit topics configured"})
        return summary

    try:
        consumer = _build_consumer(
            resolved_bootstrap=list(resolved.bootstrap_servers),
            client_id=f"{resolved.client_id}_audit",
            consumer_group=audit_cfg["consumer_group"],
            max_batch_messages=int(max_messages or audit_cfg["max_batch_messages"]),
        )
    except Exception as exc:  # pragma: no cover - runtime dependency / broker state
        if resolved.required:
            raise
        logger.warning("cw2_kafka_audit: consumer unavailable error=%r", exc)
        summary.update({"status": "warning", "reason": f"consumer unavailable: {exc!r}"})
        return summary

    processed_count = 0
    failed_count = 0
    dead_letter_count = 0
    committed_count = 0
    consumed_count = 0
    idle_polls = 0
    max_batch = int(max_messages or audit_cfg["max_batch_messages"])
    poll_ms = int(poll_timeout_ms or audit_cfg["poll_timeout_ms"])
    max_idle = int(max_idle_polls or audit_cfg["max_idle_polls"])

    try:
        consumer.subscribe(topics)
        assignment_wait_polls = max(3, min(10, max_idle))
        assignment_polls = 0
        while not consumer.assignment() and assignment_polls < assignment_wait_polls:
            consumer.poll(timeout_ms=poll_ms, max_records=1)
            assignment_polls += 1
        while consumed_count < max_batch and idle_polls < max_idle:
            polled = consumer.poll(
                timeout_ms=poll_ms,
                max_records=max(1, max_batch - consumed_count),
            )
            if not polled:
                idle_polls += 1
                continue
            idle_polls = 0

            for topic_partition, records in polled.items():
                stop_partition = False
                for record in records:
                    if consumed_count >= max_batch:
                        break
                    outcome = _process_kafka_record(
                        engine=engine,
                        record=record,
                        consumer_group=audit_cfg["consumer_group"],
                        consumer_component=audit_cfg["consumer_component"],
                        max_retries_per_message=audit_cfg["max_retries_per_message"],
                    )
                    consumed_count += 1
                    if outcome["status"] == "processed":
                        processed_count += 1
                    elif outcome["status"] == "failed":
                        failed_count += 1
                    elif outcome["status"] == "dead_lettered":
                        dead_letter_count += 1

                    commit_offset = outcome.get("commit_offset")
                    if commit_offset is not None:
                        _commit_offset(
                            consumer,
                            topic=record.topic,
                            partition=record.partition,
                            offset=int(commit_offset),
                        )
                        committed_count += 1
                    elif outcome["status"] == "failed":
                        stop_partition = True
                        break
                if stop_partition:
                    continue

        lag_report = snapshot_kafka_consumer_lag(
            kafka_config=kafka_config,
            engine=engine,
            consumer_group=audit_cfg["consumer_group"],
            lag_warning_threshold=audit_cfg["lag_warning_threshold"],
            topics=topics,
        )
    finally:
        consumer.close()

    audit_summary = summarize_kafka_event_audit(
        engine,
        kafka_config=kafka_config,
        lookback_hours=24,
    )
    summary.update(
        {
            "status": "ok" if dead_letter_count == 0 else "warning",
            "reason": None,
            "consumed_count": consumed_count,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "dead_letter_count": dead_letter_count,
            "committed_count": committed_count,
            "lag_snapshot_count": int(lag_report.get("lag_snapshot_count") or 0),
            "lag_summary": lag_report,
            "event_audit": audit_summary,
        }
    )
    record_health_snapshot(
        engine=engine,
        snapshot_type="kafka_event_audit",
        component="kafka",
        status=str(audit_summary.get("status") or summary["status"]),
        run_date=datetime.now(timezone.utc).date(),
        summary={
            "consumer_group": audit_cfg["consumer_group"],
            "consumed_count": consumed_count,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "dead_letter_count": dead_letter_count,
            "max_lag": int(audit_summary.get("max_lag") or 0),
            "pending_count": int(audit_summary.get("pending_count") or 0),
        },
        details=summary,
    )
    return summary


def snapshot_kafka_consumer_lag(
    *,
    kafka_config: Mapping[str, Any],
    engine: Engine,
    consumer_group: str,
    lag_warning_threshold: int,
    topics: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Persist one set of consumer lag snapshots and return a compact summary."""

    resolved = resolve_kafka_config(kafka_config, default_client_id="team_pearson_cw2_audit")
    if not resolved.enabled:
        return {
            "status": "skipped",
            "reason": "kafka disabled",
            "lag_snapshot_count": 0,
        }

    audit_cfg = _resolve_audit_settings(kafka_config)
    if not audit_cfg["enabled"]:
        return {
            "status": "skipped",
            "reason": "kafka audit consumer disabled",
            "lag_snapshot_count": 0,
        }
    topic_names = list(topics or _resolve_audit_topics(resolved, audit_cfg["topic_keys"]))
    if not topic_names:
        return {
            "status": "warning",
            "reason": "no audit topics configured",
            "lag_snapshot_count": 0,
        }

    consumer = _build_consumer(
        resolved_bootstrap=list(resolved.bootstrap_servers),
        client_id=f"{resolved.client_id}_audit_lag",
        consumer_group=consumer_group,
        max_batch_messages=1,
    )
    snapshot_count = 0
    max_lag = 0
    total_lag = 0
    try:
        from kafka.structs import TopicPartition  # type: ignore

        for topic_name in topic_names:
            partitions = consumer.partitions_for_topic(topic_name) or set()
            if not partitions:
                continue
            topic_partitions = [
                TopicPartition(topic_name, int(partition_id)) for partition_id in sorted(partitions)
            ]
            end_offsets = consumer.end_offsets(topic_partitions)
            for topic_partition in topic_partitions:
                committed = consumer.committed(topic_partition)
                high_watermark = int(end_offsets.get(topic_partition) or 0)
                committed_offset = 0 if committed is None or int(committed) < 0 else int(committed)
                lag = max(0, high_watermark - committed_offset)
                max_lag = max(max_lag, lag)
                total_lag += lag
                lag_status = "warning" if lag > int(lag_warning_threshold) else "ok"
                if record_kafka_lag_snapshot(
                    engine=engine,
                    consumer_group=consumer_group,
                    topic_name=topic_name,
                    partition_id=int(topic_partition.partition),
                    committed_offset=committed_offset,
                    high_watermark=high_watermark,
                    lag=lag,
                    lag_status=lag_status,
                    sampled_at=datetime.now(timezone.utc),
                ):
                    snapshot_count += 1
    finally:
        consumer.close()

    return {
        "status": "ok",
        "consumer_group": consumer_group,
        "lag_snapshot_count": snapshot_count,
        "max_lag": max_lag,
        "total_lag": total_lag,
        "topics": topic_names,
    }


def run_kafka_event_audit_from_config(
    *,
    cw1_config_path: str,
    cw2_config_path: str,
    db_engine: Engine | None = None,
    max_messages: Optional[int] = None,
    poll_timeout_ms: Optional[int] = None,
    max_idle_polls: Optional[int] = None,
    audit_overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Load config, merge Kafka settings, and run the Kafka audit consumer."""

    cw1_cfg = _load_yaml(cw1_config_path)
    cw2_cfg = _load_yaml(cw2_config_path)
    merged = _merged_kafka_config(cw1_cfg, cw2_cfg)
    if audit_overrides:
        kafka_cfg = dict(merged.get("kafka") or {})
        merged_audit = {
            **dict(kafka_cfg.get("audit_consumer") or {}),
            **dict(audit_overrides),
        }
        merged["kafka"] = {**kafka_cfg, "audit_consumer": merged_audit}
    engine = db_engine or _load_shared_db_engine()
    return consume_kafka_events_with_audit(
        kafka_config=merged,
        engine=engine,
        max_messages=max_messages,
        poll_timeout_ms=poll_timeout_ms,
        max_idle_polls=max_idle_polls,
    )


def _load_yaml(path: str) -> Dict[str, Any]:
    cfg_path = Path(path)
    default_cw2 = Path(__file__).resolve().parents[2] / "config" / "conf.yaml"
    if cfg_path.resolve() == default_cw2.resolve():
        return load_cw2_config(str(cfg_path))

    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyYAML is not installed in the current interpreter. "
            "Run CW2 with the shared coursework_one environment."
        ) from exc
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _merged_kafka_config(cw1_cfg: Dict[str, Any], cw2_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cw1_kafka = dict(cw1_cfg.get("kafka") or {})
    cw2_kafka = dict(cw2_cfg.get("kafka") or {})
    merged_topics = {
        **dict(cw1_kafka.get("topics") or {}),
        **dict(cw2_kafka.get("topics") or {}),
    }
    merged_audit = {
        **dict(cw1_kafka.get("audit_consumer") or {}),
        **dict(cw2_kafka.get("audit_consumer") or {}),
    }
    merged = dict(cw1_cfg)
    merged["kafka"] = {
        **cw1_kafka,
        **cw2_kafka,
        "topics": merged_topics,
        "audit_consumer": merged_audit,
    }
    return merged


def _resolve_audit_settings(config: Mapping[str, Any]) -> Dict[str, Any]:
    raw_cfg = dict((config or {}).get("kafka") or {})
    audit_cfg = dict(raw_cfg.get("audit_consumer") or {})
    topic_keys = audit_cfg.get("topic_keys") or [
        "cw2_risk_actions_requested",
        "cw2_risk_actions_executed",
        "platform_run_status",
    ]
    if not isinstance(topic_keys, list):
        topic_keys = [str(topic_keys)]
    return {
        "enabled": _coerce_boolish(audit_cfg.get("enabled"), default=True),
        "consumer_group": str(audit_cfg.get("consumer_group") or "team_pearson_cw2_audit").strip()
        or "team_pearson_cw2_audit",
        "consumer_component": str(
            audit_cfg.get("consumer_component") or "cw2.kafka_audit_consumer"
        ).strip()
        or "cw2.kafka_audit_consumer",
        "topic_keys": [str(item).strip() for item in topic_keys if str(item).strip()],
        "poll_timeout_ms": max(1, int(audit_cfg.get("poll_timeout_ms", 1000))),
        "max_batch_messages": max(1, int(audit_cfg.get("max_batch_messages", 200))),
        "max_idle_polls": max(1, int(audit_cfg.get("max_idle_polls", 3))),
        "max_retries_per_message": max(0, int(audit_cfg.get("max_retries_per_message", 3))),
        "lag_warning_threshold": max(0, int(audit_cfg.get("lag_warning_threshold", 100))),
        "freshness_warning_minutes": max(1, int(audit_cfg.get("freshness_warning_minutes", 60))),
    }


def _resolve_audit_topics(resolved: Any, topic_keys: Iterable[str]) -> List[str]:
    topics: List[str] = []
    for topic_key in topic_keys:
        topic_name = str(resolved.topics.get(str(topic_key), "")).strip()
        if topic_name and topic_name not in topics:
            topics.append(topic_name)
    return topics


def _build_consumer(
    *,
    resolved_bootstrap: List[str],
    client_id: str,
    consumer_group: str,
    max_batch_messages: int,
) -> Any:
    from kafka import KafkaConsumer  # type: ignore

    return KafkaConsumer(
        bootstrap_servers=resolved_bootstrap,
        client_id=client_id,
        group_id=consumer_group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_records=max_batch_messages,
        value_deserializer=None,
        key_deserializer=None,
    )


def _process_kafka_record(
    *,
    engine: Engine,
    record: Any,
    consumer_group: str,
    consumer_component: str,
    max_retries_per_message: int,
) -> Dict[str, Any]:
    headers = _decode_headers(getattr(record, "headers", None))
    message_key = _decode_message_key(getattr(record, "key", None))
    synthetic_event_id = f"{record.topic}:{int(record.partition)}:{int(record.offset)}"
    now = datetime.now(timezone.utc)
    prior_retry_count = _load_retry_count(
        engine=engine,
        topic_name=str(record.topic),
        consumer_group=consumer_group,
        kafka_partition=int(record.partition),
        kafka_offset=int(record.offset),
    )

    try:
        payload = _parse_message_payload(getattr(record, "value", None))
    except Exception as exc:
        payload = {"raw_message": _raw_message_text(getattr(record, "value", None))}
        retry_count = prior_retry_count + 1
        final_failure = retry_count >= max_retries_per_message
        ack_status = "dead_lettered" if final_failure else "failed"
        record_kafka_consumer_ack(
            engine=engine,
            event_id=synthetic_event_id,
            topic_name=str(record.topic),
            consumer_group=consumer_group,
            consumer_component=consumer_component,
            kafka_partition=int(record.partition),
            kafka_offset=int(record.offset),
            payload=payload,
            message_key=message_key,
            headers=headers,
            event_type="kafka_audit_parse_failure",
            ack_status=ack_status,
            retry_count=retry_count,
            last_error=str(exc),
            consumed_at=now,
        )
        if final_failure:
            record_kafka_dead_letter(
                engine=engine,
                event_id=synthetic_event_id,
                topic_name=str(record.topic),
                consumer_group=consumer_group,
                consumer_component=consumer_component,
                kafka_partition=int(record.partition),
                kafka_offset=int(record.offset),
                dead_letter_reason="payload_parse_failed",
                payload=payload,
                message_key=message_key,
                headers=headers,
                event_type="kafka_audit_parse_failure",
                error_text=str(exc),
            )
            return {
                "status": "dead_lettered",
                "commit_offset": int(record.offset) + 1,
            }
        return {"status": "failed", "commit_offset": None}

    event_id = str(payload.get("event_id") or synthetic_event_id)
    if not record_kafka_consumer_ack(
        engine=engine,
        event_id=event_id,
        topic_name=str(record.topic),
        consumer_group=consumer_group,
        consumer_component=consumer_component,
        kafka_partition=int(record.partition),
        kafka_offset=int(record.offset),
        payload=payload,
        message_key=message_key,
        headers=headers,
        ack_status="consumed",
        retry_count=prior_retry_count,
        consumed_at=now,
    ):
        return {"status": "failed", "commit_offset": None}

    if not record_kafka_consumer_ack(
        engine=engine,
        event_id=event_id,
        topic_name=str(record.topic),
        consumer_group=consumer_group,
        consumer_component=consumer_component,
        kafka_partition=int(record.partition),
        kafka_offset=int(record.offset),
        payload=payload,
        message_key=message_key,
        headers=headers,
        ack_status="processed",
        retry_count=prior_retry_count,
        consumed_at=now,
        processed_at=datetime.now(timezone.utc),
    ):
        retry_count = prior_retry_count + 1
        record_kafka_consumer_ack(
            engine=engine,
            event_id=event_id,
            topic_name=str(record.topic),
            consumer_group=consumer_group,
            consumer_component=consumer_component,
            kafka_partition=int(record.partition),
            kafka_offset=int(record.offset),
            payload=payload,
            message_key=message_key,
            headers=headers,
            ack_status="failed",
            retry_count=retry_count,
            last_error="consumer ack persistence failed",
            consumed_at=now,
        )
        return {"status": "failed", "commit_offset": None}

    return {"status": "processed", "commit_offset": int(record.offset) + 1}


def _commit_offset(consumer: Any, *, topic: str, partition: int, offset: int) -> None:
    from kafka.structs import OffsetAndMetadata, TopicPartition  # type: ignore

    topic_partition = TopicPartition(str(topic), int(partition))
    offset_metadata = _build_offset_and_metadata(OffsetAndMetadata, offset=int(offset))
    consumer.commit({topic_partition: offset_metadata})


def _build_offset_and_metadata(offset_and_metadata_cls: Any, *, offset: int) -> Any:
    """Build OffsetAndMetadata across kafka-python constructor variants."""

    try:
        parameter_count = len(inspect.signature(offset_and_metadata_cls).parameters)
    except (TypeError, ValueError):  # pragma: no cover - defensive only
        parameter_count = 2

    if parameter_count >= 3:
        return offset_and_metadata_cls(int(offset), None, -1)
    return offset_and_metadata_cls(int(offset), None)


def _load_retry_count(
    *,
    engine: Engine,
    topic_name: str,
    consumer_group: str,
    kafka_partition: int,
    kafka_offset: int,
) -> int:
    sql = text("""
        SELECT retry_count
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE topic_name = :topic_name
          AND consumer_group = :consumer_group
          AND kafka_partition = :kafka_partition
          AND kafka_offset = :kafka_offset
        """)
    with engine.connect() as conn:
        row = (
            conn.execute(
                sql,
                {
                    "topic_name": topic_name,
                    "consumer_group": consumer_group,
                    "kafka_partition": int(kafka_partition),
                    "kafka_offset": int(kafka_offset),
                },
            )
            .mappings()
            .first()
        )
    return int((row or {}).get("retry_count") or 0)


def _parse_message_payload(raw_value: Any) -> Dict[str, Any]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, Mapping):
        return dict(raw_value)
    if isinstance(raw_value, (bytes, bytearray)):
        raw_value = raw_value.decode("utf-8")
    if isinstance(raw_value, str):
        parsed = json.loads(raw_value)
        if isinstance(parsed, Mapping):
            return dict(parsed)
        raise ValueError("Kafka message payload must decode to a JSON object")
    raise ValueError(f"Unsupported Kafka message payload type: {type(raw_value).__name__}")


def _raw_message_text(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    if isinstance(raw_value, (bytes, bytearray)):
        try:
            return raw_value.decode("utf-8")
        except Exception:
            return repr(bytes(raw_value))
    return str(raw_value)


def _decode_message_key(raw_key: Any) -> Optional[str]:
    if raw_key is None:
        return None
    if isinstance(raw_key, (bytes, bytearray)):
        try:
            return raw_key.decode("utf-8").strip() or None
        except Exception:
            return repr(bytes(raw_key))
    return str(raw_key).strip() or None


def _decode_headers(raw_headers: Any) -> Dict[str, Any]:
    headers: Dict[str, Any] = {}
    for item in list(raw_headers or []):
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        key, value = item
        if isinstance(value, (bytes, bytearray)):
            try:
                value = value.decode("utf-8")
            except Exception:
                value = repr(bytes(value))
        headers[str(key)] = value
    return headers


def _coerce_boolish(value: Any, *, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description="Consume CW2 Kafka events and persist end-to-end audit state."
    )
    parser.add_argument("--cw1-config", required=True)
    parser.add_argument("--cw2-config", required=True)
    parser.add_argument("--max-messages", type=int, default=None)
    parser.add_argument("--poll-timeout-ms", type=int, default=None)
    parser.add_argument("--max-idle-polls", type=int, default=None)
    return parser


def main() -> int:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_parser().parse_args()
    summary = run_kafka_event_audit_from_config(
        cw1_config_path=str(args.cw1_config),
        cw2_config_path=str(args.cw2_config),
        max_messages=args.max_messages,
        poll_timeout_ms=args.poll_timeout_ms,
        max_idle_polls=args.max_idle_polls,
    )
    print(json.dumps(summary, ensure_ascii=False, default=str, indent=2))
    return 0 if str(summary.get("status")) in {"ok", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
