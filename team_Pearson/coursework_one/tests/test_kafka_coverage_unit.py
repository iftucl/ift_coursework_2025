from __future__ import annotations

import builtins
from datetime import date, datetime
from decimal import Decimal
import sys
from types import ModuleType

import pytest

from modules.utils import kafka as kafka_utils


class _FakeProducer:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.sent = []
        self.flushed = False
        _FakeProducer.instances.append(self)

    def send(self, topic, value, key=None):
        self.sent.append((topic, value, key))

    def flush(self):
        self.flushed = True


class _FailingProducer(_FakeProducer):
    def send(self, topic, value, key=None):  # noqa: ARG002
        raise RuntimeError("send failed")


class _SocketCtx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False


def _resolved(required: bool = False) -> kafka_utils.KafkaResolvedConfig:
    return kafka_utils.KafkaResolvedConfig(
        enabled=True,
        required=required,
        bootstrap_servers=("localhost:29092",),
        client_id="test-client",
        linger_ms=10,
        batch_size=1024,
        compression_type="gzip",
        topics={
            "platform_run_status": "platform.runs.status.v1",
            "cw1_event_proxies": "cw1.event.proxies.v1",
        },
    )


def test_kafka_helper_coercions_and_json_default():
    assert kafka_utils._coerce_bool("yes") is True
    assert kafka_utils._coerce_bool(None, default=True) is True
    assert kafka_utils._coerce_int("7", 1) == 7
    assert kafka_utils._coerce_int("bad", 3) == 3
    assert kafka_utils._topic_name({}, "missing", "fallback.topic") == "fallback.topic"
    assert kafka_utils._json_default(date(2026, 4, 15)) == "2026-04-15"
    assert kafka_utils._json_default(datetime(2026, 4, 15, 10, 30)) == "2026-04-15T10:30:00"
    assert kafka_utils._json_default(Decimal("1.5")) == 1.5


def test_get_kafka_producer_uses_cache_and_serializers(monkeypatch):
    kafka_utils._PRODUCER_CACHE.clear()
    _FakeProducer.instances.clear()

    fake_module = ModuleType("kafka")
    fake_module.KafkaProducer = _FakeProducer
    monkeypatch.setitem(sys.modules, "kafka", fake_module)

    producer = kafka_utils._get_kafka_producer(_resolved())
    assert isinstance(producer, _FakeProducer)
    assert kafka_utils._get_kafka_producer(_resolved()) is producer
    assert len(_FakeProducer.instances) == 1

    serialized = producer.kwargs["value_serializer"](
        {"when": date(2026, 4, 15), "amount": Decimal("1.5")}
    )
    assert b"2026-04-15" in serialized
    assert b"1.5" in serialized
    assert producer.kwargs["key_serializer"]("AAPL") == b"AAPL"


def test_get_kafka_producer_handles_missing_client_paths(monkeypatch):
    kafka_utils._PRODUCER_CACHE.clear()
    monkeypatch.delitem(sys.modules, "kafka", raising=False)
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "kafka":
            raise ModuleNotFoundError("no kafka module")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert kafka_utils._get_kafka_producer(_resolved(required=False)) is None

    kafka_utils._PRODUCER_CACHE.clear()
    with pytest.raises(RuntimeError):
        kafka_utils._get_kafka_producer(
            kafka_utils.KafkaResolvedConfig(
                **{**_resolved(required=True).__dict__, "client_id": "required-client"}
            )
        )


def test_publish_json_events_success_and_failures(monkeypatch):
    kafka_utils._PRODUCER_CACHE.clear()
    monkeypatch.setattr(kafka_utils, "_get_kafka_producer", lambda resolved: _FakeProducer())  # noqa: ARG005

    count = kafka_utils.publish_json_events(
        {"kafka": {"enabled": True, "topics": {"platform_run_status": "platform.runs.status.v1"}}},
        topic_key="platform_run_status",
        default_topic="fallback.topic",
        events=[{"symbol": "AAPL", "value": 1}, {"symbol": "  ", "value": 2}],
        default_client_id="test-client",
    )
    assert count == 2

    monkeypatch.setattr(kafka_utils, "_get_kafka_producer", lambda resolved: _FailingProducer())  # noqa: ARG005
    optional_count = kafka_utils.publish_json_events(
        {"kafka": {"enabled": True, "required": False}},
        topic_key="cw1_event_proxies",
        default_topic="cw1.event.proxies.v1",
        events=[{"symbol": "AAPL"}],
        default_client_id="test-client",
    )
    assert optional_count == 0

    with pytest.raises(RuntimeError):
        kafka_utils.publish_json_events(
            {"kafka": {"enabled": True, "required": True}},
            topic_key="cw1_event_proxies",
            default_topic="cw1.event.proxies.v1",
            events=[{"symbol": "AAPL"}],
            default_client_id="test-client",
        )


def test_audit_kafka_connectivity_reports_success_and_error(monkeypatch):
    monkeypatch.setattr(kafka_utils.socket, "create_connection", lambda *args, **kwargs: _SocketCtx())
    ok_report = kafka_utils.audit_kafka_connectivity(
        {"kafka": {"enabled": True, "bootstrap_servers": ["localhost:29092"]}},
        default_client_id="audit-client",
    )
    assert ok_report["status"] == "ok"
    assert ok_report["reachable_broker"] == "localhost:29092"

    monkeypatch.setattr(
        kafka_utils.socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")),
    )
    error_report = kafka_utils.audit_kafka_connectivity(
        {"kafka": {"enabled": True, "bootstrap_servers": ["localhost:29092"]}},
        default_client_id="audit-client",
    )
    assert error_report["status"] == "error"
    assert "boom" in error_report["error"]
