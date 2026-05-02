from __future__ import annotations

"""One-command full-chain runner for CW1 + CW2."""

import argparse
import copy
import logging
import os
import subprocess  # nosec B404
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from minio import Minio
from pymongo.collection import Collection

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(CW1_ROOT) not in sys.path:
    sys.path.insert(0, str(CW1_ROOT))

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_one.modules.utils.kafka import resolve_kafka_config  # noqa: E402
from team_Pearson.coursework_one.modules.utils.mongo import (  # noqa: E402
    build_mongo_collection,
    resolve_mongo_db,
)
from team_Pearson.coursework_two.modules.analysis import run_analysis_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.backtest import run_backtest_from_config  # noqa: E402
from team_Pearson.coursework_two.modules.ops import (  # noqa: E402
    run_audit_from_config,
    run_kafka_event_audit_from_config,
)
from team_Pearson.coursework_two.modules.reporting import (  # noqa: E402
    generate_backtest_report_from_config,
)
from team_Pearson.coursework_two.scripts.orchestration import (  # noqa: E402
    coerce_optional_int,
    default_cw1_config,
    default_cw2_config,
    load_env_layers,
    load_yaml,
    print_json,
)

logger = logging.getLogger(__name__)

_DEFAULT_MONGO_COLLECTION = "news_articles"
_CW2_SCHEMA_ORDER = (
    "cw2_feature_schema.sql",
    "cw2_ops_schema.sql",
    "cw2_recommendation_schema.sql",
    "cw2_backtest_schema.sql",
    "cw2_intraday_schema.sql",
    "cw2_analysis_schema.sql",
    "cw2_reporting_schema.sql",
)
_READINESS_AUDIT_MAX_ATTEMPTS = 3
_READINESS_AUDIT_RETRY_DELAY_SECONDS = 5.0


def _today_iso() -> str:
    """Return today's UTC date in ISO format."""
    return datetime.now(timezone.utc).date().isoformat()


def _configure_logging() -> None:
    """Configure the log format used by the full-chain wrapper."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser for the one-command full-chain workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the full Team Pearson chain from DB init through CW2 report "
            "with a single command."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--run-date", default=_today_iso(), help="YYYY-MM-DD")
    parser.add_argument("--cw1-config", default=default_cw1_config())
    parser.add_argument("--cw2-config", default=default_cw2_config())
    parser.add_argument(
        "--company-limit",
        type=int,
        default=0,
        help=(
            "Universe cap. Default 0 means full universe for the full-chain "
            "runner, regardless of any CW1 sample/debug config default."
        ),
    )
    parser.add_argument(
        "--frequency",
        default="daily",
        help="Frequency override passed to the CW1 orchestrator.",
    )
    parser.add_argument(
        "--backfill-years",
        type=int,
        default=None,
        help="Historical years to refresh upstream. Defaults to CW1 config.",
    )
    parser.add_argument(
        "--enabled-extractors",
        default="source_a,source_b,market_factors",
        help="Comma-separated extractor list forwarded to CW1.",
    )
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--report-name", default=None)
    parser.add_argument("--report-output-dir", default=None)
    parser.add_argument("--briefing-dir", default=None)
    parser.add_argument("--transaction-cost-bps", type=float, default=None)
    parser.add_argument("--robustness-run-id", default=None)
    parser.add_argument("--decision-actor", default="cw2_full_run")
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--auto-publish", action="store_true")
    parser.add_argument(
        "--smoke-profile",
        "--quick-profile",
        dest="quick_profile",
        action="store_true",
        help=(
            "Generate a temporary relaxed CW2 config for fast end-to-end "
            "smoke validation only, using an isolated smoke-validation "
            "portfolio namespace without changing the checked-in production "
            "config."
        ),
    )
    parser.add_argument(
        "--smoke-lookback-years",
        "--quick-lookback-years",
        dest="quick_lookback_years",
        type=int,
        default=1,
        help="Smoke profile only: lookback window for monthly backfill and backtest.",
    )
    return parser


def _resolve_effective_backfill_years(args: argparse.Namespace, cw1_cfg: Dict[str, Any]) -> int:
    """Resolve the upstream history refresh window from args or CW1 config."""
    if args.backfill_years is not None:
        return int(args.backfill_years)
    return int(((cw1_cfg.get("pipeline") or {}).get("backfill_years")) or 5)


def _resolve_snapshot_years(
    *, cw1_cfg: Dict[str, Any], cw2_cfg: Dict[str, Any], backfill_years: int
) -> int:
    """Choose a month-end snapshot window that covers both upstream and backtest needs."""
    cw2_lookback = int(((cw2_cfg.get("backtest") or {}).get("lookback_years")) or 5)
    return max(int(backfill_years), cw2_lookback)


def _snapshot_window(run_date: date, years: int) -> tuple[date, date]:
    """Return the inclusive month-end snapshot window ending on ``run_date``."""
    return date(run_date.year - years, run_date.month, 1), run_date


def _default_run_name(run_date: date) -> str:
    """Generate a timestamped default run name for the full-chain wrapper."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"cw2_full_chain_{run_date.isoformat()}_{ts}"


