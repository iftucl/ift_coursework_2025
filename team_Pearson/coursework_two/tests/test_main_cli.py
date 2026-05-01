"""Unit tests for the CW2 Main.py CLI entrypoint."""

from __future__ import annotations

import argparse
import importlib.util
import uuid
from pathlib import Path

_MAIN_PATH = Path(__file__).resolve().parents[1] / "Main.py"
_SPEC = importlib.util.spec_from_file_location("cw2_main_module", _MAIN_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_parser_supports_backtest_and_analysis_modes():
    parser = _MODULE._build_parser()
    args = parser.parse_args(["--mode", "backtest-and-analyse", "--run-name", "bt_demo"])
    assert args.mode == "backtest-and-analyse"
    assert args.run_name == "bt_demo"

    full_run_args = parser.parse_args(
        [
            "--mode",
            "full-run",
            "--run-date",
            "2026-04-15",
            "--smoke-profile",
            "--smoke-lookback-years",
            "1",
        ]
    )
    assert full_run_args.mode == "full-run"
    assert full_run_args.run_date == "2026-04-15"
    assert full_run_args.quick_profile is True
    assert full_run_args.quick_lookback_years == 1

    operate_args = parser.parse_args(["--mode", "operate", "--run-date", "2026-04-14"])
    assert operate_args.mode == "operate"

    analyse_args = parser.parse_args(["--mode", "analyse", "--run-id", "run-123"])
    assert analyse_args.mode == "analyse"
    assert analyse_args.run_id == "run-123"

    audit_args = parser.parse_args(["--mode", "audit"])
    assert audit_args.mode == "audit"

    monitor_args = parser.parse_args(["--mode", "monitor"])
    assert monitor_args.mode == "monitor"

    update_args = parser.parse_args(["--mode", "update-decision", "--run-date", "2026-04-15"])
    assert update_args.mode == "update-decision"
    assert update_args.run_date == "2026-04-15"

    report_args = parser.parse_args(
        ["--mode", "report", "--run-id", "run-123", "--report-name", "ops_report"]
    )
    assert report_args.mode == "report"
    assert report_args.run_id == "run-123"
    assert report_args.report_name == "ops_report"

    recommend_args = parser.parse_args(["--mode", "recommend", "--recommendation-name", "rec_demo"])
    assert recommend_args.mode == "recommend"
    assert recommend_args.recommendation_name == "rec_demo"

    decision_args = parser.parse_args(
        [
            "--mode",
            "decide-recommendation",
            "--recommendation-id",
            "rec-123",
            "--decision-type",
            "approve",
            "--actor",
            "pm",
        ]
    )
    assert decision_args.mode == "decide-recommendation"
    assert decision_args.recommendation_id == "rec-123"
    assert decision_args.decision_type == "approve"
    assert decision_args.actor == "pm"


def test_parser_supports_backtest_mode_and_run_name():
    parser = _MODULE._build_parser()
    args = parser.parse_args(
        ["--mode", "backtest", "--run-name", "bt_demo", "--transaction-cost-bps", "25"]
    )
    assert args.mode == "backtest"
    assert args.run_name == "bt_demo"
    assert args.transaction_cost_bps == 25.0


def test_default_backtest_run_name_prefix():
    name = _MODULE._default_backtest_run_name()
    assert name.startswith("cw2_backtest_")


def test_load_yaml_env_and_config_helpers(monkeypatch, tmp_path):
    cfg_path = tmp_path / "custom.yaml"
    cfg_path.write_text(
        "pipeline:\n  company_limit: 12\nuniverse:\n  country_allowlist: [US]\n",
        encoding="utf-8",
    )
    assert _MODULE._load_yaml(str(cfg_path))["pipeline"]["company_limit"] == 12

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.utils.config_validation.load_cw2_config",
        lambda path: {"loaded_from": path},
        raising=False,
    )
    default_loaded = _MODULE._load_yaml(_MODULE._default_cw2_config())
    assert default_loaded["loaded_from"].endswith("conf.yaml")

    env_calls = []
    monkeypatch.setattr(
        "modules.utils.env.load_dotenv_if_exists",
        lambda path, override=False: env_calls.append((Path(path).name, override)),
        raising=False,
    )
    _MODULE._load_env_layers()
    assert env_calls == [(".env", False), (".env", True)]
    assert (
        _MODULE._resolve_company_limit(
            argparse.Namespace(company_limit=None), {"pipeline": {"company_limit": 8}}
        )
        == 8
    )
    assert _MODULE._resolve_country_allowlist({"universe": {"country_allowlist": ["US"]}}) == ["US"]


