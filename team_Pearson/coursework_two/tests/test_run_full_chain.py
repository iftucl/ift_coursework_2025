from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import yaml
from team_Pearson.coursework_two.scripts import run_full_chain as full_chain


def test_snapshot_window_uses_first_day_of_matching_month():
    start_date, end_date = full_chain._snapshot_window(date(2026, 4, 15), 5)
    assert start_date == date(2021, 4, 1)
    assert end_date == date(2026, 4, 15)


def test_build_parser_supports_full_chain_options():
    args = full_chain.build_parser().parse_args(
        [
            "--run-date",
            "2026-04-15",
            "--cw1-config",
            "cw1.yaml",
            "--cw2-config",
            "cw2.yaml",
            "--company-limit",
            "10",
            "--frequency",
            "daily",
            "--backfill-years",
            "3",
            "--enabled-extractors",
            "source_a,source_b",
            "--run-name",
            "cw2-demo",
            "--report-name",
            "cw2-report",
            "--report-output-dir",
            "reports",
            "--briefing-dir",
            "briefings",
            "--transaction-cost-bps",
            "25",
            "--auto-approve",
            "--smoke-profile",
            "--smoke-lookback-years",
            "2",
        ]
    )

    assert args.run_name == "cw2-demo"
    assert args.transaction_cost_bps == 25.0
    assert args.auto_approve is True
    assert args.quick_profile is True
    assert args.quick_lookback_years == 2


def test_resolve_snapshot_years_uses_maximum_requirement():
    years = full_chain._resolve_snapshot_years(
        cw1_cfg={"pipeline": {"backfill_years": 3}},
        cw2_cfg={"backtest": {"lookback_years": 5}},
        backfill_years=4,
    )
    assert years == 5


def test_effective_company_limit_defaults_to_full_universe():
    assert full_chain._effective_company_limit(None) == 0
    assert full_chain._effective_company_limit(0) == 0
    assert full_chain._effective_company_limit(70) == 70


def test_build_cw1_upstream_cmd_for_full_chain_defaults_to_explicit_full_scope():
    args = argparse.Namespace(
        cw1_config="cw1.yaml",
        run_date="2026-04-15",
        frequency="daily",
        enabled_extractors="source_a,source_b,market_factors",
    )

    cmd = full_chain._build_cw1_upstream_cmd(
        args=args,
        company_limit=0,
        backfill_years=5,
    )

    assert "--company-limit" in cmd and "0" in cmd
    assert "--backfill-years" in cmd and "5" in cmd
    assert "--enabled-extractors" in cmd and "source_a,source_b,market_factors" in cmd
    assert "--index-mongo" in cmd


def test_build_backfill_cmd_uses_explicit_skip_existing_flag():
    args = argparse.Namespace(cw1_config="cw1.yaml")

    cmd = full_chain._build_backfill_cmd(
        args=args,
        company_limit=5,
        start_date=date(2025, 4, 1),
        end_date=date(2026, 4, 15),
        cw2_config_path="cw2.yaml",
        skip_existing=False,
    )

    assert "--skip-existing" in cmd
    assert "false" in cmd


def test_build_operate_cmd_includes_optional_publish_flags():
    args = argparse.Namespace(
        run_date="2026-04-15",
        cw1_config="cw1.yaml",
        cw2_config="cw2.yaml",
        decision_actor="cw2_full_run",
        briefing_dir="briefings",
        auto_approve=True,
        auto_publish=True,
    )

    cmd = full_chain._build_operate_cmd(
        args=args,
        company_limit=0,
        cw2_config_path="cw2.yaml",
    )

    assert "--mode" in cmd and "operate" in cmd
    assert "--company-limit" in cmd and "0" in cmd
    assert "--briefing-dir" in cmd and "briefings" in cmd
    assert "--auto-approve" in cmd
    assert "--auto-publish" in cmd


def test_ensure_kafka_topics_passes_default_client_id(monkeypatch):
    captured = {}

    def fake_resolve_kafka_config(config, *, default_client_id):
        captured["config"] = config
        captured["default_client_id"] = default_client_id
        return SimpleNamespace(enabled=False, required=False, topics={})

    monkeypatch.setattr(full_chain, "resolve_kafka_config", fake_resolve_kafka_config)

    result = full_chain._ensure_kafka_topics({"kafka": {"enabled": False}})

    assert result == {"status": "skipped", "reason": "kafka disabled"}
    assert captured["config"] == {"kafka": {"enabled": False}}
    assert captured["default_client_id"] == "cw2_full_run"