def _effective_company_limit(raw_value: Optional[int]) -> int:
    """Normalize the optional company-limit override used by the full chain."""
    coerced = coerce_optional_int(raw_value)
    if coerced is None:
        return 0
    return int(coerced)


def _quick_floor(company_limit: int) -> int:
    """Return the minimum name count used by the temporary smoke profile."""
    if company_limit > 0:
        if company_limit <= 3:
            return int(company_limit)
        return max(3, min(10, int(round(int(company_limit) * 0.6))))
    return 10


def _quick_cap(company_limit: int, floor_names: int) -> int:
    """Return the maximum name count used by the temporary smoke profile."""
    if company_limit > 0:
        return max(floor_names, min(int(company_limit), max(floor_names, 15)))
    return max(floor_names, 15)


def _quick_required_factor_groups(cw2_cfg: Dict[str, Any]) -> list[str]:
    """Resolve the factor groups that must stay viable in a smoke run."""
    risk_cfg = dict(cw2_cfg.get("risk_overlay") or {})
    explicit_groups = [
        str(group).strip()
        for group in (risk_cfg.get("missingness_factor_groups") or [])
        if str(group).strip()
    ]
    if explicit_groups:
        return explicit_groups

    required_groups = [
        str(group).strip()
        for group in (risk_cfg.get("required_factor_groups") or [])
        if str(group).strip()
    ]
    if required_groups:
        return required_groups

    factor_cfg = dict(cw2_cfg.get("factors") or {})
    return [
        str(group_name).strip()
        for group_name, settings in factor_cfg.items()
        if str(group_name).strip() and (settings or {}).get("sub_variables")
    ]


def _quick_required_sub_variable_count(cw2_cfg: Dict[str, Any]) -> int:
    """Count the sub-variables that define smoke-run scoring viability."""
    factor_cfg = dict(cw2_cfg.get("factors") or {})
    required_groups = _quick_required_factor_groups(cw2_cfg)
    if required_groups:
        configured = sum(
            len((factor_cfg.get(group_name) or {}).get("sub_variables") or [])
            for group_name in required_groups
        )
        if configured > 0:
            return int(configured)

    fallback = sum(
        len((settings or {}).get("sub_variables") or []) for settings in factor_cfg.values()
    )
    return max(1, int(fallback))


def _quick_lower_bound(raw_value: Any, derived_value: int, *, minimum: int = 0) -> int:
    """Return the smaller of the configured threshold and the smoke threshold."""
    try:
        configured = int(raw_value) if raw_value is not None else int(derived_value)
    except (TypeError, ValueError):
        configured = int(derived_value)
    return max(int(minimum), min(configured, int(derived_value)))


