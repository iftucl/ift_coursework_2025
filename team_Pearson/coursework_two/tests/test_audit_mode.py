"""Unit tests for the CW2 readiness audit module."""

from __future__ import annotations

from datetime import date

from team_Pearson.coursework_two.modules.ops import audit as audit_mod


class _AuditFakeMappings:
    def __init__(self, row):
        self._row = dict(row)

    def first(self):
        return dict(self._row)


class _AuditFakeResult:
    def __init__(self, row):
        self._row = dict(row)

    def mappings(self):
        return _AuditFakeMappings(self._row)


class _AuditFakeConn:
    def __init__(self):
        self.sql_texts = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, sql, params=None):  # noqa: ARG002
        sql_text = str(sql)
        self.sql_texts.append(sql_text)
        if "AS performance_rows" in sql_text:
            return _AuditFakeResult(
                {
                    "performance_rows": 10,
                    "cash_ledger_rows": 10,
                    "execution_rows": 75,
                }
            )
        if "max_total_cost_diff" in sql_text:
            return _AuditFakeResult(
                {
                    "matched_rows": 10,
                    "max_total_cost_diff": 0.0,
                    "max_turnover_diff": 0.0,
                    "max_cash_end_weight_diff": 0.0,
                }
            )
        if "max_fixed_cost_diff" in sql_text:
            return _AuditFakeResult(
                {
                    "matched_rows": 10,
                    "max_execution_cost_diff": 0.0,
                    "max_fixed_cost_diff": 0.0,
                    "max_gross_turnover_diff": 0.0,
                }
            )
        raise AssertionError(f"unexpected SQL: {sql_text}")


class _AuditFakeEngine:
    def __init__(self):
        self.conn = _AuditFakeConn()

    def connect(self):
        return self.conn