def test_execute_kafka_event_audit_passes_resolved_config_paths(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        full_chain,
        "run_kafka_event_audit_from_config",
        lambda **kwargs: captured.update(kwargs) or {"status": "ok", "processed_count": 3},
    )

    result = full_chain._execute_kafka_event_audit(
        args=argparse.Namespace(cw1_config="cw1.yaml"),
        cw2_config_path="cw2.yaml",
    )

    assert result["status"] == "ok"
    assert result["processed_count"] == 3
    assert captured["cw1_config_path"].endswith("cw1.yaml")
    assert captured["cw2_config_path"].endswith("cw2.yaml")


def test_execute_readiness_audit_retries_transient_partial(monkeypatch):
    responses = iter(
        [
            {
                "readiness": {
                    "overall_status": "partial",
                    "core_sql_ready": True,
                    "feature_pipeline_ready": True,
                    "storage_ready": False,
                    "kafka_ready": True,
                    "kafka_event_audit_ready": False,
                    "backtest_ready": True,
                    "semantic_ready": True,
                }
            },
            {
                "readiness": {
                    "overall_status": "ready",
                    "core_sql_ready": True,
                    "feature_pipeline_ready": True,
                    "storage_ready": True,
                    "kafka_ready": True,
                    "kafka_event_audit_ready": True,
                    "backtest_ready": True,
                    "semantic_ready": True,
                }
            },
        ]
    )
    sleep_calls = []

    monkeypatch.setattr(
        full_chain,
        "run_audit_from_config",
        lambda **kwargs: next(responses),
    )
    monkeypatch.setattr(full_chain.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = full_chain._execute_readiness_audit(
        args=argparse.Namespace(cw1_config="cw1.yaml"),
        cw2_config_path="cw2.yaml",
        max_attempts=3,
        retry_delay_seconds=2.5,
    )

    assert result["status"] == "ok"
    assert result["attempts"] == 2
    assert result["readiness"]["overall_status"] == "ready"
    assert sleep_calls == [2.5]


def test_execute_readiness_audit_does_not_retry_non_transient_partial(monkeypatch):
    sleep_calls = []

    monkeypatch.setattr(
        full_chain,
        "run_audit_from_config",
        lambda **kwargs: {
            "readiness": {
                "overall_status": "partial",
                "core_sql_ready": True,
                "feature_pipeline_ready": True,
                "storage_ready": True,
                "kafka_ready": True,
                "kafka_event_audit_ready": True,
                "backtest_ready": False,
                "semantic_ready": True,
            }
        },
    )
    monkeypatch.setattr(full_chain.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = full_chain._execute_readiness_audit(
        args=argparse.Namespace(cw1_config="cw1.yaml"),
        cw2_config_path="cw2.yaml",
        max_attempts=3,
        retry_delay_seconds=2.5,
    )

    assert result["status"] == "failed"
    assert result["attempts"] == 1
    assert result["readiness"]["backtest_ready"] is False
    assert sleep_calls == []


def test_build_quick_cw2_config_writes_relaxed_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(full_chain, "CW2_ROOT", tmp_path)
    monkeypatch.setattr(
        full_chain,
        "datetime",
        type(
            "_FixedDateTime",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: __import__("datetime").datetime(
                        2026, 4, 16, 12, 0, 0, tzinfo=tz
                    )
                )
            },
        ),
    )

    path, summary = full_chain._build_quick_cw2_config(
        cw2_cfg={
            "factors": {
                "quality": {
                    "sub_variables": [
                        "ebitda_margin",
                        "roe",
                        "debt_to_equity_inv",
                    ]
                },
                "value": {
                    "sub_variables": [
                        "book_to_price",
                        "earnings_to_price",
                        "ebitda_to_ev",
                    ]
                },
                "market_technical": {
                    "sub_variables": [
                        "momentum_1m",
                        "momentum_6m",
                        "momentum_12_1m",
                    ]
                },
                "dividend": {"sub_variables": ["dividend_yield"]},
            },
            "preprocessing": {"min_observations": 30, "neutralize_by": "gics_sector"},
            "investable_universe": {
                "market_cap_bottom_percentile": 0.2,
                "liquidity_bottom_percentile": 0.2,
            },
            "risk_overlay": {
                "max_volatility_60d_percentile": 0.9,
                "required_factor_groups": [
                    "quality",
                    "value",
                    "market_technical",
                ],
                "optional_percentile_blacklists": [{"column": "garch_vol_60d", "percentile": 0.9}],
            },
            "pipeline_guards": {
                "min_scoring_universe": 30,
                "min_investable_universe": 25,
            },
            "quality_gates": {
                "min_sub_score_rows": 150,
                "min_factor_score_rows": 30,
                "min_risk_overlay_rows": 30,
                "min_portfolio_targets": 25,
            },
            "portfolio_construction": {
                "portfolio_name": "cw2_core_equity",
                "selection_mode": "hybrid",
                "top_n": 50,
                "hybrid_min_n": 30,
                "hybrid_max_n": 50,
                "min_names": 25,
                "min_candidate_pool": 25,
                "max_single_weight": 0.05,
            },
            "backtest": {"lookback_years": 5, "min_eligible_universe": 25},
            "recommendation": {"portfolio_name": "cw2_core_equity"},
        },
        company_limit=5,
        lookback_years=1,
        run_date=date(2026, 4, 15),
    )

    assert path.exists()
    assert summary["lookback_years"] == 1
    assert summary["floor_names"] == 3
    assert summary["cap_names"] == 5
    assert summary["max_single_weight"] >= 0.35
    assert summary["portfolio_name"] == "cw2_core_equity_quick_20260415_c5_y1"
    assert summary["min_observations"] == 3
    assert summary["required_sub_variables"] == 9
    assert summary["min_sub_score_rows"] == 27
    assert summary["min_factor_score_rows"] == 3
    assert summary["min_risk_overlay_rows"] == 3

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert payload["preprocessing"]["min_observations"] == 3
    assert payload["investable_universe"]["market_cap_bottom_percentile"] is None
    assert payload["investable_universe"]["liquidity_bottom_percentile"] is None
    assert payload["risk_overlay"]["max_volatility_60d_percentile"] == 1.0
    assert payload["risk_overlay"]["optional_percentile_blacklists"] == []
    assert payload["pipeline_guards"]["min_scoring_universe"] == 3
    assert payload["pipeline_guards"]["min_investable_universe"] == 3
    assert payload["quality_gates"]["min_sub_score_rows"] == 27
    assert payload["quality_gates"]["min_factor_score_rows"] == 3
    assert payload["quality_gates"]["min_risk_overlay_rows"] == 3
    assert payload["quality_gates"]["min_portfolio_targets"] == 3
    assert (
        payload["portfolio_construction"]["portfolio_name"]
        == "cw2_core_equity_quick_20260415_c5_y1"
    )
    assert payload["portfolio_construction"]["min_names"] == 3
    assert payload["portfolio_construction"]["min_candidate_pool"] == 3
    assert payload["portfolio_construction"]["hybrid_min_n"] == 3
    assert payload["portfolio_construction"]["hybrid_max_n"] == 5
    assert payload["backtest"]["portfolio_name"] == "cw2_core_equity_quick_20260415_c5_y1"
    assert payload["backtest"]["lookback_years"] == 1
    assert payload["backtest"]["min_eligible_universe"] == 3
    assert payload["recommendation"]["portfolio_name"] == "cw2_core_equity_quick_20260415_c5_y1"
    assert len(payload["portfolio_construction"]["portfolio_name"]) <= 50