def _quick_portfolio_name(
    base_portfolio_name: str,
    *,
    run_date: date,
    company_limit: int,
    lookback_years: int,
) -> str:
    """Return an isolated portfolio namespace for temporary smoke runs."""
    scope = "all" if company_limit <= 0 else f"c{int(company_limit)}"
    suffix = f"_quick_{run_date.strftime('%Y%m%d')}_{scope}_y{max(1, int(lookback_years))}"
    max_base_length = max(1, 50 - len(suffix))
    trimmed_base = str(base_portfolio_name).strip()[:max_base_length]
    return f"{trimmed_base}{suffix}"


def _build_quick_cw2_config(
    *,
    cw2_cfg: Dict[str, Any],
    company_limit: int,
    lookback_years: int,
    run_date: date,
) -> tuple[Path, Dict[str, Any]]:
    """Write a temporary relaxed CW2 config for small-universe chain validation."""
    quick_cfg = copy.deepcopy(cw2_cfg)
    floor_names = _quick_floor(company_limit)
    cap_names = _quick_cap(company_limit, floor_names)
    required_sub_variables = _quick_required_sub_variable_count(quick_cfg)
    max_single_weight = max(
        float((quick_cfg.get("portfolio_construction") or {}).get("max_single_weight", 0.05)),
        min(1.0, round((1.0 / float(floor_names)) + 0.02, 4)),
    )

    pipeline_guards = dict(quick_cfg.get("pipeline_guards") or {})
    pipeline_guards["min_scoring_universe"] = floor_names
    pipeline_guards["min_investable_universe"] = floor_names
    quick_cfg["pipeline_guards"] = pipeline_guards

    preprocessing_cfg = dict(quick_cfg.get("preprocessing") or {})
    quick_min_observations = (
        _quick_lower_bound(
            preprocessing_cfg.get("min_observations"),
            floor_names,
            minimum=1,
        )
        if company_limit > 0
        else int(preprocessing_cfg.get("min_observations", 2))
    )
    preprocessing_cfg["min_observations"] = quick_min_observations
    quick_cfg["preprocessing"] = preprocessing_cfg

    investable_cfg = dict(quick_cfg.get("investable_universe") or {})
    if company_limit > 0:
        # Cross-sectional percentile cutoffs become unstable after a hard
        # universe cap, so the smoke profile keeps only the absolute floors.
        investable_cfg["market_cap_bottom_percentile"] = None
        investable_cfg["liquidity_bottom_percentile"] = None
    quick_cfg["investable_universe"] = investable_cfg

    risk_cfg = dict(quick_cfg.get("risk_overlay") or {})
    if company_limit > 0:
        # Optional percentile blacklists are useful in production, but on a
        # capped smoke-validation universe they mostly measure sample artefacts.
        risk_cfg["max_volatility_60d_percentile"] = 1.0
        risk_cfg["optional_percentile_blacklists"] = []
    quick_cfg["risk_overlay"] = risk_cfg

    quality_gates = dict(quick_cfg.get("quality_gates") or {})
    quality_gates["min_sub_score_rows"] = _quick_lower_bound(
        quality_gates.get("min_sub_score_rows"),
        floor_names * required_sub_variables,
        minimum=1,
    )
    quality_gates["min_factor_score_rows"] = _quick_lower_bound(
        quality_gates.get("min_factor_score_rows"),
        floor_names,
        minimum=1,
    )
    quality_gates["min_risk_overlay_rows"] = _quick_lower_bound(
        quality_gates.get("min_risk_overlay_rows"),
        floor_names,
        minimum=1,
    )
    quality_gates["min_portfolio_targets"] = floor_names
    quick_cfg["quality_gates"] = quality_gates

    portfolio_cfg = dict(quick_cfg.get("portfolio_construction") or {})
    base_portfolio_name = str(
        portfolio_cfg.get("portfolio_name")
        or (quick_cfg.get("backtest") or {}).get("portfolio_name")
        or "cw2_core_equity"
    )
    quick_portfolio_name = _quick_portfolio_name(
        base_portfolio_name,
        run_date=run_date,
        company_limit=company_limit,
        lookback_years=lookback_years,
    )
    portfolio_cfg["portfolio_name"] = quick_portfolio_name
    portfolio_cfg["selection_mode"] = "hybrid"
    portfolio_cfg["top_n"] = cap_names
    portfolio_cfg["hybrid_min_n"] = floor_names
    portfolio_cfg["hybrid_max_n"] = cap_names
    portfolio_cfg["min_names"] = floor_names
    portfolio_cfg["min_candidate_pool"] = floor_names
    portfolio_cfg["max_single_weight"] = max_single_weight
    quick_cfg["portfolio_construction"] = portfolio_cfg

    backtest_cfg = dict(quick_cfg.get("backtest") or {})
    backtest_cfg["portfolio_name"] = quick_portfolio_name
    backtest_cfg["lookback_years"] = max(1, int(lookback_years))
    backtest_cfg["min_eligible_universe"] = floor_names
    quick_cfg["backtest"] = backtest_cfg

    recommendation_cfg = dict(quick_cfg.get("recommendation") or {})
    recommendation_cfg["portfolio_name"] = quick_portfolio_name
    quick_cfg["recommendation"] = recommendation_cfg

    out_dir = CW2_ROOT / "outputs" / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"cw2_smoke_profile_{run_date.isoformat()}_{ts}.yaml"
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(quick_cfg, fh, sort_keys=False)

    return out_path, {
        "config_path": str(out_path),
        "lookback_years": int(backtest_cfg["lookback_years"]),
        "floor_names": floor_names,
        "cap_names": cap_names,
        "max_single_weight": max_single_weight,
        "portfolio_name": quick_portfolio_name,
        "min_observations": quick_min_observations,
        "required_sub_variables": required_sub_variables,
        "min_sub_score_rows": int(quality_gates["min_sub_score_rows"]),
        "min_factor_score_rows": int(quality_gates["min_factor_score_rows"]),
        "min_risk_overlay_rows": int(quality_gates["min_risk_overlay_rows"]),
    }


