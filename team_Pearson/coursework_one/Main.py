import json
import logging
import os
import time
import traceback
import uuid
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
ALLOWED_EXTRACTORS = {"source_a", "source_b"}


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
    }
    for key, value in mapping.items():
        if os.getenv(key) in (None, "") and value not in (None, ""):
            os.environ[key] = str(value)

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


def _log_stage_event(
    *,
    run_id: str,
    stage: str,
    status: str,
    rows_in: Optional[int] = None,
    rows_out: Optional[int] = None,
    elapsed_ms: Optional[int] = None,
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
        raise ValueError(f"Invalid enabled_extractors={invalid}. Allowed: source_a, source_b.")
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
    extractor_errors_out: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Merge records from the currently integrated source modules.

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
                    "source": "alpha_vantage",
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
                extract_source_a(symbols, run_date, backfill_years, frequency, config=config)
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
                extract_source_b(symbols, run_date, backfill_years, frequency, config=config)
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
        if rec.get("factor_name") != "total_debt":
            continue
        symbol = str(rec.get("symbol") or "").strip()
        source = str(rec.get("source") or "").strip().lower()
        if symbol and source:
            symbol_provider[symbol] = source

    counts: Dict[str, int] = {}
    for provider in symbol_provider.values():
        counts[provider] = counts.get(provider, 0) + 1
    return counts


def split_atomic_financial_records(
    records: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split raw records into financial atomic rows and remaining curated rows."""
    financial: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []
    for rec in records:
        factor_name = str(rec.get("factor_name") or "").strip().lower()
        if factor_name in FINANCIAL_ATOMIC_FACTORS and rec.get("source") != "factor_transform":
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
        from modules.output import (
            load_curated,
            load_financial_observations,
            normalize_financial_records,
            normalize_records,
            run_quality_checks,
        )
        from modules.transform import build_and_load_final_factors

        t0 = time.monotonic()
        universe_cfg = ctx.cfg.get("universe") or {}
        country_allowlist = universe_cfg.get("country_allowlist")
        universe = get_company_universe(ctx.company_limit, country_allowlist=country_allowlist)
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
        logger.info(
            "extract_config run_id=%s atomic_collection_frequency=daily "
            "output_sampling_frequency=%s",
            ctx.run_id,
            ctx.frequency,
        )
        raw = collect_raw_records(
            universe,
            ctx.args.run_date,
            "daily",
            ctx.backfill_years,
            enabled_extractors=ctx.enabled_extractors,
            config=ctx.cfg,
            extractor_errors_out=extractor_errors,
        )
        if extractor_errors:
            logger.warning(
                "extractor_warnings run_id=%s error_count=%s details=%s",
                ctx.run_id,
                len(extractor_errors),
                json.dumps(extractor_errors, ensure_ascii=False),
            )
            state.notes = _append_note(
                state.notes, f"extractor_error_count={len(extractor_errors)}"
            )
            state.notes = _append_note(
                state.notes,
                f"extractor_errors={json.dumps(extractor_errors, ensure_ascii=False)}",
            )

        if universe and not raw and len(extractor_errors) >= len(set(ctx.enabled_extractors)):
            raise RuntimeError(
                f"all_enabled_extractors_failed enabled={sorted(set(ctx.enabled_extractors))}"
            )

        state.provider_usage = summarize_provider_usage(raw)
        if state.provider_usage:
            state.notes = (
                f"{state.notes}; provider_usage={json.dumps(state.provider_usage, sort_keys=True)}"
            )
        logger.info(
            "stage_ok run_id=%s stage=extract records=%s provider_usage=%s",
            ctx.run_id,
            len(raw),
            json.dumps(state.provider_usage, sort_keys=True),
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="extract",
            status="ok",
            rows_in=len(universe),
            rows_out=len(raw),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        financial_atomic_raw, curated_raw = split_atomic_financial_records(raw)

        t0 = time.monotonic()
        curated = normalize_records(curated_raw)
        logger.info(
            "stage_ok run_id=%s stage=normalize curated_records=%s",
            ctx.run_id,
            len(curated),
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="normalize",
            status="ok",
            rows_in=len(curated_raw),
            rows_out=len(curated),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        t0 = time.monotonic()
        state.quality_report = run_quality_checks(curated)
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
            rows_in=len(curated),
            rows_out=len(curated),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        t0 = time.monotonic()
        curated_load_stats: Dict[str, int] = {}
        state.loaded_rows = load_curated(
            curated, dry_run=ctx.args.dry_run, stats_out=curated_load_stats
        )
        state.notes = _append_note(
            state.notes,
            f"load_curated_stats={json.dumps(curated_load_stats, sort_keys=True)}",
        )
        logger.info(
            "stage_ok run_id=%s stage=load_curated rows=%s dry_run=%s stats=%s",
            ctx.run_id,
            state.loaded_rows,
            ctx.args.dry_run,
            json.dumps(curated_load_stats, sort_keys=True),
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="load_curated",
            status="ok",
            rows_in=len(curated),
            rows_out=state.loaded_rows,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        t0 = time.monotonic()
        financial_normalized = normalize_financial_records(financial_atomic_raw)
        financial_load_stats: Dict[str, int] = {}
        financial_rows = load_financial_observations(
            financial_normalized,
            dry_run=ctx.args.dry_run,
            stats_out=financial_load_stats,
        )
        state.loaded_rows += int(financial_rows)
        state.notes = _append_note(
            state.notes,
            f"load_financial_stats={json.dumps(financial_load_stats, sort_keys=True)}",
        )
        logger.info(
            "stage_ok run_id=%s stage=load_financial rows=%s "
            "total_loaded_rows=%s dry_run=%s stats=%s",
            ctx.run_id,
            int(financial_rows),
            state.loaded_rows,
            ctx.args.dry_run,
            json.dumps(financial_load_stats, sort_keys=True),
        )
        state.stages_ok += 1
        _log_stage_event(
            run_id=ctx.run_id,
            stage="load_financial",
            status="ok",
            rows_in=len(financial_normalized),
            rows_out=int(financial_rows),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

        t0 = time.monotonic()
        final_factor_rows = 0
        if os.getenv("CW1_TEST_MODE") != "1":
            final_factor_rows = build_and_load_final_factors(
                run_date=ctx.args.run_date,
                backfill_years=ctx.backfill_years,
                output_frequency=ctx.frequency,
                symbols=universe,
                dry_run=ctx.args.dry_run,
            )
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
    return finalize_audit_and_runlog(ctx, state)


if __name__ == "__main__":
    raise SystemExit(main())
