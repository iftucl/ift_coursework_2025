from __future__ import annotations

"""Standalone CW2 entrypoint for feature engineering, portfolio construction, backtesting, analysis, and reporting."""

import argparse
import json
import logging
import os
import subprocess  # nosec B404
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if str(CW1_ROOT) not in sys.path:
    sys.path.insert(0, str(CW1_ROOT))

logger = logging.getLogger(__name__)


def _today_iso() -> str:
    """Return today's UTC date as an ISO ``YYYY-MM-DD`` string."""
    return datetime.now(timezone.utc).date().isoformat()


def _default_cw1_config() -> str:
    """Return the default shared CW1 configuration path."""
    return str(CW1_ROOT / "config" / "conf.yaml")


def _default_cw2_config() -> str:
    """Return the default CW2 configuration path."""
    return str(CW2_ROOT / "config" / "conf.yaml")


def _load_yaml(path: str) -> Dict[str, Any]:
    """Load one YAML config file, validating the default CW2 config when used."""
    resolved = Path(path).resolve()
    if resolved == Path(_default_cw2_config()).resolve():
        from team_Pearson.coursework_two.modules.utils import (
            config_validation as cw2_config_validation,
        )

        return cw2_config_validation.load_cw2_config(str(resolved))
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyYAML is not installed in the current interpreter. "
            "Run CW2 with the shared coursework_one environment."
        ) from exc
    with resolved.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _configure_logging() -> None:
    """Configure the shared CLI logging format for CW2 entrypoints."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _configure_cli_streams() -> None:
    """Avoid Windows console encoding failures when argparse prints local paths."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="replace")


