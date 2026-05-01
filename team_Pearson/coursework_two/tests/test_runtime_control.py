from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from team_Pearson.coursework_two.modules.ops import runtime_control as runtime_mod


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.expiry = {}

    def set(self, key, value, nx=False, ex=None):  # noqa: ARG002
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)
        self.expiry.pop(key, None)
        return 1

    def eval(self, script, num_keys, *args):  # noqa: ARG002
        if num_keys == 1:
            key, token = args
            if self.store.get(key) == token:
                self.store.pop(key, None)
                self.expiry.pop(key, None)
                return 1
            return 0
        if num_keys == 2:
            key, metadata_key, token = args
            if self.store.get(key) == token:
                self.store.pop(key, None)
                self.store.pop(metadata_key, None)
                self.expiry.pop(key, None)
                self.expiry.pop(metadata_key, None)
                return 1
        return 0

    def expire(self, key, ttl):
        self.expiry[key] = ttl
        return 1


def test_runtime_lock_uses_redis_when_available(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(runtime_mod, "_get_redis", lambda: fake_redis)

    with runtime_mod.runtime_lock(lock_name="cw2/monthly backfill", ttl_seconds=60) as handle:
        assert handle.backend == "redis"
        assert handle.acquired is True
        assert fake_redis.get(handle.redis_key) == handle.token
        assert handle.metadata_key is not None
        assert fake_redis.get(handle.metadata_key) is not None

    assert fake_redis.get(handle.redis_key) is None
    assert fake_redis.get(handle.metadata_key) is None


def test_runtime_lock_falls_back_when_redis_missing(monkeypatch):
    monkeypatch.setattr(runtime_mod, "_get_redis", lambda: None)

    handle = runtime_mod.acquire_runtime_lock(lock_name="cw2:bundle")

    assert handle.backend == "disabled"
    assert handle.acquired is True


def test_refresh_runtime_lock_updates_metadata(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(runtime_mod, "_get_redis", lambda: fake_redis)

    handle = runtime_mod.acquire_runtime_lock(
        lock_name="cw2:bundle", ttl_seconds=30, heartbeat_interval_seconds=5
    )

    before = json.loads(fake_redis.get(handle.metadata_key))
    assert runtime_mod.refresh_runtime_lock(handle) is True
    after = json.loads(fake_redis.get(handle.metadata_key))

    assert after["token"] == handle.token
    assert after["requested_name"] == "cw2:bundle"
    assert fake_redis.expiry[handle.redis_key] == 30
    assert fake_redis.expiry[handle.metadata_key] == 30
    assert after["last_heartbeat_at_utc"] >= before["last_heartbeat_at_utc"]


def test_refresh_runtime_lock_returns_false_when_lock_lost(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(runtime_mod, "_get_redis", lambda: fake_redis)

    handle = runtime_mod.acquire_runtime_lock(lock_name="cw2:bundle", ttl_seconds=30)
    fake_redis.store[handle.redis_key] = "other-token"

    assert runtime_mod.refresh_runtime_lock(handle) is False


def test_acquire_runtime_lock_reclaims_stale_lock(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(runtime_mod, "_get_redis", lambda: fake_redis)

    stale_token = "stale-token"
    lock_name = "cw2:bundle"
    redis_key = "cw2:runtime:lock:cw2:bundle"
    metadata_key = "cw2:runtime:lockmeta:cw2:bundle"
    fake_redis.store[redis_key] = stale_token
    fake_redis.store[metadata_key] = json.dumps(
        {
            "token": stale_token,
            "requested_name": lock_name,
            "heartbeat_interval_seconds": 5,
            "acquired_at_utc": "2026-04-21T10:00:00+00:00",
            "last_heartbeat_at_utc": "2026-04-21T10:00:10+00:00",
        }
    )

    class _FrozenDatetime:
        @staticmethod
        def now(tz=None):  # noqa: ARG004
            return datetime(2026, 4, 21, 10, 1, 0, tzinfo=timezone.utc)

        @staticmethod
        def fromisoformat(value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(runtime_mod, "datetime", _FrozenDatetime)

    handle = runtime_mod.acquire_runtime_lock(
        lock_name=lock_name, ttl_seconds=30, heartbeat_interval_seconds=5
    )

    assert handle.acquired is True
    assert fake_redis.get(handle.redis_key) == handle.token
    assert handle.token != stale_token
    assert json.loads(fake_redis.get(handle.metadata_key))["token"] == handle.token


def test_acquire_runtime_lock_keeps_fresh_lock(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(runtime_mod, "_get_redis", lambda: fake_redis)

    active_token = "active-token"
    lock_name = "cw2:bundle"
    redis_key = "cw2:runtime:lock:cw2:bundle"
    metadata_key = "cw2:runtime:lockmeta:cw2:bundle"
    fake_redis.store[redis_key] = active_token
    fake_redis.store[metadata_key] = json.dumps(
        {
            "token": active_token,
            "requested_name": lock_name,
            "airflow_dag_id": "cw2_backtest_analysis_report",
            "airflow_task_id": "run_backtest",
            "heartbeat_interval_seconds": 5,
            "acquired_at_utc": "2026-04-21T10:00:00+00:00",
            "last_heartbeat_at_utc": "2026-04-21T10:00:50+00:00",
        }
    )

    class _FrozenDatetime:
        @staticmethod
        def now(tz=None):  # noqa: ARG004
            return datetime(2026, 4, 21, 10, 1, 0, tzinfo=timezone.utc)

        @staticmethod
        def fromisoformat(value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(runtime_mod, "datetime", _FrozenDatetime)

    with pytest.raises(RuntimeError) as exc_info:
        runtime_mod.acquire_runtime_lock(
            lock_name=lock_name, ttl_seconds=30, heartbeat_interval_seconds=5
        )
    message = str(exc_info.value)
    assert "owner_dag='cw2_backtest_analysis_report'" in message
    assert "last_heartbeat_at='2026-04-21T10:00:50+00:00'" in message


def test_merge_stage_context_persists_json(tmp_path: Path):
    context_path = tmp_path / "context.json"

    first = runtime_mod.merge_stage_context(str(context_path), {"run_id": "run-1"})
    second = runtime_mod.merge_stage_context(
        str(context_path), {"report": {"json_path": "report_summary.json"}}
    )

    assert first["run_id"] == "run-1"
    assert second["run_id"] == "run-1"
    assert second["report"]["json_path"] == "report_summary.json"
    assert json.loads(context_path.read_text(encoding="utf-8"))["run_id"] == "run-1"


def test_build_runtime_context_snapshot_compacts_stage_outputs():
    snapshot = runtime_mod.build_runtime_context_snapshot(
        {
            "run_id": "run-1",
            "run_name": "cw2_run",
            "execution_mode": "existing_run",
            "report": {
                "report_id": "report-1",
                "json_path": "outputs/report_summary.json",
                "artifact_count": 3,
            },
            "verification": {
                "passed": True,
                "layer_status": {"layer_1": True, "layer_2": True},
            },
            "audit_kafka_event_bus": {
                "status": "warning",
                "processed_count": 12,
                "reason": "consumer lag",
            },
        },
        context_path="/tmp/cw2-context.json",
        stage_name="bundle",
        extra={"pipeline_name": "cw2_backtest_analysis_report"},
    )

    assert snapshot["context_path"] == "/tmp/cw2-context.json"
    assert snapshot["stage_name"] == "bundle"
    assert snapshot["run_id"] == "run-1"
    assert snapshot["report"]["report_id"] == "report-1"
    assert snapshot["verification"]["passed"] is True
    assert snapshot["audit_kafka_event_bus"]["processed_count"] == 12
    assert snapshot["pipeline_name"] == "cw2_backtest_analysis_report"


def test_emit_scheduler_stage_event_mirrors_publish_status(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        runtime_mod,
        "publish_json_events",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        runtime_mod,
        "resolve_kafka_config",
        lambda config, *, default_client_id: SimpleNamespace(  # noqa: ARG005
            enabled=True,
            topics={"platform_run_status": "platform.runs.status.v1"},
        ),
    )
    monkeypatch.setattr(
        runtime_mod,
        "record_ops_event",
        lambda **kwargs: captured.update(kwargs),
    )

    result = runtime_mod.emit_scheduler_stage_event(
        {"kafka": {"enabled": True}},
        engine=object(),
        producer_component="cw2.scheduler.test",
        stage_name="bundle",
        stage_status="completed",
        execution_key="bundle:run-1",
        payload={"run_id": "run-1"},
    )

    assert result["publish_status"] == "published"
    assert captured["producer_component"] == "cw2.scheduler.test"
    assert captured["topic_name"] == "platform.runs.status.v1"
    assert captured["payload"]["stage_name"] == "bundle"