def test_build_quick_cw2_config_preserves_production_filters_for_full_universe(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(full_chain, "CW2_ROOT", tmp_path)
    monkeypatch.setattr(
        full_chain,
        "datetime",
        type(
            "_FixedDateTime",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: __import__("datetime").datetime(
                        2026, 4, 16, 12, 0, 0, tzinfo=tz
                    )
                )
            },
        ),
    )

    path, summary = full_chain._build_quick_cw2_config(
        cw2_cfg={
            "factors": {"quality": {"sub_variables": ["ebitda_margin", "roe"]}},
            "preprocessing": {"min_observations": 30, "neutralize_by": "gics_sector"},
            "investable_universe": {
                "market_cap_bottom_percentile": 0.2,
                "liquidity_bottom_percentile": 0.2,
            },
            "risk_overlay": {
                "max_volatility_60d_percentile": 0.9,
                "optional_percentile_blacklists": [{"column": "garch_vol_60d", "percentile": 0.9}],
            },
            "pipeline_guards": {
                "min_scoring_universe": 30,
                "min_investable_universe": 25,
            },
            "quality_gates": {
                "min_sub_score_rows": 150,
                "min_factor_score_rows": 30,
                "min_risk_overlay_rows": 30,
                "min_portfolio_targets": 25,
            },
            "portfolio_construction": {
                "portfolio_name": "cw2_core_equity",
                "selection_mode": "hybrid",
                "top_n": 50,
                "hybrid_min_n": 30,
                "hybrid_max_n": 50,
                "min_names": 25,
                "min_candidate_pool": 25,
                "max_single_weight": 0.05,
            },
            "backtest": {
                "portfolio_name": "cw2_core_equity",
                "lookback_years": 5,
                "min_eligible_universe": 25,
            },
            "recommendation": {"portfolio_name": "cw2_core_equity"},
        },
        company_limit=0,
        lookback_years=1,
        run_date=date(2026, 4, 15),
    )

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert summary["portfolio_name"] == "cw2_core_equity_quick_20260415_all_y1"
    assert payload["preprocessing"]["min_observations"] == 30
    assert payload["investable_universe"]["market_cap_bottom_percentile"] == 0.2
    assert payload["investable_universe"]["liquidity_bottom_percentile"] == 0.2
    assert payload["risk_overlay"]["max_volatility_60d_percentile"] == 0.9
    assert payload["risk_overlay"]["optional_percentile_blacklists"] == [
        {"column": "garch_vol_60d", "percentile": 0.9}
    ]
    assert len(payload["portfolio_construction"]["portfolio_name"]) <= 50