def _run_subprocess_step(
    *,
    step_name: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
) -> Dict[str, Any]:
    """Run one subprocess step and return a structured status payload."""
    logger.info("%s: start cmd=%s", step_name, cmd)
    completed = subprocess.run(cmd, cwd=str(cwd), env=env, check=False)  # nosec B603
    result = {
        "step": step_name,
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "command": cmd,
        "cwd": str(cwd),
    }
    if completed.returncode != 0:
        raise RuntimeError(f"{step_name} failed with return code {completed.returncode}")
    return result


def _init_db_cmd(args: argparse.Namespace) -> list[str]:
    """Build the command used to initialize shared PostgreSQL schema objects."""
    return [
        sys.executable,
        str((CW1_ROOT / "scripts" / "init_db.py").resolve()),
    ]


def _apply_sql_text(engine: Any, sql_text: str) -> None:
    """Execute raw SQL text against PostgreSQL using the shared DB engine."""
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()
    finally:
        raw_conn.close()


def _initialize_cw2_schema() -> Dict[str, Any]:
    """Apply the checked-in CW2 SQL schema files in the required order."""
    engine = get_db_engine()
    sql_root = CW2_ROOT / "sql"
    applied_files = []
    for filename in _CW2_SCHEMA_ORDER:
        path = sql_root / filename
        _apply_sql_text(engine, path.read_text(encoding="utf-8"))
        applied_files.append(filename)
    return {
        "status": "ok",
        "applied_files": applied_files,
    }


