"""Unit tests for backtest writer payload shaping."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from team_Pearson.coursework_two.modules.backtest import writer as writer_mod
from team_Pearson.coursework_two.modules.backtest.writer import (
    _build_backtest_run_payload,
    compute_config_hash,
)


def test_build_backtest_run_payload_includes_explicit_version_fields():
    payload = _build_backtest_run_payload(
        run_id="run-123",
        run_name="bt_demo",
        config_snapshot={
            "backtest": {
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "rebalance_frequency": "monthly",
                "execution_lag": 1,
                "transaction_cost_bps": 12.5,
                "weighting": "mean_variance",
                "top_n": 25,
                "benchmark_ticker": "SPY",
            },
            "governance": {
                "versions": {
                    "model_version": "model-v2",
                    "backtest_engine_version": "backtest-v2",
                    "risk_overlay_policy_version": "overlay-v2",
                }
            },
        },
    )

    assert payload["run_id"] == "run-123"
    assert payload["run_name"] == "bt_demo"
    assert payload["model_version"] == "model-v2"
    assert payload["backtest_engine_version"] == "backtest-v2"
    assert payload["risk_overlay_policy_version"] == "overlay-v2"
    assert payload["config_hash"] == compute_config_hash(
        {
            "backtest": {
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "rebalance_frequency": "monthly",
                "execution_lag": 1,
                "transaction_cost_bps": 12.5,
                "weighting": "mean_variance",
                "top_n": 25,
                "benchmark_ticker": "SPY",
            },
            "governance": {
                "versions": {
                    "model_version": "model-v2",
                    "backtest_engine_version": "backtest-v2",
                    "risk_overlay_policy_version": "overlay-v2",
                }
            },
        }
    )
    assert payload["transaction_cost_bps"] == 12.5
    assert payload["factor_definition_version"]
    assert payload["covariance_method_version"]


def test_compute_config_hash_is_stable_across_dict_ordering():
    left = {
        "backtest": {"end_date": "2026-04-14", "start_date": "2021-04-14"},
        "governance": {"versions": {"model_version": "model-v2"}},
    }
    right = {
        "governance": {"versions": {"model_version": "model-v2"}},
        "backtest": {"start_date": "2021-04-14", "end_date": "2026-04-14"},
    }

    assert compute_config_hash(left) == compute_config_hash(right)


def test_publish_run_status_event_uses_platform_status_topic(monkeypatch):
    captured = {}

    def fake_publish(config, *, topic_key, default_topic, events, key_field, default_client_id):
        captured["topic_key"] = topic_key
        captured["default_topic"] = default_topic
        captured["events"] = list(events)
        captured["key_field"] = key_field
        captured["default_client_id"] = default_client_id
        return len(events)

    monkeypatch.setattr(writer_mod, "publish_json_events", fake_publish)

    writer_mod._publish_run_status_event(
        {"kafka": {"enabled": True}},
        {"run_id": "run-1", "status": "completed", "event_type": "backtest_run_status"},
    )

    assert captured["topic_key"] == "platform_run_status"
    assert captured["default_topic"] == "platform.runs.status.v1"
    assert captured["key_field"] == "run_id"
    assert captured["default_client_id"] == "team_pearson_cw2"
    assert captured["events"][0]["run_id"] == "run-1"


def test_publish_run_status_event_records_ops_event_when_engine_provided(monkeypatch):
    captured = {}

    monkeypatch.setattr(writer_mod, "publish_json_events", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        writer_mod,
        "resolve_kafka_config",
        lambda config, *, default_client_id: SimpleNamespace(  # noqa: ARG005
            enabled=True,
            topics={"platform_run_status": "platform.runs.status.v1"},
        ),
    )
    monkeypatch.setattr(writer_mod, "record_ops_event", lambda **kwargs: captured.update(kwargs))

    writer_mod._publish_run_status_event(
        {"kafka": {"enabled": True}},
        {
            "event_id": "run-1:completed",
            "run_id": "run-1",
            "status": "completed",
            "event_type": "backtest_run_status",
        },
        engine=object(),
    )

    assert captured["producer_component"] == "cw2.backtest_writer"
    assert captured["topic_key"] == "platform_run_status"
    assert captured["topic_name"] == "platform.runs.status.v1"
    assert captured["publish_status"] == "published"
    assert captured["run_id"] == "run-1"


def test_write_execution_ledger_targets_execution_table(monkeypatch):
    captured = {}

    def fake_upsert(engine, *, table_name, records, allowed_cols, conflict_cols):  # noqa: ARG001
        captured["table_name"] = table_name
        captured["records"] = list(records)
        captured["allowed_cols"] = list(allowed_cols)
        captured["conflict_cols"] = list(conflict_cols)
        return len(records)

    monkeypatch.setattr(writer_mod, "_upsert_rows", fake_upsert)

    count = writer_mod.write_execution_ledger(
        object(),
        "run-1",
        [
            {
                "rebalance_date": date(2026, 4, 14),
                "execution_date": date(2026, 4, 15),
                "symbol": "AAA",
                "requested_trade_weight": 0.10,
                "executed_trade_weight": 0.08,
                "total_cost": 0.0012,
            }
        ],
    )

    assert count == 1
    assert captured["table_name"] == "backtest_execution_ledger"
    assert captured["records"][0]["run_id"] == "run-1"
    assert "bid_ask_cost" in captured["allowed_cols"]
    assert "had_forward_fill" in captured["allowed_cols"]
    assert "forward_fill_days" in captured["allowed_cols"]
    assert captured["conflict_cols"] == ["run_id", "rebalance_date", "symbol"]


def test_write_performance_targets_period_table(monkeypatch):
    captured = {}

    def fake_upsert(engine, *, table_name, records, allowed_cols, conflict_cols):  # noqa: ARG001
        captured["table_name"] = table_name
        captured["records"] = list(records)
        captured["allowed_cols"] = list(allowed_cols)
        captured["conflict_cols"] = list(conflict_cols)
        return len(records)

    monkeypatch.setattr(writer_mod, "_upsert_rows", fake_upsert)

    count = writer_mod.write_performance(
        object(),
        "run-1",
        [
            {
                "period_end_date": date(2026, 4, 30),
                "net_return": 0.01,
                "forward_filled_symbol_count": 2,
                "forward_fill_day_count": 5,
            }
        ],
    )

    assert count == 1
    assert captured["table_name"] == "backtest_performance"
    assert captured["records"][0]["run_id"] == "run-1"
    assert "forward_filled_symbol_count" in captured["allowed_cols"]
    assert "forward_fill_day_count" in captured["allowed_cols"]
    assert captured["conflict_cols"] == ["run_id", "period_end_date"]


def test_write_holdings_cash_daily_state_and_metrics_use_expected_tables(monkeypatch):
    calls = []

    def fake_upsert(engine, *, table_name, records, allowed_cols, conflict_cols):  # noqa: ARG001
        calls.append(
            {
                "table_name": table_name,
                "records": list(records),
                "allowed_cols": list(allowed_cols),
                "conflict_cols": list(conflict_cols),
            }
        )
        return len(records)

    monkeypatch.setattr(writer_mod, "_upsert_rows", fake_upsert)

    assert (
        writer_mod.write_holdings(
            object(),
            "run-1",
            [
                {
                    "rebalance_date": date(2026, 3, 31),
                    "symbol": "AAA",
                    "target_weight": 0.05,
                }
            ],
        )
        == 1
    )
    assert (
        writer_mod.write_cash_ledger(
            object(),
            "run-1",
            [
                {
                    "rebalance_date": date(2026, 3, 31),
                    "cash_end_weight": 0.02,
                }
            ],
        )
        == 1
    )
    assert (
        writer_mod.write_intraday_daily_state(
            object(),
            "run-1",
            [
                {
                    "state_date": date(2026, 4, 1),
                    "symbol": "AAA",
                    "weight": 0.05,
                }
            ],
        )
        == 1
    )
    assert (
        writer_mod.write_metrics(
            object(),
            "run-1",
            [{"metric_group": "return", "metric_name": "sharpe", "metric_value": 0.58}],
        )
        == 1
    )

    assert [call["table_name"] for call in calls] == [
        "backtest_holdings",
        "backtest_cash_ledger",
        "backtest_intraday_daily_state",
        "backtest_metrics",
    ]
    assert calls[0]["conflict_cols"] == ["run_id", "rebalance_date", "symbol"]
    assert calls[1]["conflict_cols"] == ["run_id", "rebalance_date"]
    assert calls[2]["conflict_cols"] == ["run_id", "state_date", "symbol"]
    assert calls[3]["conflict_cols"] == ["run_id", "metric_group", "metric_name"]


def test_write_intraday_events_publishes_and_records_ops(monkeypatch):
    captured = {}

    monkeypatch.setattr(writer_mod, "_upsert_rows", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        writer_mod,
        "publish_json_events",
        lambda config, *, topic_key, default_topic, events, key_field, default_client_id: captured.update(
            {
                "topic_key": topic_key,
                "default_topic": default_topic,
                "events": list(events),
                "key_field": key_field,
                "default_client_id": default_client_id,
            }
        )
        or 1,
    )
    monkeypatch.setattr(
        writer_mod,
        "_record_ops_events",
        lambda *args, **kwargs: captured.update({"ops": kwargs}),
    )

    inserted = writer_mod.write_intraday_events(
        object(),
        "run-1",
        [
            {
                "event_date": date(2026, 4, 1),
                "event_type": "stop_loss",
                "symbol": "AAA",
                "action_scope": "symbol",
            }
        ],
        config_snapshot={"kafka": {"enabled": True}},
    )

    assert inserted == 1
    assert captured["topic_key"] == "cw2_risk_actions_executed"
    assert captured["default_topic"] == "cw2.risk.actions.executed.v1"
    assert captured["events"][0]["run_id"] == "run-1"
    assert captured["events"][0]["symbol"] == "AAA"
    assert captured["key_field"] == "symbol"
    assert captured["ops"]["published_count"] == 1


def test_create_and_mark_backtest_run_execute_status_sql(monkeypatch):
    class _Result:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, sql, params=None):  # noqa: ANN001
            self.calls.append((str(sql), params or {}))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ARG002
            return False

    class _Engine:
        def __init__(self) -> None:
            self.conn = _Result()

        def begin(self):
            return self.conn

    published = []
    monkeypatch.setattr(
        writer_mod,
        "_publish_run_status_event",
        lambda config, event, *, engine=None: published.append((config, event, engine)),
    )
    monkeypatch.setattr(writer_mod.uuid, "uuid4", lambda: "run-fixed")

    engine = _Engine()
    run_id = writer_mod.create_backtest_run(
        engine,
        run_name="demo",
        config_snapshot={
            "backtest": {
                "start_date": "2021-04-30",
                "end_date": "2026-04-30",
                "rebalance_frequency": "quarterly",
            }
        },
    )
    writer_mod.mark_backtest_completed(engine, run_id, config_snapshot={"run": "cfg"})
    writer_mod.mark_backtest_failed(engine, run_id)

    assert run_id == "run-fixed"
    assert "INSERT INTO systematic_equity.backtest_runs" in engine.conn.calls[0][0]
    assert engine.conn.calls[0][1]["rebalance_freq"] == "quarterly"
    assert "status = 'completed'" in engine.conn.calls[1][0]
    assert "status = 'failed'" in engine.conn.calls[2][0]
    assert [event["status"] for _, event, _ in published] == [
        "running",
        "completed",
        "failed",
    ]


def test_ensure_backtest_schema_executes_primary_and_intraday_sql(tmp_path):
    primary = tmp_path / "schema.sql"
    primary.write_text("CREATE TABLE primary_table(id int);", encoding="utf-8")

    class _Cursor:
        def __init__(self, engine):
            self.engine = engine

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ARG002
            return False

        def execute(self, sql_text):
            self.engine.sql_text = sql_text

    class _RawConn:
        def __init__(self, engine):
            self.engine = engine

        def cursor(self):
            return _Cursor(self.engine)

        def commit(self):
            self.engine.committed = True

        def close(self):
            self.engine.closed = True

    class _Engine:
        def raw_connection(self):
            return _RawConn(self)

    engine = _Engine()

    writer_mod.ensure_backtest_schema(engine, schema_path=str(primary))

    assert "CREATE TABLE primary_table" in engine.sql_text
    assert "backtest_intraday_events" in engine.sql_text
    assert engine.committed is True
    assert engine.closed is True


def test_upsert_rows_returns_zero_for_empty_records():
    assert (
        writer_mod._upsert_rows(
            object(),
            table_name="backtest_metrics",
            records=[],
            allowed_cols=["run_id"],
            conflict_cols=["run_id"],
        )
        == 0
    )


def test_validated_identifier_rejects_unsafe_name():
    try:
        writer_mod._validated_identifier("bad-name")
    except ValueError as exc:
        assert "Invalid SQL identifier" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