def test_run_audit_from_config_returns_ready_report(monkeypatch):
    monkeypatch.setattr(
        audit_mod,
        "_load_yaml",
        lambda _: {"backtest": {"rebalance_frequency": "monthly"}},
    )
    monkeypatch.setattr(audit_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(
        audit_mod,
        "_audit_sql",
        lambda engine: {
            "connectivity": {"status": "ok", "ping": True},
            "tables": {
                "curated_core": {
                    "factor_observations": {"exists": True, "row_count": 10},
                    "financial_observations": {"exists": True, "row_count": 10},
                    "benchmark_prices": {"exists": True, "row_count": 10},
                },
                "cw2_features": {
                    "feature_universe_screen": {"exists": True, "row_count": 5},
                    "feature_sub_scores": {"exists": True, "row_count": 5},
                    "feature_factor_scores": {"exists": True, "row_count": 5},
                    "feature_risk_overlay": {"exists": True, "row_count": 5},
                    "portfolio_target_positions": {"exists": True, "row_count": 5},
                },
                "backtest": {},
                "analysis": {},
                "intraday_overlay": {},
                "recommendations": {},
            },
        },
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_signal_history",
        lambda engine, cfg: {
            "backtest_ready": True,
            "qualifying_snapshot_count": 4,
            "aligned_month_end_snapshots": [],
        },
    )
    monkeypatch.setattr(audit_mod, "_audit_minio", lambda cfg: {"status": "ok"})
    monkeypatch.setattr(audit_mod, "_audit_mongo", lambda cfg: {"status": "ok"})
    monkeypatch.setattr(
        audit_mod,
        "_audit_sentiment_pipeline_bridge",
        lambda engine, *, cw1_cfg, cw2_cfg: {"status": "ok"},
    )
    monkeypatch.setattr(audit_mod, "_audit_redis", lambda: {"status": "ok"})
    monkeypatch.setattr(
        audit_mod, "_audit_kafka", lambda cw1, cw2: {"enabled": True, "status": "ok"}
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_kafka_event_audit",
        lambda engine, *, cw1_cfg, cw2_cfg: {"status": "ok"},
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_semantic_checks",
        lambda engine, cfg: {
            "portfolio_target_positions": {"status": "ok"},
            "backtest_execution_reconciliation": {"status": "ok"},
            "intraday_trade_blotter_consistency": {"status": "not_applicable"},
            "analysis_backtest_consistency": {"status": "ok"},
        },
    )

    report = audit_mod.run_audit_from_config(cw1_config_path="cw1.yaml", cw2_config_path="cw2.yaml")

    assert report["readiness"]["overall_status"] == "ready"
    assert report["readiness"]["backtest_ready"] is True
    assert report["storage"]["kafka"]["enabled"] is True
    assert report["execution_assurance"]["real_money_trading_enabled"] is False
    assert report["execution_assurance"]["external_executor_present"] is False
    assert (
        report["operating_model"]["architecture"]
        == "hybrid_batch_core_plus_daily_risk_overlay_with_event_bus"
    )


def test_run_audit_from_config_reports_partial_when_backtest_not_ready(monkeypatch):
    monkeypatch.setattr(
        audit_mod,
        "_load_yaml",
        lambda _: {"backtest": {"rebalance_frequency": "monthly"}},
    )
    monkeypatch.setattr(audit_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(
        audit_mod,
        "_audit_sql",
        lambda engine: {
            "connectivity": {"status": "ok", "ping": True},
            "tables": {
                "curated_core": {
                    "factor_observations": {"exists": True, "row_count": 10},
                    "financial_observations": {"exists": True, "row_count": 10},
                    "benchmark_prices": {"exists": True, "row_count": 10},
                },
                "cw2_features": {
                    "feature_universe_screen": {"exists": True, "row_count": 5},
                    "feature_sub_scores": {"exists": True, "row_count": 5},
                    "feature_factor_scores": {"exists": True, "row_count": 5},
                    "feature_risk_overlay": {"exists": True, "row_count": 5},
                    "portfolio_target_positions": {"exists": True, "row_count": 5},
                },
                "backtest": {},
                "analysis": {},
                "intraday_overlay": {},
                "recommendations": {},
            },
        },
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_signal_history",
        lambda engine, cfg: {
            "backtest_ready": False,
            "qualifying_snapshot_count": 1,
            "aligned_month_end_snapshots": [],
        },
    )
    monkeypatch.setattr(audit_mod, "_audit_minio", lambda cfg: {"status": "ok"})
    monkeypatch.setattr(audit_mod, "_audit_mongo", lambda cfg: {"status": "ok"})
    monkeypatch.setattr(
        audit_mod,
        "_audit_sentiment_pipeline_bridge",
        lambda engine, *, cw1_cfg, cw2_cfg: {"status": "ok"},
    )
    monkeypatch.setattr(audit_mod, "_audit_redis", lambda: {"status": "ok"})
    monkeypatch.setattr(
        audit_mod, "_audit_kafka", lambda cw1, cw2: {"enabled": True, "status": "ok"}
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_kafka_event_audit",
        lambda engine, *, cw1_cfg, cw2_cfg: {"status": "ok"},
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_semantic_checks",
        lambda engine, cfg: {
            "portfolio_target_positions": {"status": "ok"},
            "backtest_execution_reconciliation": {"status": "ok"},
            "intraday_trade_blotter_consistency": {"status": "not_applicable"},
            "analysis_backtest_consistency": {"status": "ok"},
        },
    )

    report = audit_mod.run_audit_from_config(cw1_config_path="cw1.yaml", cw2_config_path="cw2.yaml")

    assert report["readiness"]["overall_status"] == "partial"
    assert report["readiness"]["backtest_ready"] is False
    assert "earlier month-end portfolio snapshot" in report["readiness"]["recommended_next_step"]


def test_run_audit_from_config_marks_storage_partial_when_sentiment_bridge_degraded(
    monkeypatch,
):
    monkeypatch.setattr(
        audit_mod,
        "_load_yaml",
        lambda _: {"backtest": {"rebalance_frequency": "monthly"}},
    )
    monkeypatch.setattr(audit_mod, "_load_shared_db_engine", lambda: object())
    monkeypatch.setattr(
        audit_mod,
        "_audit_sql",
        lambda engine: {
            "connectivity": {"status": "ok", "ping": True},
            "tables": {
                "curated_core": {
                    "factor_observations": {"exists": True, "row_count": 10},
                    "financial_observations": {"exists": True, "row_count": 10},
                    "benchmark_prices": {"exists": True, "row_count": 10},
                },
                "cw2_features": {
                    "feature_universe_screen": {"exists": True, "row_count": 5},
                    "feature_sub_scores": {"exists": True, "row_count": 5},
                    "feature_factor_scores": {"exists": True, "row_count": 5},
                    "feature_risk_overlay": {"exists": True, "row_count": 5},
                    "portfolio_target_positions": {"exists": True, "row_count": 5},
                },
                "backtest": {},
                "analysis": {},
                "intraday_overlay": {},
                "recommendations": {},
            },
        },
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_signal_history",
        lambda engine, cfg: {
            "backtest_ready": True,
            "qualifying_snapshot_count": 4,
            "aligned_month_end_snapshots": [],
        },
    )
    monkeypatch.setattr(audit_mod, "_audit_minio", lambda cfg: {"status": "ok"})
    monkeypatch.setattr(audit_mod, "_audit_mongo", lambda cfg: {"status": "ok"})
    monkeypatch.setattr(
        audit_mod,
        "_audit_sentiment_pipeline_bridge",
        lambda engine, *, cw1_cfg, cw2_cfg: {"status": "degraded"},
    )
    monkeypatch.setattr(audit_mod, "_audit_redis", lambda: {"status": "ok"})
    monkeypatch.setattr(
        audit_mod, "_audit_kafka", lambda cw1, cw2: {"enabled": True, "status": "ok"}
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_kafka_event_audit",
        lambda engine, *, cw1_cfg, cw2_cfg: {"status": "ok"},
    )
    monkeypatch.setattr(
        audit_mod,
        "_audit_semantic_checks",
        lambda engine, cfg: {
            "portfolio_target_positions": {"status": "ok"},
            "backtest_execution_reconciliation": {"status": "ok"},
            "intraday_trade_blotter_consistency": {"status": "not_applicable"},
            "analysis_backtest_consistency": {"status": "ok"},
        },
    )

    report = audit_mod.run_audit_from_config(cw1_config_path="cw1.yaml", cw2_config_path="cw2.yaml")

    assert report["storage"]["mongo"]["sentiment_pipeline"]["status"] == "degraded"
    assert report["readiness"]["storage_ready"] is False
    assert report["readiness"]["overall_status"] == "partial"


def test_backtest_reconciliation_includes_intraday_costs(monkeypatch):
    engine = _AuditFakeEngine()
    monkeypatch.setattr(
        audit_mod,
        "_latest_completed_run",
        lambda engine: {  # noqa: ARG005
            "run_id": "run-1",
            "run_name": "demo-run",
        },
    )

    report = audit_mod._audit_backtest_reconciliation(engine)

    assert report["status"] == "ok"
    assert report["violations"] == []
    assert report["observed"]["max_execution_cost_diff"] == 0.0
    assert report["observed"]["max_fixed_cost_diff"] == 0.0
    assert any(
        "backtest_intraday_events" in sql_text and "intraday_agg" in sql_text
        for sql_text in engine.conn.sql_texts
    )


def test_audit_sentiment_pipeline_bridge_flags_stale_pg_pipeline(monkeypatch):
    monkeypatch.setattr(
        audit_mod,
        "_load_recent_mongo_news_stats",
        lambda cw1_cfg, *, start_date, end_date: {
            "document_count": 12,
            "distinct_publish_dates": 5,
            "latest_publish_date": "2026-04-14",
        },
    )
    monkeypatch.setattr(
        audit_mod,
        "_load_recent_pg_sentiment_stats",
        lambda engine, *, start_date, end_date: {
            "news_article_count_daily": {
                "row_count": 9,
                "distinct_date_count": 3,
                "latest_observation_date": "2026-04-10",
            },
            "news_sentiment_daily": {
                "row_count": 9,
                "distinct_date_count": 3,
                "latest_observation_date": "2026-04-10",
            },
        },
    )

    report = audit_mod._audit_sentiment_pipeline_bridge(
        object(),
        cw1_cfg={},
        cw2_cfg={
            "backtest": {
                "start_date": "2026-01-01",
                "end_date": "2026-04-14",
                "lookback_years": 5,
            }
        },
    )

    assert report["status"] == "degraded"
    assert report["article_factor_lag_days"] == 4


class _DispatchMappings:
    def __init__(self, row):
        self._row = row

    def first(self):
        return None if self._row is None else dict(self._row)


class _DispatchResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _DispatchMappings(self._row)


class _DispatchConn:
    def __init__(self, row_builder):
        self._row_builder = row_builder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def execute(self, sql, params=None):
        return _DispatchResult(self._row_builder(str(sql), params or {}))


class _DispatchEngine:
    def __init__(self, row_builder):
        self._row_builder = row_builder

    def connect(self):
        return _DispatchConn(self._row_builder)


def test_build_operating_and_execution_models():
    operating = audit_mod._build_operating_model(
        {"market_factors": {"benchmark_ticker": "SPY"}, "kafka": {"enabled": True}},
        {
            "backtest": {
                "rebalance_frequency": "quarterly",
                "execution_lag": 2,
                "benchmark_ticker": "QQQ",
                "intraday_triggers": {"enabled": True},
            },
            "portfolio_construction": {"weighting": "risk_target"},
            "regime": {"mode": "volatility_threshold"},
            "kafka": {"enabled": "true"},
        },
    )
    execution = audit_mod._build_execution_assurance_model(
        {"recommendation": {"approval_required": False}},
        kafka_event_audit={
            "processing_scope": "dedicated_audit_consumer",
            "confirms_external_execution": True,
        },
    )

    assert operating["alpha_signal_frequency"] == "quarterly"
    assert operating["risk_overlay_frequency"] == "daily"
    assert operating["benchmark_ticker"] == "QQQ"
    assert operating["event_bus"] == "kafka"
    assert execution["recommendation_requires_approval"] is False
    assert execution["confirms_external_execution"] is True


def test_audit_portfolio_target_semantics_and_analysis_reconciliation(monkeypatch):
    engine = _DispatchEngine(
        lambda sql, params: (
            {
                "as_of_date": date(2026, 4, 30),
                "portfolio_name": "cw2_core_equity",
                "non_zero_positions": 25,
                "total_weight": 1.0,
                "observed_max_single_weight": 0.08,
            }
            if "non_zero_positions" in sql
            else (
                {"observed_max_sector_weight": 0.24}
                if "observed_max_sector_weight" in sql
                else {
                    "latest_performance_date": date(2026, 4, 30),
                    "latest_performance_benchmark_nav": 1.12,
                    "latest_analysis_benchmark_date": date(2026, 4, 30),
                    "latest_analysis_benchmark_nav": 1.12,
                    "relative_metric_count": 2,
                }
            )
        )
    )
    monkeypatch.setattr(
        audit_mod,
        "_latest_completed_run",
        lambda engine: {  # noqa: ARG005
            "run_id": "run-1",
            "run_name": "demo",
            "benchmark_ticker": "SPY",
        },
    )

    portfolio_report = audit_mod._audit_portfolio_target_semantics(
        engine,
        {
            "portfolio_construction": {
                "min_names": 20,
                "max_single_weight": 0.10,
                "max_sector_weight": 0.30,
            }
        },
    )
    analysis_report = audit_mod._audit_analysis_reconciliation(
        engine,
        {"backtest": {"analysis": {"primary_benchmark": "SPY"}}},
    )

    assert portfolio_report["status"] == "ok"
    assert portfolio_report["violations"] == []
    assert analysis_report["status"] == "ok"
    assert analysis_report["observed"]["relative_metric_count"] == 2


def test_audit_intraday_trade_blotter_not_applicable(monkeypatch):
    engine = _DispatchEngine(
        lambda sql, params: {  # noqa: ARG005
            "event_rows": 0,
            "blotter_rows": 0,
            "direction_conflicts": 0,
        }
    )
    monkeypatch.setattr(
        audit_mod,
        "_latest_completed_run",
        lambda engine: {"run_id": "run-1"},  # noqa: ARG005
    )

    report = audit_mod._audit_intraday_trade_blotter(engine)

    assert report == {
        "status": "not_applicable",
        "run_id": "run-1",
        "event_rows": 0,
        "blotter_rows": 0,
    }


def test_audit_storage_wrappers(monkeypatch):
    monkeypatch.setattr(
        "minio.Minio",
        lambda endpoint, access_key, secret_key, secure: type(  # noqa: ARG005
            "_MinioClient",
            (),
            {
                "bucket_exists": staticmethod(lambda bucket: True),
                "list_objects": staticmethod(
                    lambda bucket, prefix, recursive=True: [1, 2]  # noqa: ARG005
                ),
            },
        )(),
        raising=False,
    )
    minio_report = audit_mod._audit_minio(
        {
            "minio": {
                "endpoint": "minio:9000",
                "access_key": "user",
                "secret_key": "pass",
                "bucket": "raw-data",
                "secure": "false",
            }
        }
    )
    assert minio_report["status"] == "ok"
    assert minio_report["bucket_exists"] is True

    monkeypatch.setattr(
        "team_Pearson.coursework_one.modules.utils.mongo.resolve_mongo_db",
        lambda _name, cfg: "news_db",
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_one.modules.utils.mongo.build_mongo_client",
        lambda cfg: type(  # noqa: ARG005
            "_MongoClient",
            (),
            {
                "admin": type("_Admin", (), {"command": staticmethod(lambda cmd: {"ok": 1})})(),
                "__getitem__": lambda self, name: {
                    "news_articles": type(
                        "_Collection",
                        (),
                        {"count_documents": staticmethod(lambda query: 12)},
                    )()
                },
                "close": staticmethod(lambda: None),
            },
        )(),
        raising=False,
    )
    mongo_report = audit_mod._audit_mongo({"mongo": {"database": "news_db"}})
    assert mongo_report["status"] == "ok"
    assert mongo_report["document_count"] == 12

    monkeypatch.setattr(
        "team_Pearson.coursework_one.modules.utils.resilience._get_redis",
        lambda: type(
            "_Redis",
            (),
            {
                "ping": staticmethod(lambda: True),
                "dbsize": staticmethod(lambda: 5),
            },
        )(),
        raising=False,
    )
    redis_report = audit_mod._audit_redis()
    assert redis_report == {"status": "ok", "ping": True, "key_count": 5}

    monkeypatch.setattr(
        audit_mod,
        "audit_kafka_connectivity",
        lambda cfg, default_client_id: {
            "enabled": True,
            "status": "ok",
        },  # noqa: ARG005
    )
    monkeypatch.setattr(
        audit_mod,
        "summarize_kafka_event_audit",
        lambda engine, kafka_config, lookback_hours: {  # noqa: ARG005
            "status": "ok",
            "processing_scope": "dedicated_audit_consumer",
        },
    )
    assert audit_mod._audit_kafka({}, {})["status"] == "ok"
    assert audit_mod._audit_kafka_event_audit(object(), cw1_cfg={}, cw2_cfg={})["status"] == "ok"


def test_summarize_readiness_marks_ready_with_materialized_outputs():
    readiness = audit_mod._summarize_readiness(
        sql_report={
            "tables": {
                "curated_core": {
                    "factor_observations": {"exists": True, "row_count": 10},
                    "financial_observations": {"exists": True, "row_count": 10},
                    "benchmark_prices": {"exists": True, "row_count": 10},
                },
                "cw2_features": {
                    "feature_sub_scores": {"exists": True, "row_count": 5},
                    "feature_factor_scores": {"exists": True, "row_count": 5},
                    "feature_risk_overlay": {"exists": True, "row_count": 5},
                    "portfolio_target_positions": {"exists": True, "row_count": 5},
                },
                "analysis": {
                    "backtest_scorecard": {"exists": True, "row_count": 2},
                },
                "recommendations": {
                    "portfolio_recommendations": {"exists": True, "row_count": 1},
                },
            }
        },
        signal_history={"backtest_ready": True},
        minio_report={"status": "ok"},
        mongo_report={"status": "ok", "sentiment_pipeline": {"status": "ok"}},
        redis_report={"status": "ok"},
        kafka_report={"enabled": True, "status": "ok"},
        kafka_event_audit={"status": "ok"},
        semantic_checks={
            "portfolio_target_positions": {"status": "ok"},
            "backtest_execution_reconciliation": {"status": "ok"},
        },
    )

    assert readiness["overall_status"] == "ready"
    assert readiness["analysis_materialized"] is True
    assert readiness["recommendation_materialized"] is True
    assert readiness["recommended_next_step"].startswith("The hybrid batch-core")


def test_recommended_next_step_prioritizes_storage_and_semantic_failures():
    assert (
        audit_mod._recommended_next_step(
            core_sql_ready=True,
            feature_pipeline_ready=True,
            storage_ready=False,
            kafka_event_audit_ready=False,
            backtest_ready=True,
            semantic_ready=True,
            analysis_materialized=True,
            recommendation_materialized=True,
        )
        == "Run the CW2 Kafka event-audit consumer and clear any lag/dead-letter backlog before claiming end-to-end event readiness."
    )
    assert (
        audit_mod._recommended_next_step(
            core_sql_ready=True,
            feature_pipeline_ready=True,
            storage_ready=True,
            kafka_event_audit_ready=True,
            backtest_ready=True,
            semantic_ready=False,
            analysis_materialized=True,
            recommendation_materialized=True,
        )
        == "Resolve semantic consistency issues across portfolio targets, backtest ledgers, and analysis outputs before claiming full reproducibility."
    )


def test_audit_helper_normalizers_and_dates(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", " env-minio ")

    assert audit_mod._mongo_audit_ready(
        {"status": "ok", "sentiment_pipeline": {"status": "no_recent_articles"}}
    )
    assert audit_mod._safe_float("3.5") == 3.5
    assert audit_mod._safe_float("bad") is None
    assert (
        audit_mod._env_or_cfg("MINIO_ENDPOINT", {"endpoint": "cfg-minio"}, "endpoint")
        == "env-minio"
    )
    assert audit_mod._merged_kafka_cfg(
        {"kafka": {"topics": {"a": "topic-a"}, "audit_consumer": {"enabled": False}}},
        {
            "kafka": {
                "topics": {"b": "topic-b"},
                "audit_consumer": {"consumer_group": "g"},
            }
        },
    )["kafka"]["topics"] == {"a": "topic-a", "b": "topic-b"}
    assert (
        audit_mod._kafka_enabled(
            {"kafka": {"enabled": "true"}},
            {},
        )
        is True
    )
    assert audit_mod._resolve_start_date(
        None,
        end_date=date(2026, 4, 30),
        lookback_years=1,
    ) == date(2025, 4, 30)
    assert audit_mod._resolve_end_date("latest") <= date.today()
    assert audit_mod._parse_iso_date("2026-04-30") == date(2026, 4, 30)
    assert audit_mod._date_to_iso(date(2026, 4, 30)) == "2026-04-30"
    assert audit_mod._date_lag_days(date(2026, 4, 30), date(2026, 4, 28)) == 2
    assert audit_mod._subtract_years(date(2024, 2, 29), 1) == date(2023, 2, 28)