def _ensure_mongo_indexes(cw1_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure the MongoDB news collection has the expected serving indexes."""
    mongo_cfg = dict(cw1_cfg.get("mongo") or {})
    mongo_db = resolve_mongo_db("", mongo_cfg)
    client, coll = build_mongo_collection(
        mongo_cfg,
        _DEFAULT_MONGO_COLLECTION,
        mongo_db,
    )
    try:
        _ensure_news_indexes(coll)
    finally:
        client.close()
    return {
        "status": "ok",
        "database": mongo_db,
        "collection": _DEFAULT_MONGO_COLLECTION,
    }


def _ensure_news_indexes(coll: Collection) -> None:
    """Create the Mongo indexes required by the rebuilt news-serving layer."""
    coll.create_index(
        [("title", "text"), ("summary", "text")],
        name="idx_text_title_summary",
    )
    coll.create_index([("time_published", 1)], name="idx_time_published")
    coll.create_index([("symbols", 1)], name="idx_symbols")
    coll.create_index(
        [("symbols", 1), ("time_published", -1)],
        name="idx_symbols_time_published_desc",
    )
    coll.create_index([("published_at", 1)], name="idx_published_at")
    coll.create_index([("url", 1)], name="idx_url_unique", unique=True, sparse=True)
    coll.create_index([("last_seen_run_date", 1)], name="idx_last_seen_run_date")
    coll.create_index(
        [("last_seen_run_date", 1), ("time_published", -1)],
        name="idx_last_seen_run_date_time_published_desc",
    )


def _read_env_or_cfg(env_key: str, cfg: Dict[str, Any], cfg_key: str, default: str = "") -> str:
    """Resolve one setting from env first, then config, then a default."""
    raw = os.getenv(env_key, str(cfg.get(cfg_key, default) or default))
    return str(raw).strip()


def _ensure_minio_bucket(cw1_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure the configured MinIO bucket exists before the chain runs."""
    minio_cfg = dict(cw1_cfg.get("minio") or {})
    endpoint = _read_env_or_cfg("MINIO_ENDPOINT", minio_cfg, "endpoint")
    access_key = _read_env_or_cfg("MINIO_ACCESS_KEY", minio_cfg, "access_key")
    secret_key = _read_env_or_cfg("MINIO_SECRET_KEY", minio_cfg, "secret_key")
    bucket = _read_env_or_cfg("MINIO_BUCKET", minio_cfg, "bucket")
    secure = str(minio_cfg.get("secure", "false")).lower() in {"1", "true", "yes"}

    client = Minio(
        endpoint=endpoint.removeprefix("http://").removeprefix("https://"),
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )
    existed = bool(client.bucket_exists(bucket))
    if not existed:
        client.make_bucket(bucket)
    return {
        "status": "ok",
        "bucket": bucket,
        "bucket_preexisted": existed,
    }


def _ensure_kafka_topics(cw1_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Create the configured Kafka topics when Kafka is enabled for the run."""
    kafka_cfg = resolve_kafka_config(cw1_cfg, default_client_id="cw2_full_run")
    if not kafka_cfg.enabled:
        return {"status": "skipped", "reason": "kafka disabled"}

    topic_results = []
    failures = 0
    kafka_cmd = "/opt/bitnami/kafka/bin/kafka-topics.sh"
    container = str(os.getenv("KAFKA_CONTAINER", "kafka_cw")).strip() or "kafka_cw"
    for topic_name in sorted(set(kafka_cfg.topics.values())):
        cmd = [
            "docker",
            "exec",
            container,
            kafka_cmd,
            "--bootstrap-server",
            "localhost:9092",
            "--create",
            "--if-not-exists",
            "--topic",
            str(topic_name),
            "--partitions",
            "1",
            "--replication-factor",
            "1",
        ]
        completed = subprocess.run(  # nosec B603
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            failures += 1
        topic_results.append(
            {
                "topic": str(topic_name),
                "returncode": int(completed.returncode),
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        )

    if failures and kafka_cfg.required:
        raise RuntimeError(f"kafka topic creation failed for {failures} topic(s)")

    return {
        "status": "ok" if failures == 0 else "warning",
        "required": bool(kafka_cfg.required),
        "failures": failures,
        "topics": topic_results,
    }


def _build_cw1_upstream_cmd(
    *,
    args: argparse.Namespace,
    company_limit: int,
    backfill_years: int,
) -> list[str]:
    """Build the CW1 upstream refresh command used inside the full chain."""
    cmd = [
        sys.executable,
        str((CW1_ROOT / "Main.py").resolve()),
        "--config",
        str(Path(args.cw1_config).resolve()),
        "--run-date",
        str(args.run_date),
        "--frequency",
        str(args.frequency),
        "--backfill-years",
        str(backfill_years),
        "--company-limit",
        str(company_limit),
        "--enabled-extractors",
        str(args.enabled_extractors),
        "--index-mongo",
    ]
    return cmd


def _build_backfill_cmd(
    *,
    args: argparse.Namespace,
    company_limit: int,
    start_date: date,
    end_date: date,
    cw2_config_path: str,
    skip_existing: bool,
) -> list[str]:
    """Build the monthly snapshot backfill command for the chosen date window."""
    return [
        sys.executable,
        str((CW2_ROOT / "scripts" / "backfill_monthly_snapshots.py").resolve()),
        "--start-date",
        start_date.isoformat(),
        "--end-date",
        end_date.isoformat(),
        "--company-limit",
        str(company_limit),
        "--cw1-config",
        str(Path(args.cw1_config).resolve()),
        "--cw2-config",
        str(Path(cw2_config_path).resolve()),
        "--refresh-market-factors",
        "true",
        "--skip-existing",
        "true" if skip_existing else "false",
    ]


def _build_operate_cmd(
    *, args: argparse.Namespace, company_limit: int, cw2_config_path: str
) -> list[str]:
    """Build the ``CW2 Main.py --mode operate`` command for this run."""
    cmd = [
        sys.executable,
        str((CW2_ROOT / "Main.py").resolve()),
        "--mode",
        "operate",
        "--run-date",
        str(args.run_date),
        "--company-limit",
        str(company_limit),
        "--cw1-config",
        str(Path(args.cw1_config).resolve()),
        "--cw2-config",
        str(Path(cw2_config_path).resolve()),
        "--decision-actor",
        str(args.decision_actor),
    ]
    if args.briefing_dir:
        cmd.extend(["--briefing-dir", str(args.briefing_dir)])
    if args.auto_approve:
        cmd.append("--auto-approve")
    if args.auto_publish:
        cmd.append("--auto-publish")
    return cmd


def _execute_backtest_analysis_report(
    *,
    args: argparse.Namespace,
    run_name: str,
    cw2_config_path: str,
) -> Dict[str, Any]:
    """Run the local backtest, analysis, and report stages in-process."""
    config_override = None
    if args.transaction_cost_bps is not None:
        tc = float(args.transaction_cost_bps)
        config_override = {
            "backtest": {
                "transaction_cost_bps": tc,
                "intraday_triggers": {"transaction_cost_bps": tc},
            }
        }

    run_id = run_backtest_from_config(
        run_name=run_name,
        config_path=str(Path(cw2_config_path).resolve()),
        config_override=config_override,
    )
    analysis_result = run_analysis_from_config(
        run_id=run_id,
        config_path=str(Path(cw2_config_path).resolve()),
        robustness_run_id_25bps=(str(args.robustness_run_id) if args.robustness_run_id else None),
    )
    report_result = generate_backtest_report_from_config(
        run_id=run_id,
        config_path=str(Path(cw2_config_path).resolve()),
        report_name=(str(args.report_name) if args.report_name else None),
        output_dir=(str(args.report_output_dir) if args.report_output_dir else None),
    )
    return {
        "status": "ok",
        "run_id": run_id,
        "run_name": run_name,
        "analysis": analysis_result,
        "report": report_result,
    }


def _execute_kafka_event_audit(
    *,
    args: argparse.Namespace,
    cw2_config_path: str,
) -> Dict[str, Any]:
    """Run the Kafka audit stage and normalize its result payload."""
    audit_summary = run_kafka_event_audit_from_config(
        cw1_config_path=str(Path(args.cw1_config).resolve()),
        cw2_config_path=str(Path(cw2_config_path).resolve()),
    )
    return {"status": str(audit_summary.get("status") or "unknown"), **audit_summary}


def _is_transient_readiness_partial(readiness: Dict[str, Any]) -> bool:
    """Return whether a partial readiness result looks short-lived and retryable."""
    overall_status = str(readiness.get("overall_status") or "").lower()
    if overall_status != "partial":
        return False
    stable_core = all(
        bool(readiness.get(key))
        for key in (
            "core_sql_ready",
            "feature_pipeline_ready",
            "backtest_ready",
            "semantic_ready",
        )
    )
    if not stable_core:
        return False
    return (
        not bool(readiness.get("storage_ready"))
        or not bool(readiness.get("kafka_ready"))
        or not bool(readiness.get("kafka_event_audit_ready"))
    )


def _execute_readiness_audit(
    *,
    args: argparse.Namespace,
    cw2_config_path: str,
    max_attempts: int = _READINESS_AUDIT_MAX_ATTEMPTS,
    retry_delay_seconds: float = _READINESS_AUDIT_RETRY_DELAY_SECONDS,
) -> Dict[str, Any]:
    """Run readiness audit with a short retry window for transient storage/event lag."""
    attempts_used = 0
    last_report: Dict[str, Any] = {}
    last_readiness: Dict[str, Any] = {}
    max_attempts = max(1, int(max_attempts))

    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        last_report = run_audit_from_config(
            cw1_config_path=str(Path(args.cw1_config).resolve()),
            cw2_config_path=str(Path(cw2_config_path).resolve()),
        )
        last_readiness = dict(last_report.get("readiness") or {})
        if str(last_readiness.get("overall_status") or "").lower() == "ready":
            break
        if attempt < max_attempts and _is_transient_readiness_partial(last_readiness):
            logger.warning(
                "cw2_full_chain: readiness partial after monthly backfill; retrying attempt=%s/%s delay_seconds=%.1f readiness=%s",
                attempt,
                max_attempts,
                retry_delay_seconds,
                last_readiness,
            )
            time.sleep(float(retry_delay_seconds))
            continue
        break

    final_status = str(last_readiness.get("overall_status") or "unknown").lower()
    return {
        "status": "ok" if final_status == "ready" else "failed",
        "attempts": attempts_used,
        "readiness": last_readiness,
        "audit_report": last_report,
    }


def main() -> int:
    """Execute the full CW1 -> CW2 chain and print a JSON step summary."""
    _configure_logging()
    args = build_parser().parse_args()
    load_env_layers()

    run_date = date.fromisoformat(str(args.run_date))
    cw1_cfg = load_yaml(str(args.cw1_config))
    cw2_cfg = load_yaml(str(args.cw2_config))
    company_limit = _effective_company_limit(args.company_limit)
    backfill_years = _resolve_effective_backfill_years(args, cw1_cfg)
    effective_cw2_config_path = str(Path(args.cw2_config).resolve())
    quick_profile_summary = None
    if bool(args.quick_profile):
        quick_config_path, quick_profile_summary = _build_quick_cw2_config(
            cw2_cfg=cw2_cfg,
            company_limit=company_limit,
            lookback_years=max(1, int(args.quick_lookback_years)),
            run_date=run_date,
        )
        effective_cw2_config_path = str(quick_config_path.resolve())
        cw2_cfg = load_yaml(effective_cw2_config_path)

    snapshot_years = (
        int((cw2_cfg.get("backtest") or {}).get("lookback_years") or 1)
        if bool(args.quick_profile)
        else _resolve_snapshot_years(
            cw1_cfg=cw1_cfg,
            cw2_cfg=cw2_cfg,
            backfill_years=backfill_years,
        )
    )
    start_date, end_date = _snapshot_window(run_date, snapshot_years)
    run_name = str(args.run_name or _default_run_name(run_date))

    env = os.environ.copy()
    env["CW2_CONFIG_PATH"] = effective_cw2_config_path

    summary: Dict[str, Any] = {
        "run_date": run_date.isoformat(),
        "company_limit": company_limit,
        "backfill_years": backfill_years,
        "cw2_config_path": effective_cw2_config_path,
        "snapshot_window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "years": snapshot_years,
        },
        "steps": [],
    }
    if quick_profile_summary is not None:
        summary["smoke_profile"] = quick_profile_summary
        summary["quick_profile"] = quick_profile_summary

    summary["steps"].append(
        _run_subprocess_step(
            step_name="init_db",
            cmd=_init_db_cmd(args),
            cwd=CW1_ROOT,
            env=env,
        )
    )
    cw2_schema = _initialize_cw2_schema()
    summary["steps"].append({"step": "init_cw2_schema", **cw2_schema})

    minio_status = _ensure_minio_bucket(cw1_cfg)
    summary["steps"].append({"step": "init_minio", **minio_status})

    mongo_status = _ensure_mongo_indexes(cw1_cfg)
    summary["steps"].append({"step": "init_mongo", **mongo_status})

    kafka_status = _ensure_kafka_topics(cw1_cfg)
    summary["steps"].append({"step": "init_kafka", **kafka_status})

    summary["steps"].append(
        _run_subprocess_step(
            step_name="cw1_upstream",
            cmd=_build_cw1_upstream_cmd(
                args=args,
                company_limit=company_limit,
                backfill_years=backfill_years,
            ),
            cwd=CW1_ROOT,
            env=env,
        )
    )
    summary["steps"].append(
        _run_subprocess_step(
            step_name="cw2_monthly_backfill",
            cmd=_build_backfill_cmd(
                args=args,
                company_limit=company_limit,
                start_date=start_date,
                end_date=end_date,
                cw2_config_path=effective_cw2_config_path,
                skip_existing=not bool(args.quick_profile),
            ),
            cwd=CW2_ROOT,
            env=env,
        )
    )

    audit_result = _execute_readiness_audit(
        args=args,
        cw2_config_path=effective_cw2_config_path,
    )
    readiness = dict(audit_result.get("readiness") or {})
    summary["steps"].append(
        {
            "step": "cw2_audit",
            "status": str(audit_result.get("status") or "unknown"),
            "attempts": int(audit_result.get("attempts") or 1),
            "readiness": readiness,
        }
    )
    if str(readiness.get("overall_status", "")).lower() != "ready":
        raise RuntimeError(
            "CW2 readiness audit did not pass after upstream refresh and monthly backfill: "
            f"{readiness}"
        )

    summary["steps"].append(
        _run_subprocess_step(
            step_name="cw2_operate",
            cmd=_build_operate_cmd(
                args=args,
                company_limit=company_limit,
                cw2_config_path=effective_cw2_config_path,
            ),
            cwd=CW2_ROOT,
            env=env,
        )
    )

    backtest_package = _execute_backtest_analysis_report(
        args=args,
        run_name=run_name,
        cw2_config_path=effective_cw2_config_path,
    )
    summary["steps"].append({"step": "cw2_backtest_analysis_report", **backtest_package})
    summary["run_id"] = backtest_package["run_id"]
    summary["run_name"] = backtest_package["run_name"]
    summary["report"] = backtest_package["report"]
    kafka_event_audit = _execute_kafka_event_audit(
        args=args,
        cw2_config_path=effective_cw2_config_path,
    )
    summary["steps"].append({"step": "cw2_kafka_event_audit", **kafka_event_audit})
    summary["kafka_event_audit"] = kafka_event_audit

    print_json(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