def _json_default(value: Any) -> Any:
    """Serialize datetimes, dates, UUIDs, and other CLI payload objects safely."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _print_json(payload: Dict[str, Any]) -> None:
    """Print one JSON payload using the shared non-brittle CLI serializer."""
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def _load_env_layers() -> None:
    """Load shared CW1 env first, then let an optional CW2 env override it."""
    from modules.utils.env import load_dotenv_if_exists

    load_dotenv_if_exists(CW1_ROOT / ".env")
    load_dotenv_if_exists(CW2_ROOT / ".env", override=True)


def _resolve_company_limit(args: argparse.Namespace, cw1_cfg: Dict[str, Any]) -> Optional[int]:
    """Resolve the effective company limit from CLI args or CW1 config."""
    if args.company_limit is not None:
        return args.company_limit
    pipeline_cfg = cw1_cfg.get("pipeline") or {}
    return pipeline_cfg.get("company_limit")


def _resolve_country_allowlist(cw1_cfg: Dict[str, Any]) -> Optional[object]:
    """Read the country allowlist from the shared CW1 universe config."""
    universe_cfg = cw1_cfg.get("universe") or {}
    return universe_cfg.get("country_allowlist")


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CW2 standalone CLI parser."""
    parser = argparse.ArgumentParser(
        description="CW2 standalone runner using shared CW1 infrastructure.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=(
            "features",
            "operate",
            "backtest",
            "analyse",
            "backtest-and-analyse",
            "full-run",
            "audit",
            "monitor",
            "update-decision",
            "recommend",
            "decide-recommendation",
            "report",
        ),
        default="features",
        help="CW2 run mode: feature pipeline, operated main flow (features -> recommendation -> audit), backtest engine, analysis, combined backtest+analysis, readiness audit, persisted operations monitoring snapshot, daily update-decision materialization, recommendation publishing, recommendation approval/publish workflow, or database-backed chart/report generation.",
    )
    parser.add_argument(
        "--run-date",
        default=_today_iso(),
        help="Run date in YYYY-MM-DD. Used by feature mode and as an optional backtest reference date.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Backtest-only: unique run identifier written to backtest_runs.",
    )
    parser.add_argument(
        "--transaction-cost-bps",
        type=float,
        default=None,
        help="Backtest-only: optional override for transaction cost in basis points; also applied to intraday trigger cost unless separately configured in YAML.",
    )
    parser.add_argument(
        "--recommendation-name",
        default=None,
        help="Recommendation-only: optional human-readable identifier for the published portfolio recommendation.",
    )
    parser.add_argument(
        "--recommendation-id",
        default=None,
        help="Recommendation decision mode: explicit recommendation UUID.",
    )
    parser.add_argument(
        "--decision-type",
        choices=("approve", "reject", "publish"),
        default=None,
        help="Recommendation decision mode: workflow action to record.",
    )
    parser.add_argument(
        "--actor",
        default=None,
        help="Recommendation decision mode: actor name recorded in the audit trail.",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Optional approval/rejection/publication notes.",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Operate mode: automatically record an approval decision after readiness audit passes.",
    )
    parser.add_argument(
        "--auto-publish",
        action="store_true",
        help="Operate mode: automatically publish the recommendation after readiness audit passes. Implies --auto-approve when approval is required.",
    )
    parser.add_argument(
        "--decision-actor",
        default="cw2_operate",
        help="Operate mode: actor recorded for automatic approval/publication decisions.",
    )
    parser.add_argument(
        "--briefing-dir",
        default=None,
        help="Operate mode: optional directory for a generated markdown briefing. Defaults to coursework_two/outputs/briefings.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Analysis/report-only: existing backtest_runs.run_id to analyse or render into a report.",
    )
    parser.add_argument(
        "--robustness-run-id",
        default=None,
        help="Analysis-only: optional 25 bps robustness run_id for scorecard criterion 4.",
    )
    parser.add_argument(
        "--report-name",
        default=None,
        help="Report-only: optional human-readable name for the generated reporting package.",
    )
    parser.add_argument(
        "--report-output-dir",
        default=None,
        help="Report-only: optional root directory for chart/markdown/json artifacts. Defaults to coursework_two/outputs/reports.",
    )
    parser.add_argument(
        "--company-limit",
        type=int,
        default=None,
        help="Optional universe cap. Defaults to coursework_one/config/conf.yaml.",
    )
    parser.add_argument(
        "--cw1-config",
        default=_default_cw1_config(),
        help="Path to the shared CW1 infrastructure config.",
    )
    parser.add_argument(
        "--cw2-config",
        default=_default_cw2_config(),
        help="Path to the CW2 factor/risk/portfolio config.",
    )
    parser.add_argument(
        "--with-upstream",
        action="store_true",
        help="Run the full CW1 upstream pipeline first, then let CW1 hand off into CW2.",
    )
    parser.add_argument(
        "--frequency",
        default=None,
        help="Upstream-only: override run frequency passed to coursework_one/Main.py.",
    )
    parser.add_argument(
        "--backfill-years",
        type=int,
        default=None,
        help="Upstream-only: override lookback years passed to coursework_one/Main.py.",
    )
    parser.add_argument(
        "--enabled-extractors",
        default=None,
        help="Upstream-only: comma-separated extractors for coursework_one/Main.py.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Upstream-only: run CW1 without loading to storage.",
    )
    parser.add_argument(
        "--index-mongo",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Upstream-only: keep or disable the post-run Mongo index stage.",
    )
    parser.add_argument(
        "--smoke-profile",
        "--quick-profile",
        dest="quick_profile",
        action="store_true",
        help=(
            "Full-run only: use a temporary relaxed CW2 config for fast "
            "end-to-end smoke validation. Defaults off for the full run."
        ),
    )
    parser.add_argument(
        "--smoke-lookback-years",
        "--quick-lookback-years",
        dest="quick_lookback_years",
        type=int,
        default=1,
        help="Full-run only: lookback years used by the temporary smoke CW2 config.",
    )
    return parser