def test_run_subprocess_step_reports_success(monkeypatch):
    monkeypatch.setattr(
        full_chain.subprocess,
        "run",
        lambda cmd, cwd, env, check: type(
            "Completed", (), {"returncode": 0}
        )(),  # noqa: ARG005,E501
    )

    result = full_chain._run_subprocess_step(
        step_name="cw1_upstream",
        cmd=["python", "Main.py"],
        cwd=Path("/tmp"),
        env={"X": "1"},
    )

    assert result["status"] == "ok"
    assert result["step"] == "cw1_upstream"
    assert result["returncode"] == 0


def test_run_subprocess_step_raises_on_failure(monkeypatch):
    monkeypatch.setattr(
        full_chain.subprocess,
        "run",
        lambda cmd, cwd, env, check: type(
            "Completed", (), {"returncode": 2}
        )(),  # noqa: ARG005,E501
    )

    try:
        full_chain._run_subprocess_step(
            step_name="cw2_operate",
            cmd=["python", "Main.py"],
            cwd=Path("/tmp"),
            env={},
        )
    except RuntimeError as exc:
        assert "cw2_operate failed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


def test_init_db_cmd_and_apply_sql_text():
    cmd = full_chain._init_db_cmd(argparse.Namespace())
    assert Path(cmd[1]).as_posix().endswith("team_Pearson/coursework_one/scripts/init_db.py")

    executed = {}

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

        def execute(self, sql_text):
            executed["sql_text"] = sql_text

    class _RawConn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            executed["committed"] = True

        def close(self):
            executed["closed"] = True

    class _Engine:
        def raw_connection(self):
            return _RawConn()

    full_chain._apply_sql_text(_Engine(), "SELECT 1;")

    assert executed == {
        "sql_text": "SELECT 1;",
        "committed": True,
        "closed": True,
    }


def test_initialize_cw2_schema_applies_all_sql_files(tmp_path, monkeypatch):
    sql_root = tmp_path / "sql"
    sql_root.mkdir()
    for filename in full_chain._CW2_SCHEMA_ORDER:
        (sql_root / filename).write_text(f"-- {filename}\n", encoding="utf-8")
    monkeypatch.setattr(full_chain, "CW2_ROOT", tmp_path)
    monkeypatch.setattr(full_chain, "get_db_engine", lambda: object())
    applied = []
    monkeypatch.setattr(
        full_chain,
        "_apply_sql_text",
        lambda engine, sql_text: applied.append(sql_text),
    )

    result = full_chain._initialize_cw2_schema()

    assert result["status"] == "ok"
    assert result["applied_files"] == list(full_chain._CW2_SCHEMA_ORDER)
    assert applied[0] == "-- cw2_feature_schema.sql\n"


