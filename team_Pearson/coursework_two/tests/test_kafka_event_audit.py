from __future__ import annotations

import inspect
from types import SimpleNamespace

from team_Pearson.coursework_two.modules.ops import kafka_audit as kafka_audit_mod


def test_process_kafka_record_marks_processed(monkeypatch):
    statuses = []

    monkeypatch.setattr(kafka_audit_mod, "_load_retry_count", lambda **kwargs: 0)
    monkeypatch.setattr(
        kafka_audit_mod,
        "record_kafka_consumer_ack",
        lambda **kwargs: statuses.append(kwargs["ack_status"]) or True,
    )
    monkeypatch.setattr(
        kafka_audit_mod,
        "record_kafka_dead_letter",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dead letter not expected")),
    )

    record = SimpleNamespace(
        topic="cw2.risk.actions.executed.v1",
        partition=1,
        offset=14,
        key=b"run-1",
        value=b'{"event_id":"evt-1","run_id":"run-1","event_type":"risk_action"}',
        headers=[("source", b"cw2")],
    )
    result = kafka_audit_mod._process_kafka_record(
        engine=object(),
        record=record,
        consumer_group="team_pearson_cw2_audit",
        consumer_component="cw2.kafka_audit_consumer",
        max_retries_per_message=3,
    )

    assert result == {"status": "processed", "commit_offset": 15}
    assert statuses == ["consumed", "processed"]


def test_process_kafka_record_dead_letters_after_retry_budget(monkeypatch):
    ack_statuses = []
    dead_letters = []

    monkeypatch.setattr(kafka_audit_mod, "_load_retry_count", lambda **kwargs: 2)
    monkeypatch.setattr(
        kafka_audit_mod,
        "record_kafka_consumer_ack",
        lambda **kwargs: ack_statuses.append(kwargs["ack_status"]) or True,
    )
    monkeypatch.setattr(
        kafka_audit_mod,
        "record_kafka_dead_letter",
        lambda **kwargs: dead_letters.append(dict(kwargs)) or True,
    )

    record = SimpleNamespace(
        topic="platform.runs.status.v1",
        partition=0,
        offset=8,
        key=b"run-1",
        value=b"not-json",
        headers=[],
    )
    result = kafka_audit_mod._process_kafka_record(
        engine=object(),
        record=record,
        consumer_group="team_pearson_cw2_audit",
        consumer_component="cw2.kafka_audit_consumer",
        max_retries_per_message=3,
    )

    assert result == {"status": "dead_lettered", "commit_offset": 9}
    assert ack_statuses == ["dead_lettered"]
    assert dead_letters[0]["dead_letter_reason"] == "payload_parse_failed"


def test_consume_kafka_events_with_audit_skips_when_audit_consumer_disabled(
    monkeypatch,
):
    monkeypatch.setattr(kafka_audit_mod, "ensure_ops_monitoring_schema", lambda engine: None)

    summary = kafka_audit_mod.consume_kafka_events_with_audit(
        kafka_config={
            "kafka": {
                "enabled": True,
                "audit_consumer": {"enabled": False},
            }
        },
        engine=object(),
    )

    assert summary["status"] == "skipped"
    assert summary["reason"] == "kafka audit consumer disabled"


def test_build_offset_and_metadata_matches_runtime_constructor():
    from kafka.structs import OffsetAndMetadata

    built = kafka_audit_mod._build_offset_and_metadata(OffsetAndMetadata, offset=42)
    parameter_count = len(inspect.signature(OffsetAndMetadata).parameters)

    assert built.offset == 42
    assert built.metadata is None
    if parameter_count >= 3:
        assert built.leader_epoch == -1


def test_resolve_audit_settings_normalizes_defaults():
    settings = kafka_audit_mod._resolve_audit_settings(
        {
            "kafka": {
                "audit_consumer": {
                    "enabled": "yes",
                    "topic_keys": "platform_run_status",
                    "poll_timeout_ms": 0,
                    "max_batch_messages": 0,
                    "max_idle_polls": 0,
                    "max_retries_per_message": -2,
                    "lag_warning_threshold": -5,
                }
            }
        }
    )

    assert settings["enabled"] is True
    assert settings["topic_keys"] == ["platform_run_status"]
    assert settings["poll_timeout_ms"] == 1
    assert settings["max_batch_messages"] == 1
    assert settings["max_idle_polls"] == 1
    assert settings["max_retries_per_message"] == 0
    assert settings["lag_warning_threshold"] == 0