def test_repo_root_is_added_to_sys_path_for_script_execution():
    assert str(_MODULE.REPO_ROOT) in _MODULE.sys.path


def test_main_dispatches_backtest_mode(monkeypatch):
    calls = {"load_env": 0, "backtest": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_load_env_layers",
        lambda: calls.__setitem__("load_env", calls["load_env"] + 1),
    )
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="backtest",
                with_upstream=False,
                run_name="bt_test",
                run_id=None,
                robustness_run_id=None,
                transaction_cost_bps=25.0,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_backtest_only",
        lambda args: calls.__setitem__("backtest", calls["backtest"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["load_env"] == 1
    assert calls["backtest"] == 1


def test_main_dispatches_analysis_mode(monkeypatch):
    calls = {"analysis": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="analyse",
                with_upstream=False,
                run_name=None,
                run_id="run-123",
                robustness_run_id=None,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_analysis_only",
        lambda args: calls.__setitem__("analysis", calls["analysis"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["analysis"] == 1


def test_main_dispatches_full_run_mode(monkeypatch):
    calls = {"full_run": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="full-run",
                with_upstream=False,
                run_name=None,
                run_id=None,
                report_name=None,
                report_output_dir=None,
                briefing_dir=None,
                recommendation_name=None,
                recommendation_id=None,
                decision_type=None,
                actor=None,
                notes=None,
                auto_approve=False,
                auto_publish=False,
                decision_actor="cw2_full_run",
                robustness_run_id=None,
                transaction_cost_bps=None,
                run_date="2026-04-15",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency="daily",
                backfill_years=5,
                enabled_extractors="source_a,source_b,market_factors",
                dry_run=False,
                index_mongo=True,
                quick_profile=False,
                quick_lookback_years=1,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_full_chain",
        lambda args: calls.__setitem__("full_run", calls["full_run"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["full_run"] == 1


def test_run_full_chain_forwards_quick_flags(monkeypatch):
    captured = {}

    monkeypatch.setattr(_MODULE, "logger", type("L", (), {"info": lambda *args, **kwargs: None})())

    def fake_run(cmd, cwd, check):  # noqa: ARG001
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(_MODULE.subprocess, "run", fake_run)

    rc = _MODULE._run_full_chain(
        argparse.Namespace(
            run_date="2026-04-15",
            cw1_config="cw1.yaml",
            cw2_config="cw2.yaml",
            decision_actor="cw2_full_run",
            company_limit=10,
            frequency="daily",
            backfill_years=1,
            enabled_extractors="source_a,source_b,market_factors",
            run_name="quick_run",
            report_name="quick_report",
            report_output_dir=None,
            briefing_dir=None,
            transaction_cost_bps=None,
            robustness_run_id=None,
            auto_approve=False,
            auto_publish=False,
            quick_profile=True,
            quick_lookback_years=1,
        )
    )

    assert rc == 0
    cmd = captured["cmd"]
    assert "--smoke-profile" in cmd
    assert "--smoke-lookback-years" in cmd and "1" in cmd


def test_main_dispatches_audit_mode(monkeypatch):
    calls = {"audit": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="audit",
                with_upstream=False,
                run_name=None,
                run_id=None,
                robustness_run_id=None,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_audit_only",
        lambda args: calls.__setitem__("audit", calls["audit"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["audit"] == 1


def test_main_dispatches_monitor_mode(monkeypatch):
    calls = {"monitor": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="monitor",
                with_upstream=False,
                run_name=None,
                run_id=None,
                robustness_run_id=None,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_monitor_only",
        lambda args: calls.__setitem__("monitor", calls["monitor"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["monitor"] == 1


def test_main_dispatches_update_decision_mode(monkeypatch):
    calls = {"update_decision": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="update-decision",
                with_upstream=False,
                run_name=None,
                run_id=None,
                robustness_run_id=None,
                run_date="2026-04-15",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_update_decision_only",
        lambda args: calls.__setitem__("update_decision", calls["update_decision"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["update_decision"] == 1


def test_main_dispatches_recommend_mode(monkeypatch):
    calls = {"recommend": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="recommend",
                with_upstream=False,
                run_name=None,
                recommendation_name="rec_demo",
                run_id=None,
                robustness_run_id=None,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_recommend_only",
        lambda args: calls.__setitem__("recommend", calls["recommend"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["recommend"] == 1


def test_main_dispatches_report_mode(monkeypatch):
    calls = {"report": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="report",
                with_upstream=False,
                run_name=None,
                report_name="ops_report",
                report_output_dir="reports",
                recommendation_name=None,
                recommendation_id=None,
                decision_type=None,
                actor=None,
                notes=None,
                run_id="run-123",
                robustness_run_id=None,
                transaction_cost_bps=None,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_report_only",
        lambda args: calls.__setitem__("report", calls["report"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["report"] == 1


def test_main_dispatches_operate_mode(monkeypatch):
    calls = {"operate": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="operate",
                with_upstream=False,
                run_name=None,
                recommendation_name="rec_demo",
                recommendation_id=None,
                decision_type=None,
                actor=None,
                notes=None,
                run_id=None,
                robustness_run_id=None,
                transaction_cost_bps=None,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_operate_only",
        lambda args: calls.__setitem__("operate", calls["operate"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["operate"] == 1


def test_run_operate_only_auto_publish_ready_flow(monkeypatch, tmp_path, capsys):
    calls = {
        "features": 0,
        "recommend": 0,
        "audit": 0,
        "decision": 0,
        "package": 0,
        "briefing": 0,
    }

    monkeypatch.setattr(
        _MODULE,
        "_run_cw2_only",
        lambda args: calls.__setitem__("features", calls["features"] + 1) or 0,
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_recommendation",
        lambda args: calls.__setitem__("recommend", calls["recommend"] + 1)
        or {
            "recommendation_id": "rec-1",
            "recommendation_name": "rec_name",
            "status": "proposed",
        },
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_audit",
        lambda args: calls.__setitem__("audit", calls["audit"] + 1)
        or {"readiness": {"overall_status": "ready"}},
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_recommendation_decision",
        lambda **kwargs: calls.__setitem__("decision", calls["decision"] + 1)
        or {
            "recommendation_id": kwargs["recommendation_id"],
            "decision_type": kwargs["decision_type"],
            "status": ("published" if kwargs["decision_type"] == "publish" else "approved"),
        },
    )
    monkeypatch.setattr(
        _MODULE,
        "_load_recommendation_package",
        lambda **kwargs: calls.__setitem__("package", calls["package"] + 1)
        or {
            "header": {
                "recommendation_name": "rec_name",
                "recommendation_status": "published",
                "summary_json": {"top_positions": [], "sector_weights": {}},
            },
            "items": [],
        },
    )
    monkeypatch.setattr(
        _MODULE,
        "_write_operate_briefing",
        lambda **kwargs: calls.__setitem__("briefing", calls["briefing"] + 1)
        or str(tmp_path / "brief.md"),
    )

    args = argparse.Namespace(
        run_date="2026-04-14",
        recommendation_name="rec_name",
        cw2_config="cw2.yaml",
        cw1_config="cw1.yaml",
        auto_approve=False,
        auto_publish=True,
        decision_actor="ops_bot",
        briefing_dir=str(tmp_path),
    )

    rc = _MODULE._run_operate_only(args)
    captured = capsys.readouterr()

    assert rc == 0
    assert calls == {
        "features": 1,
        "recommend": 1,
        "audit": 1,
        "decision": 2,
        "package": 1,
        "briefing": 1,
    }
    assert '"status": "published"' in captured.out


def test_main_dispatches_recommendation_decision_mode(monkeypatch):
    calls = {"decision": 0}

    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="decide-recommendation",
                with_upstream=False,
                run_name=None,
                recommendation_name="rec_demo",
                recommendation_id=None,
                decision_type="approve",
                actor="pm",
                notes="looks good",
                run_id=None,
                robustness_run_id=None,
                run_date="2026-04-14",
                cw2_config="cw2.yaml",
                cw1_config="cw1.yaml",
                company_limit=None,
                frequency=None,
                backfill_years=None,
                enabled_extractors=None,
                dry_run=False,
                index_mongo=True,
            )
        ),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_recommendation_decision_only",
        lambda args: calls.__setitem__("decision", calls["decision"] + 1) or 0,
    )

    rc = _MODULE.main()
    assert rc == 0
    assert calls["decision"] == 1


def test_run_with_upstream_builds_shared_cw1_command(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        _MODULE,
        "_load_yaml",
        lambda path: {"path": path},
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.utils.config_contract.validate_shared_runtime_contract",
        lambda cw1_cfg, cw2_cfg: {"status": "ok"},  # noqa: ARG005
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.utils.config_contract.evaluate_upstream_history_contract",
        lambda cw1_cfg, cw2_cfg, effective_backfill_years: {
            "warning": "history gap"
        },  # noqa: ARG005,E501
        raising=False,
    )
    monkeypatch.setattr(
        _MODULE.subprocess,
        "run",
        lambda cmd, cwd, env, check: captured.update(  # noqa: ARG005
            {"cmd": cmd, "cwd": cwd, "env": env}
        )
        or type("Completed", (), {"returncode": 0})(),
    )

    rc = _MODULE._run_with_upstream(
        argparse.Namespace(
            cw1_config="cw1.yaml",
            cw2_config="cw2.yaml",
            run_date="2026-04-15",
            company_limit=10,
            frequency="daily",
            backfill_years=5,
            enabled_extractors="source_a,source_b",
            dry_run=True,
            index_mongo=False,
        )
    )

    assert rc == 0
    assert captured["cwd"] == str(_MODULE.CW1_ROOT)
    assert "--dry-run" in captured["cmd"]
    assert "--no-index-mongo" in captured["cmd"]
    assert captured["env"]["CW2_CONFIG_PATH"].endswith("cw2.yaml")


def test_run_cw2_only_returns_error_when_no_rows_produced(monkeypatch):
    monkeypatch.setattr(_MODULE, "_load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(
        "modules.db.universe.get_company_universe",
        lambda company_limit, country_allowlist, as_of_date: [
            "AAPL",
            "MSFT",
        ],  # noqa: ARG005,E501
        raising=False,
    )
    monkeypatch.setattr(
        "modules.transform.cw2_features.build_and_load_cw2_features",
        lambda **kwargs: {  # noqa: ARG005
            "universe_screen": 0,
            "sub_scores": 0,
            "factor_scores": 0,
            "risk_overlay": 0,
            "portfolio_targets": 0,
        },
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.utils.config_contract.validate_shared_runtime_contract",
        lambda cw1_cfg, cw2_cfg: {"status": "ok"},  # noqa: ARG005
        raising=False,
    )

    rc = _MODULE._run_cw2_only(
        argparse.Namespace(
            run_date="2026-04-15",
            cw1_config="cw1.yaml",
            cw2_config="cw2.yaml",
            company_limit=5,
        )
    )

    assert rc == 1


def test_execute_backtest_and_report_helpers(monkeypatch, capsys):
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.backtest.run_backtest_from_config",
        lambda **kwargs: "run-1",
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.generate_backtest_report_from_config",
        lambda **kwargs: {"report_id": "report-1"},
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.analysis.run_analysis_from_config",
        lambda **kwargs: {"status": "ok"},
        raising=False,
    )
    monkeypatch.setattr(_MODULE, "_load_yaml", lambda path: {})  # noqa: ARG005
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.utils.config_contract.validate_shared_runtime_contract",
        lambda cw1_cfg, cw2_cfg: {"status": "ok"},  # noqa: ARG005
        raising=False,
    )

    run_id = _MODULE._execute_backtest(
        argparse.Namespace(
            run_name="bt-demo",
            transaction_cost_bps=25.0,
            cw2_config="cw2.yaml",
        )
    )
    report = _MODULE._execute_report(
        argparse.Namespace(
            run_id="run-1",
            cw2_config="cw2.yaml",
            report_name="cw2-report",
            report_output_dir="reports",
        )
    )
    assert run_id == "run-1"
    assert report["report_id"] == "report-1"

    assert (
        _MODULE._run_backtest_only(
            argparse.Namespace(
                cw1_config="cw1.yaml",
                cw2_config="cw2.yaml",
                run_name="bt-demo",
                transaction_cost_bps=None,
            )
        )
        == 0
    )
    assert (
        _MODULE._run_analysis_only(
            argparse.Namespace(run_id="run-1", cw2_config="cw2.yaml", robustness_run_id=None)
        )
        == 0
    )
    assert (
        _MODULE._run_report_only(
            argparse.Namespace(
                run_id="run-1",
                cw2_config="cw2.yaml",
                report_name="cw2-report",
                report_output_dir="reports",
            )
        )
        == 0
    )
    captured = capsys.readouterr()
    assert '"report_id": "report-1"' in captured.out


def test_execute_report_requires_run_id():
    try:
        _MODULE._execute_report(
            argparse.Namespace(
                run_id=None,
                cw2_config="cw2.yaml",
                report_name=None,
                report_output_dir=None,
            )
        )
    except ValueError as exc:
        assert "--run-id is required" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_run_backtest_and_analyse_validates_contract_and_executes(monkeypatch):
    captured = {}
    monkeypatch.setattr(_MODULE, "_load_yaml", lambda path: {"loaded_from": path})
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.utils.config_contract.validate_shared_runtime_contract",
        lambda cw1_cfg, cw2_cfg: captured.update({"cw1_cfg": cw1_cfg, "cw2_cfg": cw2_cfg}),
        raising=False,
    )
    monkeypatch.setattr(_MODULE, "_execute_backtest", lambda args: "run-1")  # noqa: ARG005
    monkeypatch.setattr(
        _MODULE,
        "_execute_analysis",
        lambda **kwargs: captured.update(kwargs) or {"status": "ok"},
    )

    rc = _MODULE._run_backtest_and_analyse(
        argparse.Namespace(
            cw1_config="cw1.yaml",
            cw2_config="cw2.yaml",
            robustness_run_id="robust-25bps",
        )
    )

    assert rc == 0
    assert captured["cw1_cfg"]["loaded_from"].endswith("cw1.yaml")
    assert captured["cw2_cfg"]["loaded_from"].endswith("cw2.yaml")
    assert captured["run_id"] == "run-1"
    assert captured["robustness_run_id_25bps"] == "robust-25bps"


def test_recommendation_entrypoints_validate_and_emit(monkeypatch, capsys):
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.recommendation.publish_recommendation_from_config",
        lambda **kwargs: {"recommendation_id": "rec-1", "status": "proposed"},
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.recommendation.apply_recommendation_decision",
        lambda **kwargs: {"recommendation_id": "rec-1", "status": "approved"},
        raising=False,
    )

    assert (
        _MODULE._run_recommend_only(
            argparse.Namespace(
                run_date="2026-04-15",
                cw2_config="cw2.yaml",
                recommendation_name="rec-demo",
            )
        )
        == 0
    )
    assert (
        _MODULE._run_recommendation_decision_only(
            argparse.Namespace(
                recommendation_id="rec-1",
                recommendation_name=None,
                decision_type="approve",
                actor="pm",
                notes="ok",
                cw2_config="cw2.yaml",
            )
        )
        == 0
    )
    captured = capsys.readouterr()
    assert '"recommendation_id": "rec-1"' in captured.out


def test_recommendation_decision_entrypoint_validates_required_args():
    cases = [
        (
            argparse.Namespace(
                recommendation_id="rec-1",
                recommendation_name=None,
                decision_type=None,
                actor="pm",
                notes=None,
                cw2_config="cw2.yaml",
            ),
            "--decision-type is required",
        ),
        (
            argparse.Namespace(
                recommendation_id="rec-1",
                recommendation_name=None,
                decision_type="approve",
                actor=None,
                notes=None,
                cw2_config="cw2.yaml",
            ),
            "--actor is required",
        ),
        (
            argparse.Namespace(
                recommendation_id=None,
                recommendation_name=None,
                decision_type="approve",
                actor="pm",
                notes=None,
                cw2_config="cw2.yaml",
            ),
            "--recommendation-id or --recommendation-name is required",
        ),
    ]

    for args, expected_message in cases:
        try:
            _MODULE._run_recommendation_decision_only(args)
        except ValueError as exc:
            assert expected_message in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_execute_misc_wrappers_delegate_to_module_apis(monkeypatch):
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.ops.run_audit_from_config",
        lambda **kwargs: {"readiness": {"overall_status": "ready"}},
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.ops.run_monitor_from_config",
        lambda **kwargs: {"status": "ready"},
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.ops.run_update_decision_from_config",
        lambda **kwargs: {"decision_scope": "monitor_only"},
        raising=False,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.recommendation.load_recommendation_package",
        lambda **kwargs: {"header": {"recommendation_name": "rec-1"}},
        raising=False,
    )

    args = argparse.Namespace(cw1_config="cw1.yaml", cw2_config="cw2.yaml", run_date="2026-04-15")
    assert _MODULE._execute_audit(args)["readiness"]["overall_status"] == "ready"
    assert _MODULE._execute_monitor(args)["status"] == "ready"
    assert _MODULE._execute_update_decision(args)["decision_scope"] == "monitor_only"
    assert (
        _MODULE._load_recommendation_package(
            recommendation_id="rec-1",
            cw2_config="cw2.yaml",
        )[
            "header"
        ]["recommendation_name"]
        == "rec-1"
    )


def test_execute_recommendation_decision_wrapper(monkeypatch):
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.recommendation.apply_recommendation_decision",
        lambda **kwargs: {"status": "approved", "actor": kwargs["actor"]},
        raising=False,
    )

    result = _MODULE._execute_recommendation_decision(
        recommendation_id="rec-1",
        recommendation_name=None,
        decision_type="approve",
        actor="pm",
        notes="ok",
        cw2_config="cw2.yaml",
    )

    assert result == {"status": "approved", "actor": "pm"}


def test_operate_briefing_renders_markdown(tmp_path):
    path = _MODULE._write_operate_briefing(
        run_date="2026-04-15",
        package={
            "header": {
                "recommendation_name": "rec-demo",
                "as_of_date": "2026-04-15",
                "portfolio_name": "cw2_core_equity",
                "recommendation_status": "published",
                "regime": "normal",
                "benchmark_ticker": "SPY",
                "num_positions": 3,
                "expected_turnover": 0.15,
                "avg_composite_alpha": 1.2,
                "summary_json": {
                    "sector_weights": {"Tech": 0.5},
                    "top_positions": [{"symbol": "AAPL", "weight": 0.1, "alpha": 1.5}],
                },
            },
            "items": [{"position_action": "buy"}, {"position_action": "hold"}],
        },
        audit_report={
            "readiness": {"overall_status": "ready"},
            "execution_assurance": {"operate_mode_execution": "recommendation_workflow_only"},
        },
        briefing_dir=str(tmp_path),
    )

    text = Path(path).read_text(encoding="utf-8")
    assert "Portfolio Recommendation Briefing: rec-demo" in text
    assert "`AAPL` weight=0.1 alpha=1.5" in text
    assert "`Tech`: 0.5" in text


def test_run_audit_monitor_update_only_emit_json(monkeypatch, capsys):
    monkeypatch.setattr(
        _MODULE,
        "_execute_audit",
        lambda args: {  # noqa: ARG005
            "readiness": {"overall_status": "ready"},
            "latest_run_id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        },
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_monitor",
        lambda args: {"status": "ok"},  # noqa: ARG005
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_update_decision",
        lambda args: {"decision_scope": "rebalance"},  # noqa: ARG005
    )

    assert _MODULE._run_audit_only(argparse.Namespace()) == 0
    assert _MODULE._run_monitor_only(argparse.Namespace()) == 0
    assert _MODULE._run_update_decision_only(argparse.Namespace()) == 0

    output = capsys.readouterr().out
    assert '"overall_status": "ready"' in output
    assert '"latest_run_id": "12345678-1234-5678-1234-567812345678"' in output
    assert '"status": "ok"' in output
    assert '"decision_scope": "rebalance"' in output


def test_run_operate_only_supports_auto_approve_and_publish(monkeypatch, tmp_path, capsys):
    decisions = []
    monkeypatch.setattr(_MODULE, "_run_cw2_only", lambda args: 0)  # noqa: ARG005
    monkeypatch.setattr(
        _MODULE,
        "_execute_recommendation",
        lambda args: {
            "recommendation_id": "rec-1",
            "status": "proposed",
        },  # noqa: ARG005
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_audit",
        lambda args: {  # noqa: ARG005
            "readiness": {"overall_status": "ready"},
            "execution_assurance": {
                "operate_mode_execution": "recommendation_workflow_only",
            },
        },
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_recommendation_decision",
        lambda **kwargs: decisions.append(kwargs["decision_type"])
        or {"status": kwargs["decision_type"]},
    )
    monkeypatch.setattr(
        _MODULE,
        "_load_recommendation_package",
        lambda **kwargs: {  # noqa: ARG005
            "header": {
                "recommendation_name": "rec-demo",
                "recommendation_status": "approved",
            },
            "items": [{"position_action": "buy"}],
        },
    )
    monkeypatch.setattr(
        _MODULE,
        "_write_operate_briefing",
        lambda **kwargs: str(tmp_path / "briefing.md"),
    )

    rc = _MODULE._run_operate_only(
        argparse.Namespace(
            auto_approve=True,
            auto_publish=True,
            decision_actor="pm",
            run_date="2026-04-15",
            cw2_config="cw2.yaml",
            briefing_dir=str(tmp_path),
        )
    )

    assert rc == 0
    assert decisions == ["approve", "publish"]
    output = capsys.readouterr().out
    assert '"briefing_path"' in output
    assert '"status": "approved"' in output


def test_run_operate_only_requires_ready_status_for_auto_approval(monkeypatch):
    monkeypatch.setattr(_MODULE, "_run_cw2_only", lambda args: 0)  # noqa: ARG005
    monkeypatch.setattr(
        _MODULE,
        "_execute_recommendation",
        lambda args: {
            "recommendation_id": "rec-1",
            "status": "proposed",
        },  # noqa: ARG005
    )
    monkeypatch.setattr(
        _MODULE,
        "_execute_audit",
        lambda args: {"readiness": {"overall_status": "warning"}},  # noqa: ARG005
    )

    try:
        _MODULE._run_operate_only(
            argparse.Namespace(
                auto_approve=True,
                auto_publish=False,
                decision_actor="pm",
                run_date="2026-04-15",
                cw2_config="cw2.yaml",
                briefing_dir=None,
            )
        )
    except RuntimeError as exc:
        assert "readiness.overall_status = 'ready'" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_run_operate_only_returns_feature_rc_when_feature_stage_fails(monkeypatch):
    monkeypatch.setattr(_MODULE, "_run_cw2_only", lambda args: 9)  # noqa: ARG005
    assert (
        _MODULE._run_operate_only(
            argparse.Namespace(
                auto_approve=False,
                auto_publish=False,
                decision_actor="pm",
                run_date="2026-04-15",
                cw2_config="cw2.yaml",
                briefing_dir=None,
            )
        )
        == 9
    )


def test_main_dispatches_default_feature_modes(monkeypatch):
    calls = {"cw2_only": 0, "upstream": 0}
    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_run_cw2_only",
        lambda args: calls.__setitem__("cw2_only", calls["cw2_only"] + 1) or 0,
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_with_upstream",
        lambda args: calls.__setitem__("upstream", calls["upstream"] + 1) or 0,
    )

    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(argparse.Namespace(mode="features", with_upstream=False)),
    )
    assert _MODULE.main() == 0
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(argparse.Namespace(mode="features", with_upstream=True)),
    )
    assert _MODULE.main() == 0
    assert calls == {"cw2_only": 1, "upstream": 1}


def test_main_uses_upstream_for_mode_short_circuits(monkeypatch):
    calls = {"upstream": 0}
    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_run_with_upstream",
        lambda args: calls.__setitem__("upstream", calls["upstream"] + 1) or 7,
    )
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(
            argparse.Namespace(
                mode="operate",
                with_upstream=True,
            )
        ),
    )

    assert _MODULE.main() == 7
    assert calls["upstream"] == 1


def test_main_dispatches_backtest_and_analyse_mode(monkeypatch):
    calls = {"backtest_and_analyse": 0}
    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(
        _MODULE,
        "_build_parser",
        lambda: _FakeParser(argparse.Namespace(mode="backtest-and-analyse", with_upstream=False)),
    )
    monkeypatch.setattr(
        _MODULE,
        "_run_backtest_and_analyse",
        lambda args: calls.__setitem__("backtest_and_analyse", calls["backtest_and_analyse"] + 1)
        or 0,
    )

    assert _MODULE.main() == 0
    assert calls["backtest_and_analyse"] == 1


def test_main_upstream_short_circuit_covers_other_modes(monkeypatch):
    monkeypatch.setattr(_MODULE, "_configure_logging", lambda: None)
    monkeypatch.setattr(_MODULE, "_load_env_layers", lambda: None)
    monkeypatch.setattr(_MODULE, "_run_with_upstream", lambda args: 5)  # noqa: ARG005

    for mode in ("backtest", "update-decision", "recommend"):
        monkeypatch.setattr(
            _MODULE,
            "_build_parser",
            lambda mode=mode: _FakeParser(argparse.Namespace(mode=mode, with_upstream=True)),
        )
        assert _MODULE.main() == 5


class _FakeParser:
    def __init__(self, namespace: argparse.Namespace):
        self._namespace = namespace

    def parse_args(self):
        return self._namespace
