import json
import logging
import os
import subprocess  # nosec B404
import sys
import time
import traceback
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.utils.args_parser import ALLOWED_FREQUENCIES, build_parser
from modules.utils.env import load_dotenv_if_exists

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

logger = logging.getLogger(__name__)
_ALPHA_KEY_PLACEHOLDERS = {
    "",
    "YOUR_KEY",
    "YOUR_API_KEY_HERE",
    "ALPHA_VANTAGE_API_KEY",
    "REPLACE_WITH_YOUR_KEY",
}


@dataclass
class RunLog:
    run_id: str
    start_time_utc: str
    end_time_utc: str
    run_date: str
    frequency: str
    backfill_years: int
    company_limit: Optional[int]
    stages_ok: int
    stages_failed: int
    status: str
    error: str = ""
    notes: str = ""


@dataclass
class RunContext:
    base_dir: str
    args: Any
    cfg: Dict[str, Any]
    log_cfg: Dict[str, Any]
    run_date: str
    frequency: str
    backfill_years: int
    company_limit: Optional[int]
    enabled_extractors: List[str]
    enabled_extractors_text: str
    run_id: str
    start_time_utc: str


@dataclass
class PipelineState:
    stages_ok: int = 0
    stages_failed: int = 0
    status: str = "success"
    err: str = ""
    notes: str = ""
    error_traceback: str = ""
    loaded_rows: int = 0
    quality_report: Optional[Dict[str, Any]] = None
    provider_usage: Optional[Dict[str, int]] = None


FINANCIAL_ATOMIC_FACTORS = {
    "total_debt",
    "total_shareholder_equity",
    "book_value",
    "shares_outstanding",
    "enterprise_ebitda",
    "enterprise_revenue",
}
ALLOWED_EXTRACTORS = {
    "source_a",  # Structured data: market yfinance->AV; financial yfinance->AV with EDGAR authoritative overlap
    "source_b",  # Unstructured data: news/sentiment (AV historical + Finnhub incremental + L-M lexicon)
    "market_factors",  # Derived factors computed from source_a and source_b outputs
}


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: str) -> Dict[str, Any]:
    """Load YAML config file and return parsed mapping."""
    if not path:
        return {}
    if yaml is None:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_dotenv(path: str) -> None:
    """Backward-compatible wrapper for tests; delegates to shared env loader."""
    load_dotenv_if_exists(path)


def _sanitize_alpha_key(value: Any) -> str:
    """Normalize provider key text and reject known placeholder values."""
    cleaned = str(value or "").strip()
    if cleaned.upper() in _ALPHA_KEY_PLACEHOLDERS:
        return ""
    return cleaned


def ensure_dir(path: str) -> None:
    """Create directory path if missing."""
    os.makedirs(path, exist_ok=True)