def _run_full_chain(args: argparse.Namespace) -> int:
    """Delegate ``--mode full-run`` to the dedicated CW2 full-chain script."""
    cmd = [
        sys.executable,
        str((CW2_ROOT / "scripts" / "run_full_chain.py").resolve()),
        "--run-date",
        str(args.run_date),
        "--cw1-config",
        str(Path(args.cw1_config).resolve()),
        "--cw2-config",
        str(Path(args.cw2_config).resolve()),
        "--decision-actor",
        str(args.decision_actor),
    ]
    if args.company_limit is not None:
        cmd.extend(["--company-limit", str(args.company_limit)])
    if args.frequency:
        cmd.extend(["--frequency", str(args.frequency)])
    if args.backfill_years is not None:
        cmd.extend(["--backfill-years", str(args.backfill_years)])
    if args.enabled_extractors:
        cmd.extend(["--enabled-extractors", str(args.enabled_extractors)])
    if args.run_name:
        cmd.extend(["--run-name", str(args.run_name)])
    if args.report_name:
        cmd.extend(["--report-name", str(args.report_name)])
    if args.report_output_dir:
        cmd.extend(["--report-output-dir", str(args.report_output_dir)])
    if args.briefing_dir:
        cmd.extend(["--briefing-dir", str(args.briefing_dir)])
    if args.transaction_cost_bps is not None:
        cmd.extend(["--transaction-cost-bps", str(args.transaction_cost_bps)])
    if args.robustness_run_id:
        cmd.extend(["--robustness-run-id", str(args.robustness_run_id)])
    if args.auto_approve:
        cmd.append("--auto-approve")
    if args.auto_publish:
        cmd.append("--auto-publish")
    if args.quick_profile:
        cmd.append("--smoke-profile")
    if args.quick_lookback_years is not None:
        cmd.extend(["--smoke-lookback-years", str(args.quick_lookback_years)])

    logger.info(
        "cw2_main: delegating single-command full chain run_date=%s cmd=%s",
        args.run_date,
        cmd,
    )
    completed = subprocess.run(cmd, cwd=str(CW2_ROOT), check=False)  # nosec B603
    return int(completed.returncode)


def _run_with_upstream(args: argparse.Namespace) -> int:
    """Run the shared CW1 upstream pipeline before continuing with CW2."""
    from team_Pearson.coursework_two.modules.utils.config_contract import (
        evaluate_upstream_history_contract,
        validate_shared_runtime_contract,
    )

    cw1_cfg = _load_yaml(str(Path(args.cw1_config).resolve()))
    cw2_cfg = _load_yaml(str(Path(args.cw2_config).resolve()))
    contract = validate_shared_runtime_contract(cw1_cfg, cw2_cfg)
    history_contract = evaluate_upstream_history_contract(
        cw1_cfg,
        cw2_cfg,
        effective_backfill_years=args.backfill_years,
    )
    logger.info("cw2_main: validated shared cw1/cw2 contract=%s", contract)
    if history_contract.get("warning"):
        logger.warning(
            "cw2_main: %s",
            history_contract["warning"],
        )

    env = os.environ.copy()
    env["CW2_CONFIG_PATH"] = str(Path(args.cw2_config).resolve())

    cmd = [
        sys.executable,
        str(CW1_ROOT / "Main.py"),
        "--config",
        str(Path(args.cw1_config).resolve()),
        "--run-date",
        str(args.run_date),
    ]
    if args.company_limit is not None:
        cmd.extend(["--company-limit", str(args.company_limit)])
    if args.frequency:
        cmd.extend(["--frequency", str(args.frequency)])
    if args.backfill_years is not None:
        cmd.extend(["--backfill-years", str(args.backfill_years)])
    if args.enabled_extractors:
        cmd.extend(["--enabled-extractors", str(args.enabled_extractors)])
    if args.dry_run:
        cmd.append("--dry-run")
    if not args.index_mongo:
        cmd.append("--no-index-mongo")

    logger.info("cw2_main: delegating to CW1 orchestrator with shared infrastructure")
    completed = subprocess.run(cmd, cwd=str(CW1_ROOT), env=env, check=False)  # nosec B603
    return int(completed.returncode)


