from __future__ import annotations

from modules.utils import kafka as kafka_utils


def test_resolve_kafka_config_prefers_env(monkeypatch):
    monkeypatch.setenv("KAFKA_ENABLED", "true")
    monkeypatch.setenv("KAFKA_REQUIRED", "false")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092,localhost:39092")
    monkeypatch.setenv("KAFKA_CLIENT_ID", "env-client")

    resolved = kafka_utils.resolve_kafka_config(
        {"kafka": {"enabled": False, "bootstrap_servers": ["x:1"]}},
        default_client_id="fallback",
    )

    assert resolved.enabled is True
    assert resolved.required is False
    assert resolved.bootstrap_servers == ("localhost:29092", "localhost:39092")
    assert resolved.client_id == "env-client"


def test_publish_json_events_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("KAFKA_ENABLED", raising=False)
    count = kafka_utils.publish_json_events(
        {"kafka": {"enabled": False}},
        topic_key="cw1_event_proxies",
        default_topic="cw1.event.proxies.v1",
        events=[{"symbol": "AAPL"}],
        default_client_id="test-client",
    )
    assert count == 0


def test_audit_kafka_connectivity_reports_disabled(monkeypatch):
    monkeypatch.delenv("KAFKA_ENABLED", raising=False)
    report = kafka_utils.audit_kafka_connectivity(
        {"kafka": {"enabled": False}},
        default_client_id="audit-client",
    )
    assert report["enabled"] is False
    assert report["status"] == "disabled"