def test_ensure_mongo_indexes_opens_collection_and_closes_client(monkeypatch):
    closed = {"value": False}
    monkeypatch.setattr(full_chain, "resolve_mongo_db", lambda _name, cfg: "news_db")
    monkeypatch.setattr(
        full_chain,
        "build_mongo_collection",
        lambda mongo_cfg, collection_name, mongo_db: (  # noqa: ARG005
            type(
                "_Client",
                (),
                {"close": staticmethod(lambda: closed.__setitem__("value", True))},
            )(),
            object(),
        ),
    )
    monkeypatch.setattr(full_chain, "_ensure_news_indexes", lambda coll: None)

    result = full_chain._ensure_mongo_indexes({"mongo": {"database": "news_db"}})

    assert result == {
        "status": "ok",
        "database": "news_db",
        "collection": "news_articles",
    }
    assert closed["value"] is True


def test_ensure_news_indexes_creates_expected_indexes():
    calls = []

    class _Collection:
        def create_index(self, spec, **kwargs):
            calls.append((spec, kwargs))

    full_chain._ensure_news_indexes(_Collection())

    assert len(calls) == 8
    assert calls[0][1]["name"] == "idx_text_title_summary"
    assert calls[-1][1]["name"] == "idx_last_seen_run_date_time_published_desc"
    assert calls[5][1]["unique"] is True


def test_ensure_minio_bucket_creates_missing_bucket(monkeypatch):
    captured = {}

    class _FakeMinio:
        def __init__(self, endpoint, access_key, secret_key, secure):
            captured["init"] = {
                "endpoint": endpoint,
                "access_key": access_key,
                "secret_key": secret_key,
                "secure": secure,
            }

        def bucket_exists(self, bucket):
            captured["bucket_exists"] = bucket
            return False

        def make_bucket(self, bucket):
            captured["made_bucket"] = bucket

    monkeypatch.setattr(full_chain, "Minio", _FakeMinio)

    result = full_chain._ensure_minio_bucket(
        {
            "minio": {
                "endpoint": "http://minio:9000",
                "access_key": "user",
                "secret_key": "pass",
                "bucket": "raw-data",
                "secure": "false",
            }
        }
    )

    assert result == {
        "status": "ok",
        "bucket": "raw-data",
        "bucket_preexisted": False,
    }
    assert captured["init"]["endpoint"] == "minio:9000"
    assert captured["made_bucket"] == "raw-data"


def test_ensure_kafka_topics_warns_when_non_required_creation_fails(monkeypatch):
    monkeypatch.setattr(
        full_chain,
        "resolve_kafka_config",
        lambda config, *, default_client_id: SimpleNamespace(  # noqa: ARG005
            enabled=True,
            required=False,
            topics={"a": "topic-a", "b": "topic-b"},
        ),
    )
    responses = iter(
        [
            type("Completed", (), {"returncode": 0, "stdout": "created", "stderr": ""})(),
            type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "boom"})(),
        ]
    )
    monkeypatch.setattr(
        full_chain.subprocess,
        "run",
        lambda cmd, check, capture_output, text: next(responses),  # noqa: ARG005
    )

    summary = full_chain._ensure_kafka_topics({"kafka": {"enabled": True}})

    assert summary["status"] == "warning"
    assert summary["failures"] == 1
    assert len(summary["topics"]) == 2


def test_execute_backtest_analysis_report_forwards_transaction_cost(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        full_chain,
        "run_backtest_from_config",
        lambda **kwargs: captured.update({"backtest": kwargs}) or "run-1",
    )
    monkeypatch.setattr(
        full_chain,
        "run_analysis_from_config",
        lambda **kwargs: captured.update({"analysis": kwargs}) or {"status": "ok"},
    )
    monkeypatch.setattr(
        full_chain,
        "generate_backtest_report_from_config",
        lambda **kwargs: captured.update({"report": kwargs}) or {"artifact_count": 4},
    )

    result = full_chain._execute_backtest_analysis_report(
        args=argparse.Namespace(
            transaction_cost_bps=25.0,
            robustness_run_id="robust-1",
            report_name="cw2_report",
            report_output_dir="reports",
        ),
        run_name="full-chain-demo",
        cw2_config_path="cw2.yaml",
    )

    assert result["run_id"] == "run-1"
    assert captured["backtest"]["config_override"]["backtest"]["transaction_cost_bps"] == 25.0
    assert captured["analysis"]["robustness_run_id_25bps"] == "robust-1"
    assert captured["report"]["report_name"] == "cw2_report"


