from __future__ import annotations

"""Shared Kafka helpers for the Team Pearson batch/event hybrid architecture."""

import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

_PRODUCER_CACHE: Dict[tuple[Any, ...], Any] = {}


@dataclass(frozen=True)
class KafkaResolvedConfig:
    enabled: bool
    required: bool
    bootstrap_servers: tuple[str, ...]
    client_id: str
    linger_ms: int
    batch_size: int
    compression_type: Optional[str]
    topics: Dict[str, str]


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _topic_name(topics: Mapping[str, Any], key: str, default: str) -> str:
    candidate = str(topics.get(key, default) or default).strip()
    return candidate or default


def resolve_kafka_config(
    config: Optional[Mapping[str, Any]],
    *,
    default_client_id: str,
) -> KafkaResolvedConfig:
    """Resolve Kafka config from env first, then YAML mapping."""
    raw_cfg = dict((config or {}).get("kafka") or {})
    env_bootstrap = str(os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "").strip()
    cfg_bootstrap = raw_cfg.get("bootstrap_servers") or ["localhost:29092"]
    if env_bootstrap:
        bootstrap_servers = tuple(part.strip() for part in env_bootstrap.split(",") if part.strip())
    elif isinstance(cfg_bootstrap, str):
        bootstrap_servers = tuple(part.strip() for part in cfg_bootstrap.split(",") if part.strip())
    else:
        bootstrap_servers = tuple(str(part).strip() for part in cfg_bootstrap if str(part).strip())

    topics = dict(raw_cfg.get("topics") or {})
    return KafkaResolvedConfig(
        enabled=_coerce_bool(
            os.getenv("KAFKA_ENABLED"), _coerce_bool(raw_cfg.get("enabled"), False)
        ),
        required=_coerce_bool(
            os.getenv("KAFKA_REQUIRED"), _coerce_bool(raw_cfg.get("required"), False)
        ),
        bootstrap_servers=bootstrap_servers or ("localhost:29092",),
        client_id=str(
            os.getenv("KAFKA_CLIENT_ID") or raw_cfg.get("client_id") or default_client_id
        ).strip()
        or default_client_id,
        linger_ms=_coerce_int(raw_cfg.get("linger_ms"), 50),
        batch_size=_coerce_int(raw_cfg.get("batch_size"), 16_384),
        compression_type=(str(raw_cfg.get("compression_type") or "").strip() or None),
        topics={
            "cw1_news_structured": _topic_name(
                topics, "cw1_news_structured", "cw1.news.structured.v1"
            ),
            "cw1_event_proxies": _topic_name(topics, "cw1_event_proxies", "cw1.event.proxies.v1"),
            "cw2_risk_actions_requested": _topic_name(
                topics, "cw2_risk_actions_requested", "cw2.risk.actions.requested.v1"
            ),
            "cw2_risk_actions_executed": _topic_name(
                topics, "cw2_risk_actions_executed", "cw2.risk.actions.executed.v1"
            ),
            "platform_run_status": _topic_name(
                topics, "platform_run_status", "platform.runs.status.v1"
            ),
        },
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _get_kafka_producer(resolved: KafkaResolvedConfig) -> Any | None:
    if not resolved.enabled:
        return None
    cache_key = (
        resolved.bootstrap_servers,
        resolved.client_id,
        resolved.linger_ms,
        resolved.batch_size,
        resolved.compression_type,
    )
    cached = _PRODUCER_CACHE.get(cache_key)
    if cache_key in _PRODUCER_CACHE:
        return cached

    try:
        from kafka import KafkaProducer  # type: ignore
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        if resolved.required:
            raise RuntimeError("Kafka publishing enabled but kafka-python is unavailable") from exc
        logger.warning("kafka_publish_disabled reason=missing_client error=%r", exc)
        _PRODUCER_CACHE[cache_key] = None
        return None

    producer = KafkaProducer(
        bootstrap_servers=list(resolved.bootstrap_servers),
        client_id=resolved.client_id,
        linger_ms=resolved.linger_ms,
        batch_size=resolved.batch_size,
        compression_type=resolved.compression_type,
        value_serializer=lambda payload: json.dumps(
            payload,
            ensure_ascii=False,
            default=_json_default,
        ).encode("utf-8"),
        key_serializer=lambda payload: (
            payload.encode("utf-8") if isinstance(payload, str) else payload
        ),
    )
    _PRODUCER_CACHE[cache_key] = producer
    return producer


def publish_json_events(
    config: Optional[Mapping[str, Any]],
    *,
    topic_key: str,
    default_topic: str,
    events: Sequence[Mapping[str, Any]],
    key_field: str = "symbol",
    default_client_id: str,
) -> int:
    """Publish JSON events to Kafka, returning the number of accepted messages."""
    if not events:
        return 0
    resolved = resolve_kafka_config(config, default_client_id=default_client_id)
    if not resolved.enabled:
        return 0
    producer = _get_kafka_producer(resolved)
    if producer is None:
        return 0

    topic = resolved.topics.get(topic_key, default_topic)
    published = 0
    try:
        for event in events:
            key_value = str(event.get(key_field) or "").strip() or None
            producer.send(topic, value=dict(event), key=key_value)
            published += 1
        producer.flush()
    except Exception as exc:  # pragma: no cover - depends on runtime services
        if resolved.required:
            raise RuntimeError(f"Kafka publish failed for topic={topic}") from exc
        logger.warning(
            "kafka_publish_failed topic=%s count=%s error=%r",
            topic,
            len(events),
            exc,
        )
        return 0
    return published


def audit_kafka_connectivity(
    config: Optional[Mapping[str, Any]],
    *,
    default_client_id: str,
) -> Dict[str, Any]:
    """Probe Kafka bootstrap reachability without requiring a producer send."""
    resolved = resolve_kafka_config(config, default_client_id=default_client_id)
    report: Dict[str, Any] = {
        "enabled": resolved.enabled,
        "required": resolved.required,
        "bootstrap_servers": list(resolved.bootstrap_servers),
        "status": "disabled",
    }
    if not resolved.enabled:
        return report

    try:
        for server in resolved.bootstrap_servers:
            host, port_text = str(server).rsplit(":", 1)
            with socket.create_connection((host, int(port_text)), timeout=2.0):
                report.update({"status": "ok", "reachable_broker": server})
                return report
        report.update({"status": "error", "error": "no_reachable_bootstrap_server"})
    except Exception as exc:  # pragma: no cover - depends on runtime services
        report.update({"status": "error", "error": repr(exc)})
    return report