def _run_cw2_only(args: argparse.Namespace) -> int:
    """Materialize CW2 feature and portfolio outputs from existing curated data."""
    from team_Pearson.coursework_two.modules.utils.config_contract import (
        validate_shared_runtime_contract,
    )

    from modules.db.universe import get_company_universe
    from modules.transform.cw2_features import build_and_load_cw2_features

    cw1_cfg = _load_yaml(str(Path(args.cw1_config).resolve()))
    cw2_cfg = _load_yaml(str(Path(args.cw2_config).resolve()))
    contract = validate_shared_runtime_contract(cw1_cfg, cw2_cfg)
    company_limit = _resolve_company_limit(args, cw1_cfg)
    country_allowlist = _resolve_country_allowlist(cw1_cfg)
    symbols = get_company_universe(
        company_limit,
        country_allowlist=country_allowlist,
        as_of_date=args.run_date,
    )

    logger.info(
        "cw2_main: building CW2 outputs only run_date=%s symbols=%d country_filter=%s contract=%s",
        args.run_date,
        len(symbols),
        country_allowlist or "ALL",
        contract,
    )
    result = build_and_load_cw2_features(
        run_date=str(args.run_date),
        symbols=symbols,
        config_path=str(Path(args.cw2_config).resolve()),
    )
    logger.info("cw2_main: result=%s", result)

    produced = sum(
        int(result.get(key, 0))
        for key in (
            "universe_screen",
            "sub_scores",
            "factor_scores",
            "risk_overlay",
            "portfolio_targets",
        )
    )
    if produced == 0:
        logger.error(
            "cw2_main: no CW2 rows were produced. Run the upstream pipeline first or use --with-upstream."
        )
        return 1
    return 0