def test_main_executes_full_chain_and_emits_summary(monkeypatch, tmp_path):
    captured = {}
    quick_path = tmp_path / "quick.yaml"
    quick_path.write_text("backtest: {}\n", encoding="utf-8")
    args = argparse.Namespace(
        run_date="2026-04-15",
        cw1_config="cw1.yaml",
        cw2_config="cw2.yaml",
        company_limit=5,
        frequency="daily",
        backfill_years=None,
        enabled_extractors="source_a,source_b",
        run_name=None,
        report_name="cw2_report",
        report_output_dir="reports",
        briefing_dir="briefings",
        transaction_cost_bps=20.0,
        robustness_run_id="robust-1",
        decision_actor="cw2_full_run",
        auto_approve=True,
        auto_publish=False,
        quick_profile=True,
        quick_lookback_years=1,
    )
    load_calls = []

    monkeypatch.setattr(full_chain, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        full_chain,
        "build_parser",
        lambda: type("_Parser", (), {"parse_args": staticmethod(lambda: args)})(),
    )
    monkeypatch.setattr(full_chain, "load_env_layers", lambda: None)
    monkeypatch.setattr(
        full_chain,
        "load_yaml",
        lambda path: load_calls.append(path)
        or (
            {"pipeline": {"backfill_years": 4}}
            if path == "cw1.yaml"
            else {"backtest": {"lookback_years": 5}}
        ),
    )
    monkeypatch.setattr(full_chain, "_effective_company_limit", lambda raw: 5)
    monkeypatch.setattr(full_chain, "_resolve_effective_backfill_years", lambda a, cfg: 4)
    monkeypatch.setattr(
        full_chain,
        "_build_quick_cw2_config",
        lambda **kwargs: (
            quick_path,
            {"config_path": str(quick_path), "lookback_years": 1, "floor_names": 3},
        ),
    )
    monkeypatch.setattr(
        full_chain,
        "_snapshot_window",
        lambda run_date, years: (date(2025, 4, 1), date(2026, 4, 15)),
    )
    monkeypatch.setattr(full_chain, "_default_run_name", lambda run_date: "auto-run")
    step_calls = []
    monkeypatch.setattr(
        full_chain,
        "_run_subprocess_step",
        lambda **kwargs: step_calls.append(kwargs["step_name"])
        or {"step": kwargs["step_name"], "status": "ok", "returncode": 0},
    )
    monkeypatch.setattr(
        full_chain,
        "_initialize_cw2_schema",
        lambda: {"status": "ok", "applied_files": ["cw2_feature_schema.sql"]},
    )
    monkeypatch.setattr(
        full_chain,
        "_ensure_minio_bucket",
        lambda cfg: {"status": "ok", "bucket": "raw-data", "bucket_preexisted": True},
    )
    monkeypatch.setattr(
        full_chain,
        "_ensure_mongo_indexes",
        lambda cfg: {"status": "ok", "database": "news", "collection": "news_articles"},
    )
    monkeypatch.setattr(
        full_chain,
        "_ensure_kafka_topics",
        lambda cfg: {"status": "ok", "failures": 0, "topics": []},
    )
    monkeypatch.setattr(
        full_chain,
        "run_audit_from_config",
        lambda **kwargs: {"readiness": {"overall_status": "ready"}},
    )
    monkeypatch.setattr(
        full_chain,
        "_execute_backtest_analysis_report",
        lambda **kwargs: {
            "status": "ok",
            "run_id": "run-1",
            "run_name": "auto-run",
            "report": {"artifact_count": 4},
            "analysis": {"status": "ok"},
        },
    )
    monkeypatch.setattr(
        full_chain,
        "_execute_kafka_event_audit",
        lambda **kwargs: {"status": "ok", "processed_count": 2},
    )
    monkeypatch.setattr(full_chain, "print_json", lambda payload: captured.update(payload))

    rc = full_chain.main()

    assert rc == 0
    assert captured["run_id"] == "run-1"
    assert captured["kafka_event_audit"]["processed_count"] == 2
    assert captured["smoke_profile"]["lookback_years"] == 1
    assert captured["quick_profile"]["lookback_years"] == 1
    assert step_calls == [
        "init_db",
        "cw1_upstream",
        "cw2_monthly_backfill",
        "cw2_operate",
    ]
