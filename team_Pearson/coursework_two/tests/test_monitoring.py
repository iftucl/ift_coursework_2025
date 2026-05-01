"""Unit tests for CW2 operational monitoring helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone

from team_Pearson.coursework_two.modules.ops import audit as audit_mod
from team_Pearson.coursework_two.modules.ops import monitoring as monitoring_mod


class _FakeBegin:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, sql, params):  # noqa: ARG002
        self._sink.append(dict(params))


class _FakeEngine:
    def __init__(self):
        self.calls = []

    def begin(self):
        return _FakeBegin(self.calls)


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]

    def first(self):
        return dict(self._rows[0]) if self._rows else None

    def all(self):
        return [dict(row) for row in self._rows]


class _FakeConn:
    def __init__(self, results_by_sql):
        self._results_by_sql = results_by_sql

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, sql, params=None):  # noqa: ARG002
        sql_text = str(sql)
        rows = self._results_by_sql.get(sql_text, [])
        return _FakeResult(rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]

    def mappings(self):
        return _FakeMappingsResult(self._rows)

    def __iter__(self):
        for row in self._rows:
            yield type("_Row", (), {"_mapping": dict(row)})()


class _FakeConnectEngine:
    def __init__(self, results_by_sql):
        self._results_by_sql = results_by_sql

    def connect(self):
        return _FakeConn(self._results_by_sql)


class _FakeCursor:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, sql_text):
        self._sink.append(sql_text)


class _FakeRawConnection:
    def __init__(self):
        self.executed = []
        self.committed = False
        self.closed = False

    def cursor(self):
        return _FakeCursor(self.executed)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class _FakeRawEngine:
    def __init__(self, raw_conn):
        self._raw_conn = raw_conn

    def raw_connection(self):
        return self._raw_conn


def test_record_ops_event_normalizes_and_upserts_payload():
    engine = _FakeEngine()

    monitoring_mod.record_ops_event(
        engine=engine,
        event_id="evt-1",
        event_type="backtest_run_status",
        producer_component="cw2.backtest_writer",
        topic_key="platform_run_status",
        topic_name="platform.runs.status.v1",
        run_id="run-123",
        symbol="AAPL",
        severity="high",
        publish_status="published",
        event_time="2026-04-16",
        payload={"run_id": "run-123", "status": "completed"},
    )

    assert len(engine.calls) == 1
    params = engine.calls[0]
    assert params["event_id"] == "evt-1"
    assert params["event_type"] == "backtest_run_status"
    assert params["producer_component"] == "cw2.backtest_writer"
    assert params["severity"] == "warning"
    assert params["publish_status"] == "published"
    assert params["run_id"] == "run-123"
    assert params["symbol"] == "AAPL"
    assert '"status": "completed"' in params["payload_json"]


def test_record_pipeline_run_shapes_control_plane_payload(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(monitoring_mod, "_ensure_ops_monitoring_schema_once", lambda engine: None)

    ok = monitoring_mod.record_pipeline_run(
        engine=engine,
        pipeline_name="cw2_backtest_analysis_report",
        execution_key="cw2_backtest_analysis_report:ctx.json",
        status="completed",
        trigger_source="airflow",
        latest_stage_name="verify",
        run_id="run-123",
        report_id="report-123",
        started_at="2026-04-21T10:00:00+00:00",
        completed_at="2026-04-21T10:05:00+00:00",
        context={"dag": "cw2_backtest_analysis_report"},
        metrics={"artifact_count": 4},
    )

    assert ok is True
    params = engine.calls[0]
    assert params["pipeline_name"] == "cw2_backtest_analysis_report"
    assert params["execution_key"] == "cw2_backtest_analysis_report:ctx.json"
    assert params["status"] == "completed"
    assert params["trigger_source"] == "airflow"
    assert params["duration_ms"] == 300000
    assert '"artifact_count": 4' in params["metrics_json"]


def test_record_stage_run_shapes_lock_and_result_payload(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(monitoring_mod, "_ensure_ops_monitoring_schema_once", lambda engine: None)

    ok = monitoring_mod.record_stage_run(
        engine=engine,
        pipeline_name="cw2_backtest_analysis_report",
        stage_name="report",
        execution_key="cw2_backtest_analysis_report:ctx.json:report",
        stage_status="completed",
        stage_order=30,
        trigger_source="airflow",
        lock_name="cw2:report:ctx",
        lock_backend="redis",
        lock_key="cw2:runtime:lock:report",
        idempotency_key="idemp-123",
        started_at="2026-04-21T10:10:00+00:00",
        completed_at="2026-04-21T10:10:30+00:00",
        payload={"report_name": "demo"},
        result={"artifact_count": 4},
    )

    assert ok is True
    params = engine.calls[0]
    assert params["stage_name"] == "report"
    assert params["stage_status"] == "completed"
    assert params["stage_order"] == 30
    assert params["lock_backend"] == "redis"
    assert params["duration_ms"] == 30000
    assert '"artifact_count": 4' in params["result_json"]


def test_run_monitor_from_config_persists_health_snapshot(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        monitoring_mod,
        "ensure_ops_monitoring_schema",
        lambda engine: captured.setdefault("schema", engine),
    )
    monkeypatch.setattr(
        monitoring_mod,
        "record_health_snapshot",
        lambda **kwargs: captured.update(kwargs) or "snapshot-123",
    )
    monkeypatch.setattr(
        monitoring_mod,
        "summarize_recent_monitoring",
        lambda engine: {
            "recent_event_counts": [{"event_type": "backtest_run_status", "event_count": 2}]
        },
    )
    monkeypatch.setattr(
        audit_mod,
        "run_audit_from_config",
        lambda **kwargs: {
            "readiness": {
                "overall_status": "ready",
                "core_sql_ready": True,
                "feature_pipeline_ready": True,
                "storage_ready": True,
                "kafka_ready": True,
                "kafka_event_audit_ready": True,
                "backtest_ready": True,
            },
            "storage": {"kafka": {"status": "ok"}},
        },
    )

    report = monitoring_mod.run_monitor_from_config(
        cw1_config_path="cw1.yaml",
        cw2_config_path="cw2.yaml",
        db_engine=object(),
    )

    assert report["ops_health_snapshot_id"] == "snapshot-123"
    assert report["audit"]["readiness"]["overall_status"] == "ready"
    assert captured["snapshot_type"] == "readiness_audit"
    assert captured["component"] == "platform"
    assert captured["status"] == "ready"
    assert captured["summary"]["kafka_ready"] is True


def test_ensure_ops_monitoring_schema_and_cache_guard(monkeypatch):
    raw_conn = _FakeRawConnection()
    engine = _FakeRawEngine(raw_conn)
    monitoring_mod.ensure_ops_monitoring_schema(engine)

    assert raw_conn.executed
    assert "ops_pipeline_runs" in raw_conn.executed[0]
    assert raw_conn.committed is True
    assert raw_conn.closed is True

    monitoring_mod._SCHEMA_READY_ENGINES.clear()
    ensured = []
    monkeypatch.setattr(
        monitoring_mod,
        "ensure_ops_monitoring_schema",
        lambda engine: ensured.append(id(engine)),
    )

    engine_a = object()
    engine_b = object()
    monitoring_mod._ensure_ops_monitoring_schema_once(engine_a)
    monitoring_mod._ensure_ops_monitoring_schema_once(engine_a)
    monitoring_mod._ensure_ops_monitoring_schema_once(engine_b)

    assert ensured == [id(engine_a), id(engine_b)]


def test_summarize_recent_monitoring_reads_recent_sql_state():
    lookback_hours = 1
    counts_sql = f"""
        SELECT event_type, publish_status, COUNT(*) AS event_count
        FROM systematic_equity.ops_event_log
        WHERE event_time >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY event_type, publish_status
        ORDER BY event_type, publish_status
        """
    latest_snapshot_sql = """
        SELECT component, snapshot_type, status, created_at
        FROM systematic_equity.ops_health_snapshots
        ORDER BY created_at DESC
        LIMIT 1
        """
    consumer_counts_sql = f"""
        SELECT ack_status, COUNT(*) AS event_count
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE consumed_at >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY ack_status
        ORDER BY ack_status
        """
    dead_letter_sql = f"""
        SELECT COUNT(*) AS dead_letter_count
        FROM systematic_equity.ops_kafka_dead_letter
        WHERE created_at >= NOW() - INTERVAL '{lookback_hours} hours'
        """
    latest_lag_sql = """
        WITH latest_sample AS (
            SELECT MAX(sampled_at) AS sampled_at
            FROM systematic_equity.ops_kafka_lag_snapshots
        )
        SELECT consumer_group,
               MAX(sampled_at) AS sampled_at,
               COUNT(*) AS partition_count,
               MAX(lag) AS max_lag,
               SUM(lag) AS total_lag
        FROM systematic_equity.ops_kafka_lag_snapshots
        WHERE sampled_at = (SELECT sampled_at FROM latest_sample)
        GROUP BY consumer_group
        ORDER BY consumer_group
        """
    sampled_at = datetime(2026, 4, 20, 12, 30, tzinfo=timezone.utc)
    engine = _FakeConnectEngine(
        {
            counts_sql: [
                {
                    "event_type": "cw2_scheduler_stage",
                    "publish_status": "published",
                    "event_count": 3,
                }
            ],
            consumer_counts_sql: [{"ack_status": "processed", "event_count": 2}],
            dead_letter_sql: [{"dead_letter_count": 1}],
            latest_lag_sql: [
                {
                    "consumer_group": "team_pearson_cw2_audit",
                    "sampled_at": sampled_at,
                    "partition_count": 2,
                    "max_lag": 4,
                    "total_lag": 6,
                }
            ],
            latest_snapshot_sql: [
                {
                    "component": "platform",
                    "snapshot_type": "readiness_audit",
                    "status": "ok",
                    "created_at": sampled_at,
                }
            ],
        }
    )

    summary = monitoring_mod.summarize_recent_monitoring(engine, lookback_hours=0)

    assert summary["lookback_hours"] == 1
    assert summary["recent_event_counts"][0]["event_type"] == "cw2_scheduler_stage"
    assert summary["recent_consumer_ack_counts"][0]["ack_status"] == "processed"
    assert summary["recent_dead_letter_count"] == 1
    assert summary["latest_kafka_lag"][0]["sampled_at"] == sampled_at.isoformat()
    assert summary["latest_health_snapshot"]["snapshot_type"] == "readiness_audit"


def test_monitoring_helper_normalizers_cover_edge_cases():
    event_id = monitoring_mod._derive_event_id(
        "cw2_event",
        {"run_id": "run-1", "symbol": "AAPL", "event_date": "2026-04-21"},
    )
    assert event_id == "cw2_event:run-1:AAPL:2026-04-21"

    naive_dt = datetime(2026, 4, 21, 9, 0)
    aware_dt = monitoring_mod._normalize_event_time("2026-04-21T09:00:00Z")
    assert monitoring_mod._normalize_event_time(None).tzinfo is not None
    assert monitoring_mod._normalize_event_time(naive_dt).tzinfo is not None
    assert (
        monitoring_mod._normalize_event_time(date(2026, 4, 21)).date().isoformat() == "2026-04-21"
    )
    assert aware_dt.tzinfo is not None
    assert monitoring_mod._normalize_event_time("2026-04-21").date().isoformat() == "2026-04-21"
    assert monitoring_mod._normalize_event_time("").tzinfo is not None
    try:
        monitoring_mod._normalize_event_time("not-a-date")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for malformed date text")

    assert monitoring_mod._normalize_run_date(naive_dt) == "2026-04-21"
    assert monitoring_mod._normalize_run_date(date(2026, 4, 21)) == "2026-04-21"
    assert monitoring_mod._normalize_run_date("2026-04-21T09:00:00Z") == "2026-04-21"
    assert monitoring_mod._normalize_run_date("") is None
    assert monitoring_mod._normalize_optional_text("  value ") == "value"
    assert monitoring_mod._normalize_optional_text("   ") is None

    assert monitoring_mod._normalize_severity("urgent") == "warning"
    assert monitoring_mod._normalize_severity("other") == "info"
    assert monitoring_mod._normalize_publish_status("bad") == "recorded"
    assert monitoring_mod._normalize_trigger_source("cron") == "manual"
    assert monitoring_mod._normalize_pipeline_status("custom") == "running"
    assert monitoring_mod._normalize_stage_status("custom") == "started"
    assert monitoring_mod._normalize_ack_status("custom") == "consumed"
    assert monitoring_mod._normalize_lag_status("custom") == "ok"
    assert monitoring_mod._normalize_health_status("ready") == "ok"
    assert monitoring_mod._normalize_health_status("custom") == "partial"
    assert monitoring_mod._coerce_boolish("yes", default=False) is True
    assert monitoring_mod._coerce_boolish(None, default=True) is True
    assert (
        monitoring_mod._duration_ms(
            datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 21, 9, 0, 1, tzinfo=timezone.utc),
        )
        == 1000
    )
    assert (
        monitoring_mod._duration_ms(
            datetime(2026, 4, 21, 9, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
        )
        == 0
    )
    assert monitoring_mod._duration_ms(None, aware_dt) is None
    assert monitoring_mod._json_default(aware_dt) == aware_dt.isoformat()
    assert monitoring_mod._json_default(date(2026, 4, 21)) == "2026-04-21"
    assert monitoring_mod._json_default(object()).startswith("<object object")


def test_summarize_kafka_event_audit_reports_disabled_without_querying_sql():
    summary = monitoring_mod.summarize_kafka_event_audit(
        object(),
        kafka_config={"kafka": {"enabled": False}},
        lookback_hours=12,
    )

    assert summary["status"] == "disabled"
    assert summary["processing_scope"] == "kafka_disabled"
    assert summary["confirms_external_execution"] is False
    assert summary["published_count"] == 0
    assert summary["processed_count"] == 0


def test_summarize_kafka_event_audit_reports_warning_for_pending_and_lag():
    lookback_hours = 24
    consumer_group = "team_pearson_cw2_audit"
    published_sql = f"""
        SELECT COUNT(*) AS published_count
        FROM (
            SELECT DISTINCT event_id
            FROM systematic_equity.ops_event_log
            WHERE publish_status = 'published'
              AND event_time >= NOW() - INTERVAL '{lookback_hours} hours'
        ) AS published_events
        """
    ack_sql = f"""
        SELECT ack_status, COUNT(*) AS event_count
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY ack_status
        ORDER BY ack_status
        """
    component_sql = f"""
        SELECT consumer_component, MAX(updated_at) AS last_seen_at
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY consumer_component
        ORDER BY MAX(updated_at) DESC, consumer_component
        """
    pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '2 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    stale_pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS stale_pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '60 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    self_audit_pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS self_audit_pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_type = 'cw2_scheduler_stage'
          AND e.producer_component = 'cw2.scheduler.kafka_event_audit'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '2 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    dead_letter_sql = f"""
        SELECT COUNT(*) AS dead_letter_count
        FROM systematic_equity.ops_kafka_dead_letter
        WHERE consumer_group = :consumer_group
          AND created_at >= NOW() - INTERVAL '{lookback_hours} hours'
        """
    latest_lag_sql = """
        WITH latest_sample AS (
            SELECT MAX(sampled_at) AS sampled_at
            FROM systematic_equity.ops_kafka_lag_snapshots
            WHERE consumer_group = :consumer_group
        )
        SELECT MAX(sampled_at) AS sampled_at,
               COUNT(*) AS partition_count,
               MAX(lag) AS max_lag,
               SUM(lag) AS total_lag,
               SUM(CASE WHEN lag_status = 'warning' THEN 1 ELSE 0 END) AS warning_partitions,
               SUM(CASE WHEN lag_status = 'error' THEN 1 ELSE 0 END) AS error_partitions
        FROM systematic_equity.ops_kafka_lag_snapshots
        WHERE consumer_group = :consumer_group
          AND sampled_at = (SELECT sampled_at FROM latest_sample)
        """
    engine = _FakeConnectEngine(
        {
            published_sql: [{"published_count": 4}],
            ack_sql: [
                {"ack_status": "processed", "event_count": 2},
                {"ack_status": "failed", "event_count": 1},
            ],
            component_sql: [
                {
                    "consumer_component": "cw2.kafka_audit_daemon",
                    "last_seen_at": datetime.now(timezone.utc),
                }
            ],
            pending_sql: [{"pending_count": 2}],
            stale_pending_sql: [{"stale_pending_count": 2}],
            self_audit_pending_sql: [{"self_audit_pending_count": 0}],
            dead_letter_sql: [{"dead_letter_count": 0}],
            latest_lag_sql: [
                {
                    "sampled_at": datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
                    "partition_count": 3,
                    "max_lag": 125,
                    "total_lag": 130,
                    "warning_partitions": 1,
                    "error_partitions": 0,
                }
            ],
        }
    )

    summary = monitoring_mod.summarize_kafka_event_audit(
        engine,
        kafka_config={
            "kafka": {
                "enabled": True,
                "audit_consumer": {
                    "consumer_group": consumer_group,
                    "lag_warning_threshold": 100,
                    "freshness_warning_minutes": 60,
                },
            }
        },
        lookback_hours=lookback_hours,
    )

    assert summary["status"] == "warning"
    assert summary["processing_scope"] == "dedicated_audit_consumer"
    assert summary["external_executor_present"] is False
    assert summary["consumer_components"] == ["cw2.kafka_audit_daemon"]
    assert summary["published_count"] == 4
    assert summary["processed_count"] == 2
    assert summary["failed_count"] == 1
    assert summary["raw_pending_count"] == 2
    assert summary["reconciled_orphan_count"] == 0
    assert summary["reconciled_self_audit_count"] == 0
    assert summary["pending_count"] == 2
    assert summary["max_lag"] == 125


def test_summarize_kafka_event_audit_reconciles_stale_orphans_when_lag_is_zero():
    lookback_hours = 24
    consumer_group = "team_pearson_cw2_audit"
    published_sql = f"""
        SELECT COUNT(*) AS published_count
        FROM (
            SELECT DISTINCT event_id
            FROM systematic_equity.ops_event_log
            WHERE publish_status = 'published'
              AND event_time >= NOW() - INTERVAL '{lookback_hours} hours'
        ) AS published_events
        """
    ack_sql = f"""
        SELECT ack_status, COUNT(*) AS event_count
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY ack_status
        ORDER BY ack_status
        """
    component_sql = f"""
        SELECT consumer_component, MAX(updated_at) AS last_seen_at
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY consumer_component
        ORDER BY MAX(updated_at) DESC, consumer_component
        """
    pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '2 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    stale_pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS stale_pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '60 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    self_audit_pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS self_audit_pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_type = 'cw2_scheduler_stage'
          AND e.producer_component = 'cw2.scheduler.kafka_event_audit'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '2 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    dead_letter_sql = f"""
        SELECT COUNT(*) AS dead_letter_count
        FROM systematic_equity.ops_kafka_dead_letter
        WHERE consumer_group = :consumer_group
          AND created_at >= NOW() - INTERVAL '{lookback_hours} hours'
        """
    latest_lag_sql = """
        WITH latest_sample AS (
            SELECT MAX(sampled_at) AS sampled_at
            FROM systematic_equity.ops_kafka_lag_snapshots
            WHERE consumer_group = :consumer_group
        )
        SELECT MAX(sampled_at) AS sampled_at,
               COUNT(*) AS partition_count,
               MAX(lag) AS max_lag,
               SUM(lag) AS total_lag,
               SUM(CASE WHEN lag_status = 'warning' THEN 1 ELSE 0 END) AS warning_partitions,
               SUM(CASE WHEN lag_status = 'error' THEN 1 ELSE 0 END) AS error_partitions
        FROM systematic_equity.ops_kafka_lag_snapshots
        WHERE consumer_group = :consumer_group
          AND sampled_at = (SELECT sampled_at FROM latest_sample)
        """
    engine = _FakeConnectEngine(
        {
            published_sql: [{"published_count": 4}],
            ack_sql: [{"ack_status": "processed", "event_count": 2}],
            component_sql: [
                {
                    "consumer_component": "cw2.kafka_audit_daemon",
                    "last_seen_at": datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
                }
            ],
            pending_sql: [{"pending_count": 2}],
            stale_pending_sql: [{"stale_pending_count": 2}],
            self_audit_pending_sql: [{"self_audit_pending_count": 0}],
            dead_letter_sql: [{"dead_letter_count": 0}],
            latest_lag_sql: [
                {
                    "sampled_at": datetime.now(timezone.utc),
                    "partition_count": 3,
                    "max_lag": 0,
                    "total_lag": 0,
                    "warning_partitions": 0,
                    "error_partitions": 0,
                }
            ],
        }
    )

    summary = monitoring_mod.summarize_kafka_event_audit(
        engine,
        kafka_config={
            "kafka": {
                "enabled": True,
                "audit_consumer": {
                    "consumer_group": consumer_group,
                    "lag_warning_threshold": 100,
                    "freshness_warning_minutes": 60,
                    "orphan_reconcile_minutes": 60,
                },
            }
        },
        lookback_hours=lookback_hours,
    )

    assert summary["status"] == "ok"
    assert summary["processing_scope"] == "dedicated_audit_consumer"
    assert summary["raw_pending_count"] == 2
    assert summary["reconciled_orphan_count"] == 2
    assert summary["reconciled_self_audit_count"] == 0
    assert summary["pending_count"] == 0


def test_summarize_kafka_event_audit_reconciles_recent_self_audit_when_consumer_is_healthy():
    lookback_hours = 24
    consumer_group = "team_pearson_cw2_audit"
    published_sql = f"""
        SELECT COUNT(*) AS published_count
        FROM (
            SELECT DISTINCT event_id
            FROM systematic_equity.ops_event_log
            WHERE publish_status = 'published'
              AND event_time >= NOW() - INTERVAL '{lookback_hours} hours'
        ) AS published_events
        """
    ack_sql = f"""
        SELECT ack_status, COUNT(*) AS event_count
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY ack_status
        ORDER BY ack_status
        """
    component_sql = f"""
        SELECT consumer_component, MAX(updated_at) AS last_seen_at
        FROM systematic_equity.ops_kafka_consumer_ack
        WHERE consumer_group = :consumer_group
          AND updated_at >= NOW() - INTERVAL '{lookback_hours} hours'
        GROUP BY consumer_component
        ORDER BY MAX(updated_at) DESC, consumer_component
        """
    pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '2 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    stale_pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS stale_pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '60 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    self_audit_pending_sql = f"""
        WITH ack_state AS (
            SELECT event_id,
                   MAX(CASE WHEN ack_status = 'processed' THEN 1 ELSE 0 END) AS has_processed
            FROM systematic_equity.ops_kafka_consumer_ack
            WHERE consumer_group = :consumer_group
            GROUP BY event_id
        )
        SELECT COUNT(*) AS self_audit_pending_count
        FROM systematic_equity.ops_event_log e
        LEFT JOIN ack_state a
               ON a.event_id = e.event_id
        WHERE e.publish_status = 'published'
          AND e.event_type = 'cw2_scheduler_stage'
          AND e.producer_component = 'cw2.scheduler.kafka_event_audit'
          AND e.event_time >= NOW() - INTERVAL '{lookback_hours} hours'
          AND e.event_time < NOW() - INTERVAL '2 minutes'
          AND COALESCE(a.has_processed, 0) = 0
        """
    dead_letter_sql = f"""
        SELECT COUNT(*) AS dead_letter_count
        FROM systematic_equity.ops_kafka_dead_letter
        WHERE consumer_group = :consumer_group
          AND created_at >= NOW() - INTERVAL '{lookback_hours} hours'
        """
    latest_lag_sql = """
        WITH latest_sample AS (
            SELECT MAX(sampled_at) AS sampled_at
            FROM systematic_equity.ops_kafka_lag_snapshots
            WHERE consumer_group = :consumer_group
        )
        SELECT MAX(sampled_at) AS sampled_at,
               COUNT(*) AS partition_count,
               MAX(lag) AS max_lag,
               SUM(lag) AS total_lag,
               SUM(CASE WHEN lag_status = 'warning' THEN 1 ELSE 0 END) AS warning_partitions,
               SUM(CASE WHEN lag_status = 'error' THEN 1 ELSE 0 END) AS error_partitions
        FROM systematic_equity.ops_kafka_lag_snapshots
        WHERE consumer_group = :consumer_group
          AND sampled_at = (SELECT sampled_at FROM latest_sample)
        """
    engine = _FakeConnectEngine(
        {
            published_sql: [{"published_count": 3}],
            ack_sql: [{"ack_status": "processed", "event_count": 2}],
            component_sql: [
                {
                    "consumer_component": "cw2.kafka_audit_daemon",
                    "last_seen_at": datetime.now(timezone.utc),
                }
            ],
            pending_sql: [{"pending_count": 1}],
            stale_pending_sql: [{"stale_pending_count": 0}],
            self_audit_pending_sql: [{"self_audit_pending_count": 1}],
            dead_letter_sql: [{"dead_letter_count": 0}],
            latest_lag_sql: [
                {
                    "sampled_at": datetime.now(timezone.utc),
                    "partition_count": 3,
                    "max_lag": 0,
                    "total_lag": 0,
                    "warning_partitions": 0,
                    "error_partitions": 0,
                }
            ],
        }
    )

    summary = monitoring_mod.summarize_kafka_event_audit(
        engine,
        kafka_config={
            "kafka": {
                "enabled": True,
                "audit_consumer": {
                    "consumer_group": consumer_group,
                    "lag_warning_threshold": 100,
                    "freshness_warning_minutes": 60,
                    "pending_grace_minutes": 2,
                    "orphan_reconcile_minutes": 60,
                },
            }
        },
        lookback_hours=lookback_hours,
    )

    assert summary["status"] == "ok"
    assert summary["processing_scope"] == "dedicated_audit_consumer"
    assert summary["raw_pending_count"] == 1
    assert summary["reconciled_orphan_count"] == 0
    assert summary["reconciled_self_audit_count"] == 1
    assert summary["pending_count"] == 0


def test_record_kafka_consumer_ack_persists_normalized_payload():
    engine = _FakeEngine()

    ok = monitoring_mod.record_kafka_consumer_ack(
        engine=engine,
        event_id="evt-1",
        topic_name="platform.runs.status.v1",
        consumer_group="team_pearson_cw2_audit",
        consumer_component="cw2.kafka_audit_consumer",
        kafka_partition=1,
        kafka_offset=42,
        payload={"event_type": "run_status", "run_id": "run-1", "symbol": "AAPL"},
        message_key="run-1",
        headers={"source": "cw2"},
        ack_status="processed",
        retry_count=2,
        last_error="",
        consumed_at="2026-04-21T10:00:00+00:00",
        processed_at="2026-04-21T10:00:05+00:00",
    )

    assert ok is True
    params = engine.calls[0]
    assert params["topic_name"] == "platform.runs.status.v1"
    assert params["ack_status"] == "processed"
    assert params["retry_count"] == 2
    assert '"run_id": "run-1"' in params["payload_json"]
    assert '"source": "cw2"' in params["headers_json"]


def test_record_kafka_dead_letter_and_lag_snapshot_shape_rows():
    engine = _FakeEngine()

    dead_letter_ok = monitoring_mod.record_kafka_dead_letter(
        engine=engine,
        event_id="evt-2",
        topic_name="cw2.risk.actions.executed.v1",
        consumer_group="team_pearson_cw2_audit",
        consumer_component="cw2.kafka_audit_consumer",
        kafka_partition=0,
        kafka_offset=7,
        dead_letter_reason="payload_parse_failed",
        payload={"event_type": "risk_action", "symbol": "MSFT"},
        headers={"source": "cw2"},
        error_text="invalid json",
    )
    lag_ok = monitoring_mod.record_kafka_lag_snapshot(
        engine=engine,
        consumer_group="team_pearson_cw2_audit",
        topic_name="platform.runs.status.v1",
        partition_id=0,
        committed_offset=5,
        high_watermark=9,
        lag=4,
        lag_status="warning",
        sampled_at="2026-04-21T10:10:00+00:00",
    )

    assert dead_letter_ok is True
    assert lag_ok is True
    dead_letter_params = engine.calls[0]
    lag_params = engine.calls[1]
    assert dead_letter_params["dead_letter_reason"] == "payload_parse_failed"
    assert '"symbol": "MSFT"' in dead_letter_params["payload_json"]
    assert lag_params["lag"] == 4
    assert lag_params["lag_status"] == "warning"


def test_record_health_snapshot_returns_id_and_builds_json_payload():
    engine = _FakeEngine()

    snapshot_id = monitoring_mod.record_health_snapshot(
        engine=engine,
        snapshot_type="readiness_audit",
        component="platform",
        status="ready",
        run_date="2026-04-21",
        summary={"overall_status": "ready"},
        details={"kafka_ready": True},
    )

    assert snapshot_id
    params = engine.calls[0]
    assert params["snapshot_id"] == snapshot_id
    assert params["status"] == "ok"
    assert '"overall_status": "ready"' in params["summary_json"]
    assert '"kafka_ready": true' in params["details_json"]


def test_build_kafka_topic_name_uses_resolved_mapping(monkeypatch):
    monkeypatch.setattr(
        monitoring_mod,
        "resolve_kafka_config",
        lambda config, *, default_client_id: type(  # noqa: ARG005
            "_Resolved",
            (),
            {"topics": {"platform_run_status": "platform.runs.status.v1"}},
        )(),
    )

    topic_name = monitoring_mod.build_kafka_topic_name(
        {"kafka": {"enabled": True}},
        topic_key="platform_run_status",
        default_topic="fallback",
        default_client_id="cw2_monitor",
    )

    assert topic_name == "platform.runs.status.v1"