def test_decode_helpers_cover_bytes_and_invalid_payload():
    assert kafka_audit_mod._parse_message_payload({"event_id": "evt-1"}) == {"event_id": "evt-1"}
    assert kafka_audit_mod._parse_message_payload(b'{"event_id":"evt-2"}') == {"event_id": "evt-2"}
    assert kafka_audit_mod._raw_message_text(b"\xff") == "b'\\xff'"
    assert kafka_audit_mod._decode_message_key(b"run-1") == "run-1"
    assert kafka_audit_mod._decode_message_key(b"\xff") == "b'\\xff'"
    assert kafka_audit_mod._decode_headers([("source", b"cw2"), ("count", 2)]) == {
        "source": "cw2",
        "count": 2,
    }
    assert kafka_audit_mod._coerce_boolish(None, default=True) is True
    assert kafka_audit_mod._coerce_boolish("off", default=True) is False

    try:
        kafka_audit_mod._parse_message_payload("[]")
    except ValueError as exc:
        assert "JSON object" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for non-object payload")


def test_run_kafka_event_audit_from_config_merges_overrides(monkeypatch):
    captured = {}
    fake_engine = object()
    monkeypatch.setattr(
        kafka_audit_mod,
        "_load_yaml",
        lambda path: {
            "cw1.yaml": {
                "kafka": {
                    "enabled": True,
                    "topics": {"platform_run_status": "platform.runs.status.v1"},
                }
            },
            "cw2.yaml": {
                "kafka": {
                    "topics": {"cw2_risk_actions_executed": "cw2.risk.executed.v1"},
                    "audit_consumer": {"enabled": True, "max_batch_messages": 100},
                }
            },
        }[path],
    )
    monkeypatch.setattr(kafka_audit_mod, "_load_shared_db_engine", lambda: fake_engine)
    monkeypatch.setattr(
        kafka_audit_mod,
        "consume_kafka_events_with_audit",
        lambda **kwargs: captured.update(kwargs) or {"status": "ok"},
    )

    result = kafka_audit_mod.run_kafka_event_audit_from_config(
        cw1_config_path="cw1.yaml",
        cw2_config_path="cw2.yaml",
        max_messages=50,
        poll_timeout_ms=900,
        max_idle_polls=2,
        audit_overrides={"consumer_component": "cw2.kafka_audit_daemon"},
    )

    assert result["status"] == "ok"
    assert captured["engine"] is fake_engine
    assert captured["max_messages"] == 50
    assert captured["poll_timeout_ms"] == 900
    assert (
        captured["kafka_config"]["kafka"]["audit_consumer"]["consumer_component"]
        == "cw2.kafka_audit_daemon"
    )
    assert (
        captured["kafka_config"]["kafka"]["topics"]["cw2_risk_actions_executed"]
        == "cw2.risk.executed.v1"
    )


def test_snapshot_kafka_consumer_lag_records_offsets(monkeypatch):
    class _LagConsumer:
        def __init__(self):
            self.closed = False

        def partitions_for_topic(self, topic_name):
            return {0, 1} if topic_name == "topic-a" else set()

        def end_offsets(self, partitions):
            return {
                partitions[0]: 10,
                partitions[1]: 7,
            }

        def committed(self, topic_partition):
            return {0: 8, 1: None}[int(topic_partition.partition)]

        def close(self):
            self.closed = True

    lag_rows = []
    consumer = _LagConsumer()
    monkeypatch.setattr(
        kafka_audit_mod,
        "resolve_kafka_config",
        lambda config, *, default_client_id: SimpleNamespace(  # noqa: ARG005
            enabled=True,
            bootstrap_servers=["kafka:9092"],
            client_id="team_pearson_cw2_audit",
            topics={"platform_run_status": "topic-a"},
        ),
    )
    monkeypatch.setattr(kafka_audit_mod, "_build_consumer", lambda **kwargs: consumer)
    monkeypatch.setattr(
        kafka_audit_mod,
        "record_kafka_lag_snapshot",
        lambda **kwargs: lag_rows.append(kwargs) or True,
    )

    summary = kafka_audit_mod.snapshot_kafka_consumer_lag(
        kafka_config={
            "kafka": {
                "enabled": True,
                "audit_consumer": {
                    "enabled": True,
                    "topic_keys": ["platform_run_status"],
                },
            }
        },
        engine=object(),
        consumer_group="team_pearson_cw2_audit",
        lag_warning_threshold=1,
    )

    assert summary["status"] == "ok"
    assert summary["lag_snapshot_count"] == 2
    assert summary["max_lag"] == 7
    assert summary["total_lag"] == 9
    assert lag_rows[0]["partition_id"] in {0, 1}
    assert consumer.closed is True