def _default_backtest_run_name() -> str:
    """Build a timestamped default run name for ad hoc backtests."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"cw2_backtest_{ts}"


def _execute_backtest(args: argparse.Namespace) -> str:
    """Run the CW2 backtest engine and return the created ``run_id``."""
    from team_Pearson.coursework_two.modules.backtest import run_backtest_from_config

    run_name = str(args.run_name or _default_backtest_run_name())
    config_override: Optional[Dict[str, Any]] = None
    if args.transaction_cost_bps is not None:
        config_override = {
            "backtest": {
                "transaction_cost_bps": float(args.transaction_cost_bps),
                "intraday_triggers": {
                    "transaction_cost_bps": float(args.transaction_cost_bps),
                },
            }
        }
    logger.info(
        "cw2_main: running backtest mode run_name=%s cw2_config=%s transaction_cost_bps=%s",
        run_name,
        args.cw2_config,
        args.transaction_cost_bps,
    )
    run_id = run_backtest_from_config(
        run_name=run_name,
        config_path=str(Path(args.cw2_config).resolve()),
        config_override=config_override,
    )
    logger.info("cw2_main: backtest completed run_name=%s run_id=%s", run_name, run_id)
    return run_id


def _run_backtest_only(args: argparse.Namespace) -> int:
    """Validate config contracts and execute backtest-only mode."""
    from team_Pearson.coursework_two.modules.utils.config_contract import (
        validate_shared_runtime_contract,
    )

    validate_shared_runtime_contract(
        _load_yaml(str(Path(args.cw1_config).resolve())),
        _load_yaml(str(Path(args.cw2_config).resolve())),
    )
    _execute_backtest(args)
    return 0


def _run_analysis_only(args: argparse.Namespace) -> int:
    """Execute analysis-only mode for one existing backtest run."""
    if not args.run_id:
        raise ValueError("--run-id is required for --mode analyse")
    logger.info(
        "cw2_main: running analysis mode run_id=%s cw2_config=%s",
        args.run_id,
        args.cw2_config,
    )
    result = _execute_analysis(
        run_id=str(args.run_id),
        cw2_config=args.cw2_config,
        robustness_run_id_25bps=(
            str(args.robustness_run_id) if args.robustness_run_id is not None else None
        ),
    )
    logger.info("cw2_main: analysis completed run_id=%s result=%s", args.run_id, result)
    return 0


def _execute_report(args: argparse.Namespace) -> Dict[str, Any]:
    """Generate a database-backed report package for one backtest run."""
    from team_Pearson.coursework_two.modules import reporting as reporting_mod

    if not args.run_id:
        raise ValueError("--run-id is required for --mode report")
    logger.info(
        "cw2_main: generating report run_id=%s cw2_config=%s report_name=%s report_output_dir=%s",
        args.run_id,
        args.cw2_config,
        args.report_name,
        args.report_output_dir,
    )
    return reporting_mod.generate_backtest_report_from_config(
        run_id=str(args.run_id),
        config_path=str(Path(args.cw2_config).resolve()),
        report_name=(str(args.report_name) if args.report_name else None),
        output_dir=(str(args.report_output_dir) if args.report_output_dir else None),
    )


def _run_report_only(args: argparse.Namespace) -> int:
    """Execute report-only mode and print the resulting artifact summary."""
    result = _execute_report(args)
    logger.info("cw2_main: report completed run_id=%s result=%s", args.run_id, result)
    _print_json(result)
    return 0


def _run_backtest_and_analyse(args: argparse.Namespace) -> int:
    """Run the stored-strategy backtest and immediate post-run analysis."""
    from team_Pearson.coursework_two.modules.utils.config_contract import (
        validate_shared_runtime_contract,
    )

    validate_shared_runtime_contract(
        _load_yaml(str(Path(args.cw1_config).resolve())),
        _load_yaml(str(Path(args.cw2_config).resolve())),
    )
    run_id = _execute_backtest(args)
    result = _execute_analysis(
        run_id=str(run_id),
        cw2_config=args.cw2_config,
        robustness_run_id_25bps=(
            str(args.robustness_run_id) if args.robustness_run_id is not None else None
        ),
    )
    logger.info("cw2_main: backtest+analysis completed run_id=%s result=%s", run_id, result)
    return 0


def _run_audit_only(args: argparse.Namespace) -> int:
    """Run the readiness audit and print the JSON report."""
    report = _execute_audit(args)
    _print_json(report)
    return 0


def _run_monitor_only(args: argparse.Namespace) -> int:
    """Run the persisted operations monitoring snapshot and print it."""
    report = _execute_monitor(args)
    _print_json(report)
    return 0


def _run_update_decision_only(args: argparse.Namespace) -> int:
    """Materialize the daily update decision and print the result JSON."""
    report = _execute_update_decision(args)
    _print_json(report)
    return 0


def _run_recommend_only(args: argparse.Namespace) -> int:
    """Publish a formal portfolio recommendation and print its summary."""
    result = _execute_recommendation(args)
    logger.info("cw2_main: recommendation published result=%s", result)
    _print_json(result)
    return 0


def _execute_recommendation(args: argparse.Namespace) -> Dict[str, Any]:
    """Publish a recommendation object from the latest stored target positions."""
    from team_Pearson.coursework_two.modules.recommendation import (
        publish_recommendation_from_config,
    )

    logger.info(
        "cw2_main: publishing recommendation run_date=%s cw2_config=%s",
        args.run_date,
        args.cw2_config,
    )
    return publish_recommendation_from_config(
        run_date=str(args.run_date),
        config_path=str(Path(args.cw2_config).resolve()),
        recommendation_name=(str(args.recommendation_name) if args.recommendation_name else None),
    )


def _run_recommendation_decision_only(args: argparse.Namespace) -> int:
    """Record one approve/reject/publish decision for a recommendation."""
    if not args.decision_type:
        raise ValueError("--decision-type is required for --mode decide-recommendation")
    if not args.actor:
        raise ValueError("--actor is required for --mode decide-recommendation")
    if not args.recommendation_id and not args.recommendation_name:
        raise ValueError(
            "--recommendation-id or --recommendation-name is required for --mode decide-recommendation"
        )

    result = _execute_recommendation_decision(
        recommendation_id=(str(args.recommendation_id) if args.recommendation_id else None),
        recommendation_name=(str(args.recommendation_name) if args.recommendation_name else None),
        decision_type=str(args.decision_type),
        actor=str(args.actor),
        notes=(str(args.notes) if args.notes else None),
        cw2_config=args.cw2_config,
    )
    logger.info("cw2_main: recommendation decision recorded result=%s", result)
    _print_json(result)
    return 0


def _execute_recommendation_decision(
    *,
    recommendation_id: Optional[str],
    recommendation_name: Optional[str],
    decision_type: str,
    actor: str,
    notes: Optional[str],
    cw2_config: str,
) -> Dict[str, Any]:
    """Apply one recommendation workflow decision through the CW2 module API."""
    from team_Pearson.coursework_two.modules import recommendation as recommendation_mod

    logger.info(
        "cw2_main: recording recommendation decision type=%s recommendation_id=%s recommendation_name=%s",
        decision_type,
        recommendation_id,
        recommendation_name,
    )
    return recommendation_mod.apply_recommendation_decision(
        decision_type=decision_type,
        actor=actor,
        recommendation_id=recommendation_id,
        recommendation_name=recommendation_name,
        notes=notes,
        config_path=str(Path(cw2_config).resolve()),
    )


def _execute_audit(args: argparse.Namespace) -> Dict[str, Any]:
    """Run the cross-store readiness audit for the active CW1/CW2 config pair."""
    from team_Pearson.coursework_two.modules.ops import run_audit_from_config

    logger.info(
        "cw2_main: running readiness audit cw1_config=%s cw2_config=%s",
        args.cw1_config,
        args.cw2_config,
    )
    return run_audit_from_config(
        cw1_config_path=str(Path(args.cw1_config).resolve()),
        cw2_config_path=str(Path(args.cw2_config).resolve()),
    )


def _execute_monitor(args: argparse.Namespace) -> Dict[str, Any]:
    """Collect the latest SQL-backed control-plane monitoring snapshot."""
    from team_Pearson.coursework_two.modules.ops import run_monitor_from_config

    logger.info(
        "cw2_main: running persisted operations monitoring snapshot cw1_config=%s cw2_config=%s",
        args.cw1_config,
        args.cw2_config,
    )
    return run_monitor_from_config(
        cw1_config_path=str(Path(args.cw1_config).resolve()),
        cw2_config_path=str(Path(args.cw2_config).resolve()),
    )


def _execute_update_decision(args: argparse.Namespace) -> Dict[str, Any]:
    """Materialize the daily operate/monitor/rebalance decision for one run date."""
    from team_Pearson.coursework_two.modules.ops import run_update_decision_from_config

    logger.info(
        "cw2_main: running update decision run_date=%s cw2_config=%s",
        args.run_date,
        args.cw2_config,
    )
    return run_update_decision_from_config(
        run_date=str(args.run_date),
        config_path=str(Path(args.cw2_config).resolve()),
    )


def _execute_analysis(
    *,
    run_id: str,
    cw2_config: str,
    robustness_run_id_25bps: Optional[str],
) -> Dict[str, Any]:
    """Run the CW2 analysis module for one existing backtest ``run_id``."""
    from team_Pearson.coursework_two.modules.analysis import run_analysis_from_config

    return run_analysis_from_config(
        run_id=run_id,
        config_path=str(Path(cw2_config).resolve()),
        robustness_run_id_25bps=robustness_run_id_25bps,
    )


def _run_operate_only(args: argparse.Namespace) -> int:
    """Execute the production-style CW2 operate flow and emit a briefing."""
    auto_approve = bool(args.auto_approve or args.auto_publish)

    feature_rc = _run_cw2_only(args)
    if feature_rc != 0:
        return feature_rc

    recommendation_result = _execute_recommendation(args)
    audit_report = _execute_audit(args)
    readiness = dict(audit_report.get("readiness") or {})
    decisions = []

    if auto_approve:
        if str(readiness.get("overall_status", "")).lower() != "ready":
            raise RuntimeError(
                "Automated recommendation approval/publish requires readiness.overall_status = 'ready'"
            )
        decisions.append(
            _execute_recommendation_decision(
                recommendation_id=str(recommendation_result["recommendation_id"]),
                recommendation_name=None,
                decision_type="approve",
                actor=str(args.decision_actor),
                notes="Auto-approved by operate flow after readiness audit passed.",
                cw2_config=args.cw2_config,
            )
        )
    if args.auto_publish:
        decisions.append(
            _execute_recommendation_decision(
                recommendation_id=str(recommendation_result["recommendation_id"]),
                recommendation_name=None,
                decision_type="publish",
                actor=str(args.decision_actor),
                notes="Auto-published by operate flow after readiness audit passed.",
                cw2_config=args.cw2_config,
            )
        )

    package = _load_recommendation_package(
        recommendation_id=str(recommendation_result["recommendation_id"]),
        cw2_config=args.cw2_config,
    )
    execution_assurance = dict(audit_report.get("execution_assurance") or {})
    recommendation_summary = {
        **recommendation_result,
        "status": str(
            (package.get("header") or {}).get("recommendation_status")
            or recommendation_result.get("status")
        ),
    }
    briefing_path = _write_operate_briefing(
        run_date=str(args.run_date),
        package=package,
        audit_report=audit_report,
        briefing_dir=args.briefing_dir,
    )

    summary = {
        "run_date": str(args.run_date),
        "execution_assurance": execution_assurance,
        "recommendation": recommendation_summary,
        "decisions": decisions,
        "briefing_path": briefing_path,
        "audit": readiness,
    }
    logger.info("cw2_main: operate flow completed summary=%s", summary)
    _print_json(summary)
    return 0


def _load_recommendation_package(*, recommendation_id: str, cw2_config: str) -> Dict[str, Any]:
    """Load one stored recommendation package for briefing or review output."""
    from team_Pearson.coursework_two.modules import recommendation as recommendation_mod

    return recommendation_mod.load_recommendation_package(
        recommendation_id=recommendation_id,
        config_path=str(Path(cw2_config).resolve()),
    )


def _write_operate_briefing(
    *,
    run_date: str,
    package: Dict[str, Any],
    audit_report: Dict[str, Any],
    briefing_dir: Optional[str],
) -> str:
    """Render a markdown briefing for the latest operate-mode recommendation."""
    header = dict(package.get("header") or {})
    items = list(package.get("items") or [])
    readiness = dict(audit_report.get("readiness") or {})
    execution_assurance = dict(audit_report.get("execution_assurance") or {})
    summary_json = dict(header.get("summary_json") or {})
    sector_weights = dict(summary_json.get("sector_weights") or {})
    top_positions = list(summary_json.get("top_positions") or [])

    action_counts: Dict[str, int] = {}
    for item in items:
        action = str(item.get("position_action") or "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1

    output_dir = Path(briefing_dir) if briefing_dir else (CW2_ROOT / "outputs" / "briefings")
    output_dir.mkdir(parents=True, exist_ok=True)
    recommendation_name = str(header.get("recommendation_name") or "recommendation")
    file_path = output_dir / f"{recommendation_name}.md"

    lines = [
        f"# Portfolio Recommendation Briefing: {recommendation_name}",
        "",
        "## Overview",
        f"- Run date: `{run_date}`",
        f"- As of date: `{header.get('as_of_date')}`",
        f"- Portfolio: `{header.get('portfolio_name')}`",
        f"- Status: `{header.get('recommendation_status')}`",
        f"- Regime: `{header.get('regime')}`",
        f"- Benchmark: `{header.get('benchmark_ticker')}`",
        f"- Positions: `{header.get('num_positions')}`",
        f"- Expected turnover: `{header.get('expected_turnover')}`",
        f"- Average composite alpha: `{header.get('avg_composite_alpha')}`",
        "",
        "## Readiness",
        f"- Overall status: `{readiness.get('overall_status')}`",
        f"- Core SQL ready: `{readiness.get('core_sql_ready')}`",
        f"- Feature pipeline ready: `{readiness.get('feature_pipeline_ready')}`",
        f"- Storage ready: `{readiness.get('storage_ready')}`",
        f"- Backtest ready: `{readiness.get('backtest_ready')}`",
        f"- Analysis materialized: `{readiness.get('analysis_materialized')}`",
        f"- Recommendation materialized: `{readiness.get('recommendation_materialized')}`",
        "",
        "## Execution Model",
        f"- Backtest execution: `{execution_assurance.get('backtest_execution_mode', 'simulated_portfolio_execution')}`",
        f"- Operate-mode execution: `{execution_assurance.get('operate_mode_execution', 'recommendation_workflow_only')}`",
        f"- Kafka processing scope: `{execution_assurance.get('kafka_event_processing_scope', 'internal_audit_consumer')}`",
        f"- External executor present: `{execution_assurance.get('external_executor_present', False)}`",
        f"- Real-money trading enabled: `{execution_assurance.get('real_money_trading_enabled', False)}`",
        "",
        "## Position Actions",
    ]
    for action in sorted(action_counts):
        lines.append(f"- `{action}`: {action_counts[action]}")
    lines.extend(["", "## Top Positions"])
    for row in top_positions[:10]:
        lines.append(f"- `{row.get('symbol')}` weight={row.get('weight')} alpha={row.get('alpha')}")
    lines.extend(["", "## Sector Weights"])
    for sector, weight in sorted(
        sector_weights.items(), key=lambda item: (-float(item[1]), str(item[0]))
    ):
        lines.append(f"- `{sector}`: {weight}")

    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(file_path)


def main() -> int:
    """Parse CLI args and dispatch to the requested CW2 operating mode."""
    _configure_cli_streams()
    _configure_logging()
    _load_env_layers()
    args = _build_parser().parse_args()

    if args.mode in {"backtest", "backtest-and-analyse"}:
        if args.with_upstream:
            upstream_rc = _run_with_upstream(args)
            if upstream_rc != 0:
                return upstream_rc
        if args.mode == "backtest":
            return _run_backtest_only(args)
        return _run_backtest_and_analyse(args)

    if args.mode == "analyse":
        return _run_analysis_only(args)

    if args.mode == "full-run":
        return _run_full_chain(args)

    if args.mode == "audit":
        return _run_audit_only(args)

    if args.mode == "monitor":
        return _run_monitor_only(args)

    if args.mode == "update-decision":
        if args.with_upstream:
            upstream_rc = _run_with_upstream(args)
            if upstream_rc != 0:
                return upstream_rc
        return _run_update_decision_only(args)

    if args.mode == "recommend":
        if args.with_upstream:
            upstream_rc = _run_with_upstream(args)
            if upstream_rc != 0:
                return upstream_rc
        return _run_recommend_only(args)

    if args.mode == "operate":
        if args.with_upstream:
            upstream_rc = _run_with_upstream(args)
            if upstream_rc != 0:
                return upstream_rc
        return _run_operate_only(args)

    if args.mode == "decide-recommendation":
        return _run_recommendation_decision_only(args)

    if args.mode == "report":
        return _run_report_only(args)

    if args.with_upstream:
        return _run_with_upstream(args)
    return _run_cw2_only(args)


if __name__ == "__main__":
    raise SystemExit(main())