def write_jsonl(path: str, record: Dict[str, Any]) -> None:
    """Append one JSON object line to a JSONL file."""
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def apply_env_defaults_from_config(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Use config values as env fallbacks, while keeping env as source of truth."""
    db_cfg = cfg.get("database") or {}
    minio_cfg = cfg.get("minio") or {}
    redis_cfg = cfg.get("redis") or {}
    kafka_cfg = cfg.get("kafka") or {}
    api_cfg = cfg.get("api") or {}
    legacy_api_cfg = cfg.get("alpha_vantage") or {}

    mapping = {
        "POSTGRES_HOST": db_cfg.get("host"),
        "POSTGRES_PORT": db_cfg.get("port"),
        "POSTGRES_DB": db_cfg.get("name"),
        "POSTGRES_USER": db_cfg.get("user"),
        "POSTGRES_PASSWORD": db_cfg.get("password"),
        "POSTGRES_SCHEMA": db_cfg.get("schema"),
        "MINIO_ENDPOINT": minio_cfg.get("endpoint"),
        "MINIO_ACCESS_KEY": minio_cfg.get("access_key"),
        "MINIO_SECRET_KEY": minio_cfg.get("secret_key"),
        "MINIO_BUCKET": minio_cfg.get("bucket"),
        "REDIS_HOST": redis_cfg.get("host"),
        "REDIS_PORT": redis_cfg.get("port"),
        "REDIS_DB": redis_cfg.get("db"),
        "REDIS_PASSWORD": redis_cfg.get("password"),
        "REDIS_REQUIRED": redis_cfg.get("required"),
        "KAFKA_ENABLED": kafka_cfg.get("enabled"),
        "KAFKA_REQUIRED": kafka_cfg.get("required"),
        "KAFKA_CLIENT_ID": kafka_cfg.get("client_id"),
    }
    for key, value in mapping.items():
        if os.getenv(key) in (None, "") and value not in (None, ""):
            os.environ[key] = str(value)

    bootstrap_servers = kafka_cfg.get("bootstrap_servers") or []
    if os.getenv("KAFKA_BOOTSTRAP_SERVERS") in (None, "") and bootstrap_servers:
        if isinstance(bootstrap_servers, str):
            os.environ["KAFKA_BOOTSTRAP_SERVERS"] = str(bootstrap_servers)
        else:
            os.environ["KAFKA_BOOTSTRAP_SERVERS"] = ",".join(
                str(item).strip() for item in bootstrap_servers if str(item).strip()
            )

    env_primary = _sanitize_alpha_key(os.getenv("ALPHA_VANTAGE_API_KEY"))
    env_alias = _sanitize_alpha_key(os.getenv("ALPHA_VANTAGE_KEY"))
    conf_key = _sanitize_alpha_key(
        api_cfg.get("alpha_vantage_key") or legacy_api_cfg.get("api_key")
    )

    if not env_primary and env_alias:
        os.environ["ALPHA_VANTAGE_API_KEY"] = env_alias
        env_primary = env_alias

    if not env_primary and conf_key:
        os.environ["ALPHA_VANTAGE_API_KEY"] = conf_key
        return {"alpha_vantage_key_source": "conf"}
    if env_primary:
        return {"alpha_vantage_key_source": "env"}
    return {"alpha_vantage_key_source": "missing"}


def _configure_logging(log_cfg: Dict[str, Any]) -> None:
    """Initialize root logging with configured level and format."""
    level = str(
        os.getenv("CW1_LOG_LEVEL") or log_cfg.get("level") or log_cfg.get("log_level") or "INFO"
    ).upper()
    fmt = str(log_cfg.get("format") or "%(asctime)s %(levelname)s %(name)s %(message)s")

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(getattr(logging, level, logging.INFO))
        return
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=fmt,
    )


def _append_note(notes: str, item: str) -> str:
    """Append one semicolon-delimited note item."""
    item = str(item).strip()
    if not item:
        return notes
    return item if not notes else f"{notes}; {item}"


def _summary_with_limit(items: List[Dict[str, str]], limit: int = 20) -> str:
    total = len(items)
    if total == 0:
        return json.dumps([], ensure_ascii=False)
    if total <= limit:
        return json.dumps(items, ensure_ascii=False)
    return json.dumps(
        {
            "count": total,
            "limit": limit,
            "sample": items[:limit],
            "truncated": True,
        },
        ensure_ascii=False,
    )


def _source_a_supporting_rows_exist(
    *,
    run_date: str,
    backfill_years: int,
    symbol: str,
    reusable_details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether reusable Source A outputs still exist in PostgreSQL.

    The materialization registry is filesystem-backed, so it can survive a DB reset.
    A registry hit alone is therefore insufficient to skip Source A. We require
    representative pricing rows in ``factor_observations`` and, when the original
    run emitted them, financial rows in ``financial_observations``.
    """

    details = reusable_details or {}
    expect_price_rows = bool(
        int(details.get("curated_rows") or 0) > 0 or int(details.get("loaded_rows") or 0) > 0
    )
    expect_financial_rows = int(details.get("financial_rows") or 0) > 0
    if not expect_price_rows and not expect_financial_rows:
        return False

    try:
        from sqlalchemy import text

        from modules.db.db_connection import get_db_engine
        from modules.input.extract_source_a import _rolling_window_start_date

        start_date = _rolling_window_start_date(run_date, backfill_years)
        query = text("""
            SELECT
                EXISTS (
                    SELECT 1
                    FROM systematic_equity.factor_observations
                    WHERE symbol = :symbol
                      AND observation_date BETWEEN :start_date AND :run_date
                      AND factor_name IN (
                          'adjusted_close_price',
                          'open_price',
                          'high_price',
                          'low_price',
                          'daily_volume'
                      )
                ) AS has_price_rows,
                EXISTS (
                    SELECT 1
                    FROM systematic_equity.financial_observations
                    WHERE symbol = :symbol
                      AND COALESCE(publish_date, report_date) BETWEEN :start_date AND :run_date
                ) AS has_financial_rows
            """)
        with get_db_engine().begin() as conn:
            row = (
                conn.execute(
                    query,
                    {
                        "symbol": symbol,
                        "start_date": start_date,
                        "run_date": run_date,
                    },
                )
                .mappings()
                .one()
            )
    except Exception as exc:
        logger.info(
            "source_a support_check_failed symbol=%s run_date=%s reason=%r",
            symbol,
            run_date,
            exc,
        )
        return False

    has_price_rows = bool(row.get("has_price_rows"))
    has_financial_rows = bool(row.get("has_financial_rows"))
    if not expect_price_rows:
        has_price_rows = True
    return has_price_rows and (not expect_financial_rows or has_financial_rows)


def _source_b_supporting_rows_exist(
    *,
    symbol: str,
    month_start: date,
    fetch_end: date,
    reusable_details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether reusable Source B atomics still exist in PostgreSQL.

    The materialization registry is filesystem-backed, so registry hits can
    survive a database reset. For symbol-month windows that previously emitted
    Source B atomics, require representative ``factor_observations`` rows to
    still exist before allowing the extractor to skip.
    """

    details = reusable_details or {}
    expect_rows = bool(
        int(details.get("loaded_rows") or 0) > 0 or int(details.get("articles") or 0) > 0
    )
    if not expect_rows:
        return True

    try:
        from sqlalchemy import text

        from modules.db.db_connection import get_db_engine

        query = text("""
            SELECT EXISTS (
                SELECT 1
                FROM systematic_equity.factor_observations
                WHERE symbol = :symbol
                  AND observation_date BETWEEN :month_start AND :fetch_end
                  AND factor_name IN ('news_sentiment_daily', 'news_article_count_daily')
            ) AS has_source_b_rows
        """)
        with get_db_engine().begin() as conn:
            row = (
                conn.execute(
                    query,
                    {
                        "symbol": symbol,
                        "month_start": month_start,
                        "fetch_end": fetch_end,
                    },
                )
                .mappings()
                .one()
            )
    except Exception as exc:
        logger.info(
            "source_b support_check_failed symbol=%s month_start=%s reason=%r",
            symbol,
            month_start,
            exc,
        )
        return False

    return bool(row.get("has_source_b_rows"))


def _log_stage_event(
    *,
    run_id: str,
    stage: str,
    status: str,
    rows_in: Optional[int] = None,
    rows_out: Optional[int] = None,
    elapsed_ms: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit normalized stage telemetry for pipeline observability."""
    logger.info(
        "stage_event run_id=%s stage=%s status=%s rows_in=%s rows_out=%s elapsed_ms=%s",
        run_id,
        stage,
        status,
        rows_in if rows_in is not None else -1,
        rows_out if rows_out is not None else -1,
        elapsed_ms if elapsed_ms is not None else -1,
    )
    try:
        from modules.output.audit import write_pipeline_stage_event

        write_pipeline_stage_event(
            run_id=run_id,
            stage_name=stage,
            status=status,
            rows_in=rows_in,
            rows_out=rows_out,
            elapsed_ms=elapsed_ms,
            details=details or {},
        )
    except Exception:
        logger.debug(
            "stage_event_db_write_skipped run_id=%s stage=%s",
            run_id,
            stage,
            exc_info=True,
        )


def _write_dataset_refresh_event(
    *,
    run_id: str,
    run_date: str,
    dataset_name: str,
    stage_name: str,
    status: str,
    rows_written: int = 0,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort append-only dataset refresh evidence."""
    try:
        from modules.output.audit import write_dataset_refresh_event

        write_dataset_refresh_event(
            run_id=run_id,
            run_date=run_date,
            dataset_name=dataset_name,
            stage_name=stage_name,
            status=status,
            rows_written=rows_written,
            details=details or {},
        )
    except Exception:
        logger.debug(
            "dataset_refresh_event_db_write_skipped run_id=%s dataset=%s stage=%s",
            run_id,
            dataset_name,
            stage_name,
            exc_info=True,
        )


def _resolve_backfill_years(cli_value: Optional[int], pipeline_cfg: Dict[str, Any]) -> int:
    """Resolve backfill window from CLI/env/config with validation."""
    env_value = os.getenv("PIPELINE_BACKFILL_YEARS")
    raw = (
        cli_value
        if cli_value is not None
        else (env_value if env_value not in (None, "") else pipeline_cfg.get("backfill_years", 5))
    )
    try:
        years = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid backfill_years={raw!r}. Expected integer >= 0.") from exc
    if years < 0:
        raise ValueError(f"Invalid backfill_years={years}. Expected integer >= 0.")
    return years


def _resolve_company_limit(cli_value: Optional[int], pipeline_cfg: Dict[str, Any]) -> Optional[int]:
    """Resolve company limit from CLI/env/config with validation."""
    env_value = os.getenv("PIPELINE_COMPANY_LIMIT")
    raw = (
        cli_value
        if cli_value is not None
        else (env_value if env_value not in (None, "") else pipeline_cfg.get("company_limit", 20))
    )
    if raw is None:
        return None
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid company_limit={raw!r}. Expected integer or null.") from exc
    if limit <= 0:
        return None
    return limit


def _resolve_enabled_extractors(
    cli_value: Optional[List[str]], pipeline_cfg: Dict[str, Any]
) -> List[str]:
    """Resolve active extractor list and enforce allowed names."""
    configured = pipeline_cfg.get("enabled_extractors", ["source_a", "source_b"])
    env_value = os.getenv("PIPELINE_ENABLED_EXTRACTORS")
    if cli_value is not None:
        source = cli_value
    elif env_value not in (None, ""):
        source = [x.strip() for x in str(env_value).split(",")]
    elif isinstance(configured, list):
        source = configured
    elif isinstance(configured, str):
        source = [x.strip() for x in configured.split(",")]
    else:
        source = ["source_a", "source_b"]

    out: List[str] = []
    seen = set()
    for raw in source:
        token = str(raw).strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)

    if not out:
        out = ["source_a", "source_b"]

    invalid = sorted(x for x in out if x not in ALLOWED_EXTRACTORS)
    if invalid:
        raise ValueError(
            f"Invalid enabled_extractors={invalid}. " f"Allowed: {sorted(ALLOWED_EXTRACTORS)}."
        )
    return out


def _resolve_frequency(cli_value: Optional[str], pipeline_cfg: Dict[str, Any]) -> str:
    """Resolve run frequency from CLI/env/config with validation."""
    env_value = os.getenv("PIPELINE_FREQUENCY")
    raw = (
        cli_value
        if cli_value not in (None, "")
        else (env_value if env_value not in (None, "") else pipeline_cfg.get("frequency", "daily"))
    )
    freq = str(raw).strip().lower()
    if freq not in ALLOWED_FREQUENCIES:
        raise ValueError(
            f"Invalid frequency={raw!r}. Expected one of {sorted(ALLOWED_FREQUENCIES)}."
        )
    return freq


def get_window(run_date: str, frequency: str) -> tuple[str, str]:
    """Return [start_date, end_date] for the requested scheduling frequency."""
    end = datetime.strptime(run_date, "%Y-%m-%d").date()

    if frequency == "daily":
        start = end
    elif frequency == "weekly":
        start = end - timedelta(days=6)
    elif frequency == "monthly":
        start = end.replace(day=1)
    elif frequency == "quarterly":
        quarter_start_month = ((end.month - 1) // 3) * 3 + 1
        start = date(end.year, quarter_start_month, 1)
    elif frequency == "annual":
        start = date(end.year, 1, 1)
    else:
        raise ValueError(f"Unsupported frequency: {frequency}")

    return start.isoformat(), end.isoformat()


def collect_raw_records(
    symbols: List[str],
    run_date: str,
    frequency: str,
    backfill_years: int,
    enabled_extractors: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
    source_a_failed_symbols_out: Optional[List[Dict[str, str]]] = None,
    extractor_errors_out: Optional[List[Dict[str, str]]] = None,
    source_b_failed_months_out: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Merge records from the currently integrated source modules.

    Parameters:
    source_a_failed_symbols_out: optional mutable list used to collect
    per-symbol Source A failures.
    extractor_errors_out: optional mutable list used to collect extractor-level
    exceptions.
    source_b_failed_months_out: optional mutable list used to collect Source B
    per-(symbol, month) failures.

    In CI/unit tests, set env var `CW1_TEST_MODE=1` to bypass external extractors.
    """
    if os.getenv("CW1_TEST_MODE") == "1":
        out: List[Dict[str, Any]] = []
        for symbol in symbols:
            out.append(
                {
                    "symbol": symbol,
                    "observation_date": run_date,
                    "factor_name": "test_factor",
                    "factor_value": 1.0,
                    "source": "yfinance",
                    "metric_frequency": frequency,
                    "source_report_date": run_date,
                }
            )
        return out

    selected = enabled_extractors or ["source_a", "source_b"]
    normalized_selected = {str(x).strip().lower() for x in selected}
    records: List[Dict[str, Any]] = []

    # Lazy imports keep local test/dev fast and avoid heavy optional dependencies.
    if "source_a" in normalized_selected:
        try:
            from modules.input.extract_source_a import extract_source_a

            records.extend(
                extract_source_a(
                    symbols,
                    run_date,
                    backfill_years,
                    frequency,
                    config=config,
                    failed_symbols=source_a_failed_symbols_out,
                )
            )
        except Exception as exc:
            err = f"{exc!r}"
            logger.exception(
                "extractor_failed run_date=%s extractor=source_a error=%s", run_date, err
            )
            if extractor_errors_out is not None:
                extractor_errors_out.append({"extractor": "source_a", "error": err})

    if "source_b" in normalized_selected:
        try:
            from modules.input.extract_source_b import extract_source_b

            records.extend(
                extract_source_b(
                    symbols,
                    run_date,
                    backfill_years,
                    frequency,
                    config=config,
                    failed_months_out=source_b_failed_months_out,
                )
            )
        except Exception as exc:
            err = f"{exc!r}"
            logger.exception(
                "extractor_failed run_date=%s extractor=source_b error=%s", run_date, err
            )
            if extractor_errors_out is not None:
                extractor_errors_out.append({"extractor": "source_b", "error": err})

    return records


def summarize_provider_usage(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Summarize provider usage by symbol based on total_debt marker rows."""
    symbol_provider: Dict[str, str] = {}
    for rec in records:
        metric_name = str(rec.get("metric_name") or rec.get("factor_name") or "").strip().lower()
        if metric_name != "total_debt":
            continue
        symbol = str(rec.get("symbol") or "").strip()
        source = str(rec.get("source") or "").strip().lower()
        if symbol and source:
            symbol_provider[symbol] = source

    counts: Dict[str, int] = {}
    for provider in symbol_provider.values():
        counts[provider] = counts.get(provider, 0) + 1
    return counts


def _merge_stats(total: Dict[str, int], partial: Dict[str, int]) -> None:
    """Add one stats mapping into an aggregate stats mapping in place."""
    for key, value in (partial or {}).items():
        total[key] = int(total.get(key, 0)) + int(value)


def _plan_hybrid_work_units(
    symbols: List[str],
    *,
    enabled_extractors: List[str],
    run_date: str,
    backfill_years: int,
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build deterministic work units for hybrid orchestration."""
    units: List[Dict[str, Any]] = []
    enabled = {str(x).strip().lower() for x in enabled_extractors}

    if "source_a" in enabled:
        for symbol in symbols:
            units.append(
                {
                    "unit_id": f"source_a:{symbol}",
                    "extractor": "source_a",
                    "symbol": symbol,
                }
            )

    if "source_b" in enabled:
        from modules.input.extract_source_b import _filter_symbols_for_source_b, _month_windows

        source_b_symbols = _filter_symbols_for_source_b(symbols, config)
        windows = _month_windows(run_date, backfill_years)
        for symbol in source_b_symbols:
            for month_start, fetch_end in windows:
                units.append(
                    {
                        "unit_id": f"source_b:{symbol}:{month_start.isoformat()}",
                        "extractor": "source_b",
                        "symbol": symbol,
                        "month_start": month_start.isoformat(),
                        "fetch_end": fetch_end.isoformat(),
                    }
                )

    return units


def _persist_atomic_unit_records(
    *,
    raw_records: List[Dict[str, Any]],
    dry_run: bool,
    normalize_records_fn: Any,
    normalize_financial_records_fn: Any,
    load_curated_fn: Any,
    load_financial_observations_fn: Any,
    quality_accumulator: Any,
) -> tuple[int, int, int, Dict[str, int], Dict[str, int], Dict[str, Any]]:
    """Normalize and persist one unit's atomic records immediately."""
    from modules.output.quality import run_quality_checks

    financial_atomic_raw, curated_raw = split_atomic_financial_records(raw_records)
    curated = normalize_records_fn(curated_raw)
    quality_accumulator.update(curated)
    unit_quality_report = run_quality_checks(curated)

    curated_stats: Dict[str, int] = {}
    curated_rows = int(load_curated_fn(curated, dry_run=dry_run, stats_out=curated_stats))

    financial_normalized = normalize_financial_records_fn(financial_atomic_raw)
    financial_stats: Dict[str, int] = {}
    financial_rows = int(
        load_financial_observations_fn(
            financial_normalized,
            dry_run=dry_run,
            stats_out=financial_stats,
        )
    )

    return (
        int(len(curated)),
        int(len(financial_normalized)),
        curated_rows + financial_rows,
        curated_stats,
        financial_stats,
        unit_quality_report,
    )


def split_atomic_financial_records(
    records: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split raw records into financial atomic rows and remaining curated rows."""
    financial: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []
    for rec in records:
        metric_name = str(rec.get("metric_name") or rec.get("factor_name") or "").strip().lower()
        if metric_name in FINANCIAL_ATOMIC_FACTORS and rec.get("source") != "factor_transform":
            financial.append(rec)
        else:
            remaining.append(rec)
    return financial, remaining


def scheduling_stub(frequency: str) -> str:
    """Validate scheduling frequency and return stage note text."""
    if frequency not in ALLOWED_FREQUENCIES:
        raise ValueError(f"Unsupported frequency: {frequency}")
    return f"Scheduling stub configured for: {frequency}"


def parse_args():
    """Parse CLI arguments for the main pipeline entrypoint."""
    return build_parser().parse_args()


def resolve_paths(base_dir: str, config_path: str) -> str:
    """Resolve config path against project base directory."""
    if os.path.isabs(config_path):
        return config_path
    return os.path.join(base_dir, config_path)


def resolve_runtime(base_dir: str, args: Any) -> Optional[RunContext]:
    """Build validated runtime context from CLI, env, and config."""
    project_root = Path(__file__).resolve().parent
    load_dotenv_if_exists(project_root / ".env")
    cfg_path = resolve_paths(base_dir, args.config)
    cfg = load_yaml(cfg_path)
    env_defaults_status = apply_env_defaults_from_config(cfg)

    pipeline_cfg = cfg.get("pipeline") or {}
    log_cfg = cfg.get("logging") or {}
    _configure_logging(log_cfg)
    logger.info(
        "alpha_vantage_key_resolution source=%s",
        env_defaults_status["alpha_vantage_key_source"],
    )
    try:
        enabled_extractors = _resolve_enabled_extractors(args.enabled_extractors, pipeline_cfg)
    except ValueError as exc:
        logger.error("config_error field=enabled_extractors message=%s", str(exc))
        return None

    try:
        frequency = _resolve_frequency(args.frequency, pipeline_cfg)
    except ValueError as exc:
        logger.error("config_error field=frequency message=%s", str(exc))
        return None

    try:
        backfill_years = _resolve_backfill_years(args.backfill_years, pipeline_cfg)
    except ValueError as exc:
        logger.error("config_error field=backfill_years message=%s", str(exc))
        return None
    try:
        company_limit = _resolve_company_limit(args.company_limit, pipeline_cfg)
    except ValueError as exc:
        logger.error("config_error field=company_limit message=%s", str(exc))
        return None
    logger.info(
        "config_resolved frequency=%s backfill_years=%s company_limit=%s",
        frequency,
        backfill_years,
        "None (unlimited)" if company_limit is None else str(company_limit),
    )

    return RunContext(
        base_dir=base_dir,
        args=args,
        cfg=cfg,
        log_cfg=log_cfg,
        run_date=str(args.run_date),
        frequency=frequency,
        backfill_years=backfill_years,
        company_limit=company_limit,
        enabled_extractors=enabled_extractors,
        enabled_extractors_text=",".join(enabled_extractors),
        run_id=str(uuid.uuid4()),
        start_time_utc=utc_now_iso(),
    )


def run_scheduling_stage(ctx: RunContext, state: PipelineState) -> None:
    """Execute scheduling/window stage and update pipeline state."""
    t0 = time.monotonic()
    try:
        state.notes = scheduling_stub(ctx.frequency)
        window_start, window_end = get_window(ctx.args.run_date, ctx.frequency)
        state.notes = f"{state.notes}; window_start={window_start}; window_end={window_end}"
        logger.info(
            "stage_ok run_id=%s stage=scheduling frequency=%s window_start=%s window_end=%s",
            ctx.run_id,
            ctx.frequency,
            window_start,
            window_end,
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="scheduling",
            status="ok",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as e:
        state.status = "failed"
        state.err = f"scheduling_stub_error: {repr(e)}"
        logger.exception("stage_failed run_id=%s stage=scheduling error=%s", ctx.run_id, state.err)
        state.stages_failed += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="scheduling",
            status="failed",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )


def write_audit_start_stage(ctx: RunContext, state: PipelineState) -> None:
    """Persist run-start audit and bootstrap metadata catalog."""
    # Primary audit sink: PostgreSQL systematic_equity.pipeline_runs
    # Secondary audit sink: local JSONL (kept for developer convenience).
    try:
        from modules.output.audit import write_pipeline_run_start

        write_pipeline_run_start(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            started_at=ctx.start_time_utc,
            frequency=ctx.frequency,
            backfill_years=int(ctx.backfill_years),
            company_limit=ctx.company_limit,
            enabled_extractors=ctx.enabled_extractors_text,
            notes=state.notes,
        )
    except Exception as audit_exc:
        logger.warning(
            "audit_start_warning run_id=%s warning=%r",
            ctx.run_id,
            audit_exc,
            exc_info=True,
        )
    try:
        from modules.output.metadata import bootstrap_metadata_catalog

        bootstrap_metadata_catalog()
    except Exception as metadata_exc:
        logger.warning(
            "metadata_bootstrap_warning run_id=%s warning=%r",
            ctx.run_id,
            metadata_exc,
            exc_info=True,
        )


def run_pipeline_stage(ctx: RunContext, state: PipelineState) -> None:
    """Run extract/normalize/quality/load/transform stages."""
    if state.status != "success":
        return
    try:
        # Lazy imports so unit tests can import Main without DB drivers installed.
        from modules.db.universe import get_company_universe
        from modules.input.extract_source_a import extract_source_a
        from modules.input.extract_source_b import (
            _filter_symbols_for_source_b,
            _month_windows,
            _source_b_supporting_objects_exist,
            extract_source_b_window,
        )
        from modules.output import (
            load_curated,
            load_financial_observations,
            normalize_financial_records,
            normalize_records,
        )
        from modules.output.manifest import (
            MaterializationRegistry,
            RunManifestTracker,
            atomic_config_identity,
            source_a_materialization_key,
            source_b_materialization_key,
        )
        from modules.output.metadata import write_quality_snapshot, write_source_coverage_audit
        from modules.output.quality import QualityAccumulator
        from modules.transform import build_and_load_cw2_features, build_and_load_final_factors
        from modules.utils.source_coverage import (
            finalize_source_coverage_contract,
            initialize_source_coverage_contract,
            mark_source_a_result,
            mark_source_b_window_result,
            summarize_source_coverage_counts,
        )

        t0 = time.monotonic()
        universe_cfg = ctx.cfg.get("universe") or {}
        country_allowlist = universe_cfg.get("country_allowlist")
        universe = get_company_universe(
            ctx.company_limit,
            country_allowlist=country_allowlist,
            as_of_date=ctx.run_date,
        )
        symbols_preview = universe[:20]
        logger.info(
            "stage_ok run_id=%s stage=universe symbols_count=%s symbols_list=%s%s",
            ctx.run_id,
            len(universe),
            symbols_preview,
            " ...(truncated)" if len(universe) > len(symbols_preview) else "",
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="universe",
            status="ok",
            rows_out=len(universe),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        t0 = time.monotonic()
        extractor_errors: List[Dict[str, str]] = []
        source_a_failed_symbols: List[Dict[str, str]] = []
        source_b_failed_months: List[Dict[str, str]] = []
        provider_usage_counter: Counter[str] = Counter()
        quality_accumulator = QualityAccumulator()
        curated_load_stats_total: Dict[str, int] = {}
        financial_load_stats_total: Dict[str, int] = {}
        atomic_loaded_rows = 0
        raw_record_count = 0
        reused_unit_count = 0
        reused_loaded_rows = 0

        planned_units = _plan_hybrid_work_units(
            universe,
            enabled_extractors=ctx.enabled_extractors,
            run_date=ctx.args.run_date,
            backfill_years=ctx.backfill_years,
            config=ctx.cfg,
        )
        manifest = RunManifestTracker(
            base_dir=ctx.base_dir,
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            frequency=ctx.frequency,
            backfill_years=ctx.backfill_years,
            company_limit=ctx.company_limit,
            enabled_extractors=ctx.enabled_extractors,
            universe=universe,
            planned_units=planned_units,
        )
        materialization_registry = MaterializationRegistry(base_dir=ctx.base_dir)
        source_a_config_id = atomic_config_identity(ctx.cfg, extractor="source_a")
        source_b_config_id = atomic_config_identity(ctx.cfg, extractor="source_b")
        manifest_summary = manifest.summary()
        state.notes = _append_note(
            state.notes, f"manifest_plan_path={manifest_summary['plan_path']}"
        )
        state.notes = _append_note(
            state.notes, f"manifest_state_path={manifest_summary['state_path']}"
        )
        state.notes = _append_note(
            state.notes, f"manifest_events_path={manifest_summary['events_path']}"
        )
        source_b_windows = (
            _month_windows(ctx.args.run_date, ctx.backfill_years)
            if "source_b" in {str(x).strip().lower() for x in ctx.enabled_extractors}
            else []
        )
        source_coverage_tracker = initialize_source_coverage_contract(
            universe=universe,
            config=ctx.cfg,
            enabled_extractors=ctx.enabled_extractors,
            source_b_expected_windows=len(source_b_windows),
        )

        if "source_a" in {str(x).strip().lower() for x in ctx.enabled_extractors}:
            for idx, symbol in enumerate(universe, start=1):
                unit_id = f"source_a:{symbol}"
                unit_failed: List[Dict[str, str]] = []
                materialization_key = source_a_materialization_key(
                    symbol, ctx.args.run_date, ctx.backfill_years
                )
                reusable = (
                    None
                    if ctx.args.dry_run
                    else materialization_registry.get_reusable(
                        materialization_key,
                        config_identity=source_a_config_id,
                    )
                )
                reusable_details = (reusable or {}).get("details") or {}
                support_rows_ready = bool(
                    reusable
                    and _source_a_supporting_rows_exist(
                        run_date=ctx.args.run_date,
                        backfill_years=ctx.backfill_years,
                        symbol=symbol,
                        reusable_details=reusable_details,
                    )
                )
                if reusable and support_rows_ready:
                    reused_unit_count += 1
                    reused_loaded_rows += int(reusable_details.get("loaded_rows") or 0)
                    quality_accumulator.update_report(reusable_details.get("quality_report") or {})
                    mark_source_a_result(
                        source_coverage_tracker,
                        symbol,
                        outcome="reused",
                        raw_records=int(reusable_details.get("raw_records") or 0),
                        loaded_rows=int(reusable_details.get("loaded_rows") or 0),
                    )
                    manifest.mark_unit(
                        unit_id,
                        "skipped",
                        details={
                            "symbol": symbol,
                            "reason": "atomic_materialization_reused",
                            "materialization_key": materialization_key,
                            "source_run_id": reusable.get("run_id"),
                        },
                    )
                    continue
                if reusable and not support_rows_ready:
                    logger.info(
                        "source_a materialization_replay_required symbol=%s "
                        "reason=missing_supporting_db_rows",
                        symbol,
                    )
                try:
                    unit_raw = extract_source_a(
                        [symbol],
                        ctx.args.run_date,
                        ctx.backfill_years,
                        "daily",
                        config=ctx.cfg,
                        failed_symbols=unit_failed,
                    )
                    if unit_failed:
                        source_a_failed_symbols.extend(unit_failed)
                        mark_source_a_result(
                            source_coverage_tracker,
                            symbol,
                            outcome="failed",
                            reason=str(unit_failed[0].get("reason") or ""),
                        )
                        manifest.mark_unit(unit_id, "failed", details=unit_failed[0])
                        continue
                    if not unit_raw:
                        mark_source_a_result(
                            source_coverage_tracker,
                            symbol,
                            outcome="skipped",
                            reason="source_a_no_data_returned",
                        )
                        manifest.mark_unit(
                            unit_id,
                            "skipped",
                            details={"symbol": symbol, "reason": "source_a_no_data_returned"},
                        )
                        continue

                    raw_record_count += len(unit_raw)
                    provider_usage_counter.update(summarize_provider_usage(unit_raw))
                    (
                        curated_count,
                        financial_count,
                        unit_loaded_rows,
                        curated_stats,
                        financial_stats,
                        unit_quality_report,
                    ) = _persist_atomic_unit_records(
                        raw_records=unit_raw,
                        dry_run=bool(ctx.args.dry_run),
                        normalize_records_fn=normalize_records,
                        normalize_financial_records_fn=normalize_financial_records,
                        load_curated_fn=load_curated,
                        load_financial_observations_fn=load_financial_observations,
                        quality_accumulator=quality_accumulator,
                    )
                    atomic_loaded_rows += unit_loaded_rows
                    _merge_stats(curated_load_stats_total, curated_stats)
                    _merge_stats(financial_load_stats_total, financial_stats)
                    mark_source_a_result(
                        source_coverage_tracker,
                        symbol,
                        outcome="success",
                        raw_records=len(unit_raw),
                        loaded_rows=unit_loaded_rows,
                    )
                    manifest.mark_unit(
                        unit_id,
                        "success",
                        details={
                            "symbol": symbol,
                            "raw_records": len(unit_raw),
                            "curated_rows": curated_count,
                            "financial_rows": financial_count,
                            "loaded_rows": unit_loaded_rows,
                        },
                    )
                    if not ctx.args.dry_run:
                        materialization_registry.record_success(
                            materialization_key,
                            run_id=ctx.run_id,
                            unit_id=unit_id,
                            extractor="source_a",
                            config_identity=source_a_config_id,
                            details={
                                "symbol": symbol,
                                "raw_records": len(unit_raw),
                                "curated_rows": curated_count,
                                "financial_rows": financial_count,
                                "loaded_rows": unit_loaded_rows,
                                "quality_report": unit_quality_report,
                            },
                        )
                except Exception as exc:
                    err = f"{exc!r}"
                    extractor_errors.append(
                        {"extractor": "source_a", "symbol": symbol, "error": err}
                    )
                    source_a_failed_symbols.append({"symbol": symbol, "reason": err})
                    mark_source_a_result(
                        source_coverage_tracker,
                        symbol,
                        outcome="failed",
                        reason=err,
                    )
                    manifest.mark_unit(
                        unit_id,
                        "failed",
                        details={"symbol": symbol, "reason": err},
                    )

                if idx % 25 == 0:
                    logger.info(
                        "unit_progress run_id=%s extractor=source_a completed=%s/%s loaded_rows=%s",
                        ctx.run_id,
                        idx,
                        len(universe),
                        atomic_loaded_rows,
                    )

            # ----------------------------------------------------------------
            # EDGAR XBRL enrichment — filing-based publish_date authority plus
            # authoritative overwrite on mapped core financial atomics.
            # Source A provider order remains yfinance primary, Alpha Vantage
            # gap-fill, then EDGAR authoritative on overlapping SEC-mapped metrics.
            # ----------------------------------------------------------------
            t0_edgar = time.monotonic()
            try:
                from datetime import date as _date

                from modules.extract.edgar_xbrl import run_edgar_extraction
                from modules.input.extract_source_a import (
                    enrich_source_a_raw_with_edgar_publish_dates,
                )

                as_of = _date.fromisoformat(ctx.args.run_date)
                edgar_records = run_edgar_extraction(
                    universe,
                    backfill_years=ctx.backfill_years,
                    as_of=as_of,
                )
                financial_normalized = normalize_financial_records(edgar_records)
                edgar_stats: Dict[str, int] = {}
                edgar_rows = int(
                    load_financial_observations(
                        financial_normalized,
                        dry_run=bool(ctx.args.dry_run),
                        stats_out=edgar_stats,
                    )
                )
                _merge_stats(financial_load_stats_total, edgar_stats)
                atomic_loaded_rows += edgar_rows
                state.loaded_rows += edgar_rows
                logger.info(
                    "stage_ok run_id=%s stage=edgar_xbrl rows=%s stats=%s",
                    ctx.run_id,
                    edgar_rows,
                    edgar_stats,
                )
                try:
                    raw_enrichment_stats = enrich_source_a_raw_with_edgar_publish_dates(
                        ctx.cfg,
                        ctx.args.run_date,
                        edgar_records,
                    )
                    logger.info(
                        "stage_ok run_id=%s stage=edgar_raw_enrichment stats=%s",
                        ctx.run_id,
                        raw_enrichment_stats,
                    )
                except Exception as raw_exc:
                    logger.warning(
                        "stage_warn run_id=%s stage=edgar_raw_enrichment error=%r",
                        ctx.run_id,
                        raw_exc,
                    )
                state.stages_ok += 1
                _log_stage_event(
                    run_id=ctx.run_id,
                    stage="edgar_xbrl",
                    status="ok",
                    rows_in=len(universe),
                    rows_out=edgar_rows,
                    elapsed_ms=int((time.monotonic() - t0_edgar) * 1000),
                )
                _write_dataset_refresh_event(
                    run_id=ctx.run_id,
                    run_date=ctx.args.run_date,
                    dataset_name="financial_observations",
                    stage_name="edgar_xbrl",
                    status="ok",
                    rows_written=edgar_rows,
                    details=edgar_stats,
                )
            except Exception as exc:
                err = f"{exc!r}"
                logger.exception(
                    "stage_failed run_id=%s stage=edgar_xbrl error=%s", ctx.run_id, err
                )
                extractor_errors.append({"extractor": "edgar_xbrl", "error": err})
                state.stages_failed += 1
                state.notes = _append_note(state.notes, f"edgar_xbrl_error={err[:200]}")
                _log_stage_event(
                    run_id=ctx.run_id,
                    stage="edgar_xbrl",
                    status="failed",
                    elapsed_ms=int((time.monotonic() - t0_edgar) * 1000),
                    details={"error": err},
                )
                _write_dataset_refresh_event(
                    run_id=ctx.run_id,
                    run_date=ctx.args.run_date,
                    dataset_name="financial_observations",
                    stage_name="edgar_xbrl",
                    status="failed",
                    rows_written=0,
                    details={"error": err},
                )

        # ----------------------------------------------------------------
        # Stage: source_b — Unstructured data: news + L-M sentiment
        # Sources: AV (historical, before cutoff) + Finnhub (incremental, after cutoff)
        # Incremental: per-symbol per-month materialization registry tracks
        # which (symbol, month) units are already processed so daily runs
        # only fetch the new window, not the full history again.
        # ----------------------------------------------------------------
        if "source_b" in {str(x).strip().lower() for x in ctx.enabled_extractors}:
            from modules.input.extract_source_b import build_source_b_kafka_payloads

            source_b_symbols = _filter_symbols_for_source_b(universe, ctx.cfg)
            from modules.utils.kafka import publish_json_events

            for idx, symbol in enumerate(source_b_symbols, start=1):
                for month_start, fetch_end in source_b_windows:
                    month_key = month_start.isoformat()
                    unit_id = f"source_b:{symbol}:{month_key}"
                    materialization_key = source_b_materialization_key(
                        symbol, month_key, fetch_end.isoformat()
                    )
                    reusable = (
                        None
                        if ctx.args.dry_run
                        else materialization_registry.get_reusable(
                            materialization_key,
                            config_identity=source_b_config_id,
                        )
                    )
                    reusable_details = (reusable or {}).get("details") or {}
                    support_objects_ready = bool(
                        reusable
                        and _source_b_supporting_objects_exist(
                            ctx.cfg,
                            symbol=symbol,
                            run_date=ctx.args.run_date,
                            month_start=month_start,
                        )
                    )
                    support_rows_ready = bool(
                        reusable
                        and _source_b_supporting_rows_exist(
                            symbol=symbol,
                            month_start=month_start,
                            fetch_end=fetch_end,
                            reusable_details=reusable_details,
                        )
                    )
                    if reusable and support_objects_ready and support_rows_ready:
                        reused_unit_count += 1
                        reused_loaded_rows += int(reusable_details.get("loaded_rows") or 0)
                        mark_source_b_window_result(
                            source_coverage_tracker,
                            symbol,
                            outcome="reused",
                            article_count=int(reusable_details.get("articles") or 0),
                            loaded_rows=int(reusable_details.get("loaded_rows") or 0),
                        )
                        manifest.mark_unit(
                            unit_id,
                            "skipped",
                            details={
                                "symbol": symbol,
                                "month_start": month_key,
                                "reason": "atomic_materialization_reused",
                                "materialization_key": reusable.get("materialization_key", ""),
                                "source_run_id": reusable.get("run_id"),
                            },
                        )
                        continue
                    if reusable and not support_objects_ready:
                        logger.info(
                            "source_b materialization_replay_required symbol=%s month_start=%s "
                            "reason=missing_supporting_minio_objects",
                            symbol,
                            month_key,
                        )
                    if reusable and support_objects_ready and not support_rows_ready:
                        logger.info(
                            "source_b materialization_replay_required symbol=%s month_start=%s "
                            "reason=missing_supporting_db_rows",
                            symbol,
                            month_key,
                        )

                    try:
                        window_result = extract_source_b_window(
                            symbol=symbol,
                            run_date=ctx.args.run_date,
                            month_start=month_start,
                            fetch_end=fetch_end,
                            backfill_years=ctx.backfill_years,
                            frequency="daily",
                            config=ctx.cfg,
                            force_replay=bool(reusable and not support_objects_ready),
                        )
                        sentiment_records = list(window_result.get("records") or [])
                        article_count = int(window_result.get("article_count") or 0)
                        sentiment_normalized = normalize_records(sentiment_records)
                        sentiment_stats: Dict[str, int] = {}
                        unit_loaded_rows = int(
                            load_curated(
                                sentiment_normalized,
                                dry_run=bool(ctx.args.dry_run),
                                stats_out=sentiment_stats,
                            )
                        )
                        if not ctx.args.dry_run and unit_loaded_rows > 0:
                            kafka_payloads = build_source_b_kafka_payloads(
                                raw_payload=window_result.get("raw_payload"),
                                records=sentiment_normalized,
                                run_id=ctx.run_id,
                                run_date=ctx.args.run_date,
                            )
                            publish_json_events(
                                ctx.cfg,
                                topic_key="cw1_news_structured",
                                default_topic="cw1.news.structured.v1",
                                events=kafka_payloads.get("news_structured", []),
                                key_field="symbol",
                                default_client_id="team_pearson_cw1",
                            )
                            publish_json_events(
                                ctx.cfg,
                                topic_key="cw1_event_proxies",
                                default_topic="cw1.event.proxies.v1",
                                events=kafka_payloads.get("event_proxies", []),
                                key_field="symbol",
                                default_client_id="team_pearson_cw1",
                            )
                        _merge_stats(curated_load_stats_total, sentiment_stats)
                        atomic_loaded_rows += unit_loaded_rows
                        state.loaded_rows += unit_loaded_rows
                        mark_source_b_window_result(
                            source_coverage_tracker,
                            symbol,
                            outcome="success",
                            article_count=article_count,
                            loaded_rows=unit_loaded_rows,
                        )

                        manifest.mark_unit(
                            unit_id,
                            "success",
                            details={
                                "symbol": symbol,
                                "month_start": month_key,
                                "articles": article_count,
                                "loaded_rows": unit_loaded_rows,
                            },
                        )
                        if not ctx.args.dry_run:
                            materialization_registry.record_success(
                                materialization_key,
                                run_id=ctx.run_id,
                                unit_id=unit_id,
                                extractor="source_b",
                                config_identity=source_b_config_id,
                                details={
                                    "symbol": symbol,
                                    "month_start": month_key,
                                    "articles": article_count,
                                    "loaded_rows": unit_loaded_rows,
                                },
                            )
                    except Exception as exc:
                        err = f"{exc!r}"
                        extractor_errors.append(
                            {
                                "extractor": "source_b",
                                "symbol": symbol,
                                "month_start": month_key,
                                "error": err,
                            }
                        )
                        source_b_failed_months.append(
                            {"symbol": symbol, "month_start": month_key, "reason": err}
                        )
                        mark_source_b_window_result(
                            source_coverage_tracker,
                            symbol,
                            outcome="failed",
                            reason=err,
                        )
                        manifest.mark_unit(
                            unit_id,
                            "failed",
                            details={"symbol": symbol, "month_start": month_key, "reason": err},
                        )

                if idx % 10 == 0:
                    logger.info(
                        "unit_progress run_id=%s extractor=source_b completed=%s/%s loaded_rows=%s",
                        ctx.run_id,
                        idx,
                        len(source_b_symbols),
                        atomic_loaded_rows,
                    )

        t0_source_coverage = time.monotonic()
        source_coverage_rows, source_coverage_report = finalize_source_coverage_contract(
            source_coverage_tracker,
            config=ctx.cfg,
        )
        source_coverage_details = summarize_source_coverage_counts(source_coverage_report)
        source_coverage_rows_written = write_source_coverage_audit(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            rows=source_coverage_rows,
        )
        write_quality_snapshot(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="source_coverage_audit",
            quality_report=source_coverage_report,
        )
        state.notes = _append_note(
            state.notes,
            f"source_coverage_summary={json.dumps(source_coverage_details, sort_keys=True)}",
        )
        if source_coverage_report.get("failures"):
            state.notes = _append_note(
                state.notes,
                "source_coverage_failures="
                f"{json.dumps(source_coverage_report.get('failures') or [], ensure_ascii=False)}",
            )
        if source_coverage_report.get("passed"):
            logger.info(
                "stage_ok run_id=%s stage=source_coverage_contract rows=%s details=%s",
                ctx.run_id,
                source_coverage_rows_written,
                json.dumps(source_coverage_details, sort_keys=True),
            )
            state.stages_ok += 1
            _log_stage_event(
                run_id=ctx.run_id,
                stage="source_coverage_contract",
                status="ok",
                rows_in=len(universe),
                rows_out=source_coverage_rows_written,
                elapsed_ms=int((time.monotonic() - t0_source_coverage) * 1000),
                details=source_coverage_details,
            )
            _write_dataset_refresh_event(
                run_id=ctx.run_id,
                run_date=ctx.args.run_date,
                dataset_name="source_coverage_audit",
                stage_name="source_coverage_contract",
                status="ok",
                rows_written=source_coverage_rows_written,
                details=source_coverage_details,
            )
        else:
            state.stages_failed += 1
            _log_stage_event(
                run_id=ctx.run_id,
                stage="source_coverage_contract",
                status="failed",
                rows_in=len(universe),
                rows_out=source_coverage_rows_written,
                elapsed_ms=int((time.monotonic() - t0_source_coverage) * 1000),
                details=source_coverage_details,
            )
            _write_dataset_refresh_event(
                run_id=ctx.run_id,
                run_date=ctx.args.run_date,
                dataset_name="source_coverage_audit",
                stage_name="source_coverage_contract",
                status="failed",
                rows_written=source_coverage_rows_written,
                details=source_coverage_details,
            )
            raise RuntimeError(
                "source_coverage_contract_failed: "
                + "; ".join(source_coverage_report.get("failures") or [])
            )

        # ----------------------------------------------------------------
        # Stage: market_factors — beta_1y, momentum_6m/12m, vol_60d, etc.
        # Runs AFTER source_a so price data is already in DB.
        # ----------------------------------------------------------------
        if "market_factors" in {str(x).strip().lower() for x in ctx.enabled_extractors}:
            t0 = time.monotonic()
            try:
                from datetime import date as _date

                from modules.transform.market_factors import build_market_factors

                run_date_obj = _date.fromisoformat(ctx.args.run_date)
                start_date_obj = _date.fromisoformat(
                    get_window(ctx.args.run_date, ctx.frequency)[0]
                )
                mf_records = build_market_factors(
                    universe,
                    end_date=run_date_obj,
                    start_date=start_date_obj,
                    output_frequency=ctx.frequency,
                    benchmark_ticker=str(
                        (ctx.cfg.get("market_factors") or {}).get("benchmark_ticker", "SPY")
                    ).strip()
                    or "SPY",
                )
                mf_normalized = normalize_records(mf_records)
                mf_stats: Dict[str, int] = {}
                mf_rows = int(
                    load_curated(
                        mf_normalized,
                        dry_run=bool(ctx.args.dry_run),
                        stats_out=mf_stats,
                    )
                )
                _merge_stats(curated_load_stats_total, mf_stats)
                atomic_loaded_rows += mf_rows
                state.loaded_rows += mf_rows
                logger.info(
                    "stage_ok run_id=%s stage=market_factors rows=%s stats=%s",
                    ctx.run_id,
                    mf_rows,
                    mf_stats,
                )
                state.stages_ok += 1
                _log_stage_event(
                    run_id=ctx.run_id,
                    stage="market_factors",
                    status="ok",
                    rows_in=len(universe),
                    rows_out=mf_rows,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
                _write_dataset_refresh_event(
                    run_id=ctx.run_id,
                    run_date=ctx.args.run_date,
                    dataset_name="factor_observations",
                    stage_name="market_factors",
                    status="ok",
                    rows_written=mf_rows,
                    details=mf_stats,
                )
            except Exception as exc:
                err = f"{exc!r}"
                logger.exception(
                    "stage_failed run_id=%s stage=market_factors error=%s", ctx.run_id, err
                )
                extractor_errors.append({"extractor": "market_factors", "error": err})
                state.stages_failed += 1
                state.notes = _append_note(state.notes, f"market_factors_error={err[:200]}")
                _log_stage_event(
                    run_id=ctx.run_id,
                    stage="market_factors",
                    status="failed",
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                    details={"error": err},
                )
                _write_dataset_refresh_event(
                    run_id=ctx.run_id,
                    run_date=ctx.args.run_date,
                    dataset_name="factor_observations",
                    stage_name="market_factors",
                    status="failed",
                    rows_written=0,
                    details={"error": err},
                )

        if source_a_failed_symbols or source_b_failed_months:
            state.notes = _append_note(state.notes, "pipeline_extractor_degraded=true")
            logger.warning(
                "extractor_degraded run_id=%s source_a_count=%s source_b_count=%s",
                ctx.run_id,
                len(source_a_failed_symbols),
                len(source_b_failed_months),
            )
            state.notes = _append_note(
                state.notes,
                f"pipeline_extractor_degraded_source_a_count={len(source_a_failed_symbols)}",
            )
            state.notes = _append_note(
                state.notes,
                f"pipeline_extractor_degraded_source_b_count={len(source_b_failed_months)}",
            )

        if source_a_failed_symbols:
            state.notes = _append_note(
                state.notes,
                f"source_a_failed_symbols={_summary_with_limit(source_a_failed_symbols)}",
            )
        if source_b_failed_months:
            state.notes = _append_note(
                state.notes,
                f"source_b_failed_months={_summary_with_limit(source_b_failed_months)}",
            )
        if extractor_errors:
            logger.warning(
                "extractor_warnings run_id=%s error_count=%s details=%s",
                ctx.run_id,
                len(extractor_errors),
                _summary_with_limit(extractor_errors, limit=10),
            )
            state.notes = _append_note(
                state.notes, f"extractor_error_count={len(extractor_errors)}"
            )
            state.notes = _append_note(
                state.notes,
                f"extractor_errors={_summary_with_limit(extractor_errors, limit=10)}",
            )

        state.provider_usage = dict(sorted(provider_usage_counter.items()))
        if state.provider_usage:
            state.notes = _append_note(
                state.notes,
                f"provider_usage={json.dumps(state.provider_usage, sort_keys=True)}",
            )
        state.notes = _append_note(state.notes, f"reused_atomic_units={reused_unit_count}")
        state.notes = _append_note(state.notes, f"reused_atomic_loaded_rows={reused_loaded_rows}")

        state.loaded_rows = atomic_loaded_rows
        manifest_summary = manifest.summary()
        state.notes = _append_note(
            state.notes,
            "manifest_unit_status_counts="
            f"{json.dumps(manifest_summary['unit_status_counts'], sort_keys=True)}",
        )
        logger.info(
            "stage_ok run_id=%s stage=atomic_persist raw_records=%s "
            "loaded_rows=%s provider_usage=%s manifest=%s",
            ctx.run_id,
            raw_record_count,
            state.loaded_rows,
            json.dumps(state.provider_usage, sort_keys=True),
            json.dumps(manifest_summary["unit_status_counts"], sort_keys=True),
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="atomic_persist",
            status="ok",
            rows_in=len(planned_units),
            rows_out=state.loaded_rows,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
        if curated_load_stats_total:
            _write_dataset_refresh_event(
                run_id=ctx.run_id,
                run_date=ctx.args.run_date,
                dataset_name="factor_observations",
                stage_name="atomic_persist",
                status="ok",
                rows_written=int(curated_load_stats_total.get("inserted", 0))
                + int(curated_load_stats_total.get("updated", 0)),
                details=curated_load_stats_total,
            )
        if financial_load_stats_total:
            _write_dataset_refresh_event(
                run_id=ctx.run_id,
                run_date=ctx.args.run_date,
                dataset_name="financial_observations",
                stage_name="atomic_persist",
                status="ok",
                rows_written=int(financial_load_stats_total.get("inserted", 0))
                + int(financial_load_stats_total.get("updated", 0)),
                details=financial_load_stats_total,
            )

        t0 = time.monotonic()
        state.quality_report = quality_accumulator.report()
        logger.info(
            "stage_ok run_id=%s stage=quality report=%s",
            ctx.run_id,
            json.dumps(state.quality_report, sort_keys=True),
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="quality",
            status="ok",
            rows_in=state.quality_report.get("row_count"),
            rows_out=state.quality_report.get("row_count"),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        state.notes = _append_note(
            state.notes,
            f"load_curated_stats={json.dumps(curated_load_stats_total, sort_keys=True)}",
        )
        state.notes = _append_note(
            state.notes,
            f"load_financial_stats={json.dumps(financial_load_stats_total, sort_keys=True)}",
        )

        t0 = time.monotonic()
        final_factor_rows = 0
        if os.getenv("CW1_TEST_MODE") != "1":
            if not manifest.ready_for_final_build():
                raise RuntimeError("final_build_gate_blocked: pending_or_running_units_exist")
            manifest.mark_final_build("running")
            try:
                final_factor_rows = build_and_load_final_factors(
                    run_date=ctx.args.run_date,
                    backfill_years=ctx.backfill_years,
                    output_frequency=ctx.frequency,
                    symbols=universe,
                    dry_run=ctx.args.dry_run,
                )
                manifest.mark_final_build("success", rows_written=int(final_factor_rows))
            except Exception as exc:
                manifest.mark_final_build("failed", error=f"{exc!r}")
                raise
        state.loaded_rows += int(final_factor_rows)
        logger.info(
            "stage_ok run_id=%s stage=transform_final rows=%s total_loaded_rows=%s",
            ctx.run_id,
            int(final_factor_rows),
            state.loaded_rows,
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="transform_final",
            status="ok",
            rows_in=len(universe),
            rows_out=int(final_factor_rows),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
        _write_dataset_refresh_event(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="factor_observations",
            stage_name="transform_final",
            status="ok",
            rows_written=int(final_factor_rows),
            details={"frequency": ctx.frequency},
        )

        t0 = time.monotonic()
        cw2_feature_rows = {
            "sub_scores": 0,
            "factor_scores": 0,
            "risk_overlay": 0,
            "as_of_date_shifted": 0,
        }
        if os.getenv("CW1_TEST_MODE") != "1":
            cw2_feature_rows = build_and_load_cw2_features(
                run_date=ctx.args.run_date,
                symbols=universe,
            )
        cw2_total_rows = int(
            cw2_feature_rows.get("sub_scores", 0)
            + cw2_feature_rows.get("factor_scores", 0)
            + cw2_feature_rows.get("risk_overlay", 0)
        )
        state.loaded_rows += cw2_total_rows
        logger.info(
            "stage_ok run_id=%s stage=cw2_features rows=%s details=%s total_loaded_rows=%s",
            ctx.run_id,
            cw2_total_rows,
            cw2_feature_rows,
            state.loaded_rows,
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="cw2_features",
            status="ok",
            rows_in=len(universe),
            rows_out=cw2_total_rows,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            details=cw2_feature_rows,
        )
        _write_dataset_refresh_event(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="feature_sub_scores",
            stage_name="cw2_features",
            status="ok",
            rows_written=int(cw2_feature_rows.get("sub_scores", 0)),
            details={"as_of_date_shifted": int(cw2_feature_rows.get("as_of_date_shifted", 0))},
        )
        _write_dataset_refresh_event(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="feature_factor_scores",
            stage_name="cw2_features",
            status="ok",
            rows_written=int(cw2_feature_rows.get("factor_scores", 0)),
            details={"as_of_date_shifted": int(cw2_feature_rows.get("as_of_date_shifted", 0))},
        )
        _write_dataset_refresh_event(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="feature_risk_overlay",
            stage_name="cw2_features",
            status="ok",
            rows_written=int(cw2_feature_rows.get("risk_overlay", 0)),
            details={"as_of_date_shifted": int(cw2_feature_rows.get("as_of_date_shifted", 0))},
        )

        fallback_count = (state.provider_usage or {}).get("yfinance", 0)
        fallback_used = "yes" if fallback_count > 0 else "no"
        logger.info(
            "run_summary run_id=%s loaded_rows=%s fallback_used=%s fallback_count=%s quality=%s",
            ctx.run_id,
            state.loaded_rows,
            fallback_used,
            fallback_count,
            json.dumps(state.quality_report or {}, sort_keys=True),
        )
        print(
            f"[run_id={ctx.run_id}] loaded_rows={state.loaded_rows} "
            f"quality={state.quality_report} fallback_used={fallback_used} "
            f"fallback_count={fallback_count}"
        )

    except Exception as e:
        state.status = "failed"
        state.err = f"pipeline_error: {repr(e)}"
        state.error_traceback = traceback.format_exc()
        state.stages_failed += 1
        logger.exception("run_failed run_id=%s error=%s", ctx.run_id, state.err)
        _log_stage_event(
            run_id=ctx.run_id,
            stage="pipeline",
            status="failed",
            details={"error": state.err},
        )


def finalize_audit_and_runlog(ctx: RunContext, state: PipelineState) -> int:
    """Persist run-finish audit artifacts and return process exit code."""
    end = utc_now_iso()

    run_log_path = ctx.log_cfg.get("run_log_path", "logs/pipeline_runs.jsonl")
    if not os.path.isabs(run_log_path):
        run_log_path = os.path.join(ctx.base_dir, run_log_path)

    record = RunLog(
        run_id=ctx.run_id,
        start_time_utc=ctx.start_time_utc,
        end_time_utc=end,
        run_date=ctx.args.run_date,
        frequency=ctx.frequency,
        backfill_years=int(ctx.backfill_years),
        company_limit=ctx.company_limit,
        stages_ok=int(state.stages_ok),
        stages_failed=int(state.stages_failed),
        status=state.status,
        error=state.err,
        notes=state.notes,
    )
    write_jsonl(run_log_path, asdict(record))

    try:
        from modules.output.audit import write_pipeline_run_finish

        write_pipeline_run_finish(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            finished_at=end,
            status=state.status,
            rows_written=int(state.loaded_rows),
            error_message=state.err,
            error_traceback=state.error_traceback,
            notes=state.notes,
            frequency=ctx.frequency,
            backfill_years=int(ctx.backfill_years),
            company_limit=ctx.company_limit,
            enabled_extractors=ctx.enabled_extractors_text,
        )
    except Exception as audit_exc:
        logger.warning(
            "audit_finish_warning run_id=%s warning=%r",
            ctx.run_id,
            audit_exc,
            exc_info=True,
        )

    try:
        from modules.output.metadata import write_quality_snapshot

        write_quality_snapshot(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="factor_observations",
            quality_report=state.quality_report or {},
        )
        _write_dataset_refresh_event(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="quality_snapshots",
            stage_name="quality_snapshot",
            status="ok",
            rows_written=1,
            details={"dataset_name": "factor_observations"},
        )
    except Exception as metadata_exc:
        logger.warning(
            "quality_snapshot_warning run_id=%s warning=%r",
            ctx.run_id,
            metadata_exc,
            exc_info=True,
        )

    logger.info("run_log_written run_id=%s path=%s", ctx.run_id, run_log_path)
    print(f"[run_id={ctx.run_id}] run_log_written_to={run_log_path}")

    return 0 if state.status == "success" else 1


def run_mongo_index_stage(ctx: RunContext, state: PipelineState) -> None:
    """Best-effort Mongo indexing stage after a successful main pipeline run."""
    if state.status != "success":
        return
    if not bool(getattr(ctx.args, "index_mongo", True)):
        logger.info("mongo_index_skipped run_id=%s reason=disabled_by_cli", ctx.run_id)
        return
    if bool(ctx.args.dry_run):
        logger.info("mongo_index_skipped run_id=%s reason=dry_run", ctx.run_id)
        return

    t0 = time.monotonic()
    cmd = [
        sys.executable,
        "-m",
        "scripts.index_news_to_mongo",
        "--run-date",
        ctx.args.run_date,
        "--config",
        ctx.args.config,
    ]
    logger.info("mongo_index_start run_id=%s cmd=%s", ctx.run_id, " ".join(cmd))
    # Safe: fixed script path + validated runtime args; shell not used.
    result = subprocess.run(
        cmd,
        cwd=ctx.base_dir,
        check=False,
    )  # nosec B603
    if result.returncode != 0:
        logger.warning(
            "mongo_index_warning run_id=%s rc=%s mode=best_effort",
            ctx.run_id,
            result.returncode,
        )
        state.notes = _append_note(state.notes, f"mongo_index_warning_rc={result.returncode}")
        _log_stage_event(
            run_id=ctx.run_id,
            stage="mongo_index",
            status="warning",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            details={"returncode": int(result.returncode)},
        )
        _write_dataset_refresh_event(
            run_id=ctx.run_id,
            run_date=ctx.args.run_date,
            dataset_name="news_articles",
            stage_name="mongo_index",
            status="warning",
            rows_written=0,
            details={"returncode": int(result.returncode)},
        )
        return

    logger.info("mongo_index_done run_id=%s", ctx.run_id)
    state.stages_ok += 1
    _log_stage_event(
        run_id=ctx.run_id,
        stage="mongo_index",
        status="ok",
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )
    _write_dataset_refresh_event(
        run_id=ctx.run_id,
        run_date=ctx.args.run_date,
        dataset_name="news_articles",
        stage_name="mongo_index",
        status="ok",
        rows_written=0,
        details={},
    )


def main() -> int:
    """Program entrypoint for one end-to-end pipeline run."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    args = parse_args()
    ctx = resolve_runtime(base_dir, args)
    if ctx is None:
        return 1

    state = PipelineState()
    run_scheduling_stage(ctx, state)
    write_audit_start_stage(ctx, state)
    run_pipeline_stage(ctx, state)
    run_mongo_index_stage(ctx, state)
    return finalize_audit_and_runlog(ctx, state)


if __name__ == "__main__":
    raise SystemExit(main())