def test_consume_kafka_events_with_audit_happy_path(monkeypatch):
    record = SimpleNamespace(topic="topic-a", partition=0, offset=4)
    committed = []
    health = {}

    class _Consumer:
        def __init__(self):
            self._poll_count = 0
            self.closed = False

        def subscribe(self, topics):
            self.topics = list(topics)

        def assignment(self):
            return {"assigned"}

        def poll(self, timeout_ms, max_records):  # noqa: ARG002
            self._poll_count += 1
            if self._poll_count == 1:
                return {("topic-a", 0): [record]}
            return {}

        def close(self):
            self.closed = True

    consumer = _Consumer()
    monkeypatch.setattr(kafka_audit_mod, "ensure_ops_monitoring_schema", lambda engine: None)
    monkeypatch.setattr(
        kafka_audit_mod,
        "resolve_kafka_config",
        lambda config, *, default_client_id: SimpleNamespace(  # noqa: ARG005
            enabled=True,
            required=False,
            bootstrap_servers=["kafka:9092"],
            client_id="team_pearson_cw2_audit",
            topics={"cw2_risk_actions_requested": "topic-a"},
        ),
    )
    monkeypatch.setattr(kafka_audit_mod, "_build_consumer", lambda **kwargs: consumer)
    monkeypatch.setattr(
        kafka_audit_mod,
        "_process_kafka_record",
        lambda **kwargs: {"status": "processed", "commit_offset": 5},
    )
    monkeypatch.setattr(
        kafka_audit_mod,
        "_commit_offset",
        lambda consumer, **kwargs: committed.append(kwargs),
    )
    monkeypatch.setattr(
        kafka_audit_mod,
        "snapshot_kafka_consumer_lag",
        lambda **kwargs: {"lag_snapshot_count": 2, "max_lag": 3},
    )
    monkeypatch.setattr(
        kafka_audit_mod,
        "summarize_kafka_event_audit",
        lambda *args, **kwargs: {  # noqa: ARG005
            "status": "ok",
            "max_lag": 3,
            "pending_count": 0,
        },
    )
    monkeypatch.setattr(
        kafka_audit_mod,
        "record_health_snapshot",
        lambda **kwargs: health.update(kwargs),
    )

    summary = kafka_audit_mod.consume_kafka_events_with_audit(
        kafka_config={
            "kafka": {
                "enabled": True,
                "audit_consumer": {
                    "enabled": True,
                    "topic_keys": ["cw2_risk_actions_requested"],
                    "max_batch_messages": 1,
                    "max_idle_polls": 1,
                },
            }
        },
        engine=object(),
    )

    assert summary["status"] == "ok"
    assert summary["processed_count"] == 1
    assert summary["committed_count"] == 1
    assert summary["lag_snapshot_count"] == 2
    assert committed == [{"topic": "topic-a", "partition": 0, "offset": 5}]
    assert health["snapshot_type"] == "kafka_event_audit"
    assert consumer.closed is True


def test_main_returns_nonzero_for_warning_status(monkeypatch, capsys):
    monkeypatch.setattr(
        kafka_audit_mod,
        "_build_parser",
        lambda: type(
            "_Parser",
            (),
            {
                "parse_args": staticmethod(
                    lambda: SimpleNamespace(
                        cw1_config="cw1.yaml",
                        cw2_config="cw2.yaml",
                        max_messages=10,
                        poll_timeout_ms=1000,
                        max_idle_polls=2,
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        kafka_audit_mod,
        "run_kafka_event_audit_from_config",
        lambda **kwargs: {"status": "warning", "processed_count": 0},  # noqa: ARG005
    )

    rc = kafka_audit_mod.main()
    captured = capsys.readouterr()

    assert rc == 1
    assert '"status": "warning"' in captured.out
