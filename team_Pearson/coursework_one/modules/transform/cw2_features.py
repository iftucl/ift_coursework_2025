from __future__ import annotations

"""CW2 feature pipeline wrapper for universe screening, factor scores, and portfolio targets."""

import hashlib
import inspect
import json
import logging
import math
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import yaml
from modules.db import get_db_engine
from modules.output.metadata import write_quality_snapshot
from modules.transform.pit_semantics import (
    financial_publish_cutoff_predicate,
    financial_publish_value_expr,
)
from sqlalchemy import text

try:
    from team_Pearson.coursework_two.modules.utils.governance import (
        FEATURE_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )
except (
    ModuleNotFoundError
):  # pragma: no cover - import-path fallback for direct module execution
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_two.modules.utils.governance import (
        FEATURE_VERSION_KEYS,
        resolve_version_bundle,
        select_version_fields,
    )

logger = logging.getLogger(__name__)
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class CW2PITSnapshot:
    """Single as-of-date PIT-clean snapshot consumed by the CW2 pipeline."""

    requested_as_of_date: date
    as_of_date: date
    financial_publish_cutoff_date: date
    factor_df: Any
    financial_df: Any
    company_info: Any
    company_info_lookup: Dict[str, Dict[str, Any]]
    sector_map: Dict[str, str]
    vix_level: Optional[float]
    vix_history: List[float]
    risk_data: Any
    covariance_matrix: Any = None
    covariance_meta: Dict[str, Any] = field(default_factory=dict)
    previous_positions: List[Dict[str, Any]] = field(default_factory=list)
    term_spread_level: Optional[float] = None
    term_spread_history: List[float] = field(default_factory=list)


@dataclass(frozen=True)
class UniverseGuardResult:
    """Minimum-universe guard outcome for scoring and portfolio construction."""

    min_scoring_universe: int
    min_investable_universe: int
    scoring_universe: int
    investable_universe: int
    allow_factor_scoring: bool
    allow_portfolio_construction: bool


def _validated_identifier(value: str, *, label: str) -> str:
    candidate = str(value).strip()
    if not _VALID_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"Invalid {label}: {value!r}")
    return candidate


def _validated_identifier_list(values: Iterable[str], *, label: str) -> List[str]:
    return [_validated_identifier(str(value), label=label) for value in values]


def _db_schema() -> str:
    return _validated_identifier(
        os.getenv("POSTGRES_SCHEMA", "systematic_equity"),
        label="schema",
    )


def _pit_publish_cutoff_predicate(
    cutoff_param: str, *, fallback_expr: str = "observation_date"
) -> str:
    cutoff_param = str(cutoff_param).strip()
    fallback_expr = str(fallback_expr).strip()
    if not cutoff_param or not fallback_expr:
        raise ValueError(
            "publish cutoff predicate requires cutoff_param and fallback_expr"
        )
    return f"COALESCE(publish_date, {fallback_expr}) <= :{cutoff_param}"


def _feature_as_of_min_coverage_ratio() -> float:
    raw = str(os.getenv("CW2_FEATURE_ASOF_MIN_SYMBOL_COVERAGE_RATIO", "0.60")).strip()
    try:
        ratio = float(raw)
    except ValueError:
        ratio = 0.60
    return min(1.0, max(0.0, ratio))


def _load_company_info_rows(
    conn: Any, query: Any, symbols: List[str]
) -> List[Dict[str, Any]]:
    try:
        return list(conn.execute(query, {"symbols": symbols}).mappings().all())
    except Exception as exc:  # pragma: no cover - depends on runtime schema shape
        logger.debug("cw2_features: company info query failed: %s", exc)
        return []


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _cw2_root() -> Path:
    return _repo_root() / "team_Pearson" / "coursework_two"


def _cw2_config_path() -> Path:
    return _cw2_root() / "config" / "conf.yaml"


def _cw2_schema_path() -> Path:
    return _cw2_root() / "sql" / "cw2_feature_schema.sql"


def _cw1_config_path() -> Path:
    configured_path = os.getenv("CW1_CONFIG_PATH")
    if configured_path:
        return Path(configured_path)
    return _repo_root() / "team_Pearson" / "coursework_one" / "config" / "conf.yaml"


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolved_minio_config() -> Dict[str, Any]:
    cw1_cfg = _load_yaml_file(_cw1_config_path())
    minio_cfg = dict(cw1_cfg.get("minio") or {})
    minio_cfg["endpoint"] = os.getenv("MINIO_ENDPOINT", minio_cfg.get("endpoint"))
    minio_cfg["access_key"] = os.getenv("MINIO_ACCESS_KEY", minio_cfg.get("access_key"))
    minio_cfg["secret_key"] = os.getenv("MINIO_SECRET_KEY", minio_cfg.get("secret_key"))
    minio_cfg["bucket"] = os.getenv("MINIO_BUCKET", minio_cfg.get("bucket"))
    endpoint_raw = str(minio_cfg.get("endpoint", "") or "").strip()
    is_https = endpoint_raw.startswith("https://")
    minio_cfg["endpoint"] = endpoint_raw.replace("http://", "").replace("https://", "")
    if minio_cfg.get("secure") is None:
        minio_cfg["secure"] = is_https
    return minio_cfg


def _build_minio_client(minio_cfg: Dict[str, Any]) -> Any:
    from minio import Minio

    return Minio(
        endpoint=minio_cfg["endpoint"],
        access_key=minio_cfg["access_key"],
        secret_key=minio_cfg["secret_key"],
        secure=minio_cfg.get("secure", False),
    )


def _covariance_artifact_object_path(
    *,
    snapshot_id: str,
    as_of_date: date,
    portfolio_name: str,
) -> str:
    safe_portfolio = (
        re.sub(r"[^A-Za-z0-9_-]+", "_", str(portfolio_name).strip())
        or "cw2_core_equity"
    )
    return (
        "artifacts/cw2/portfolio_construction/covariance/"
        f"year={as_of_date.strftime('%Y')}/month={as_of_date.strftime('%m')}/"
        f"as_of_date={as_of_date.isoformat()}/portfolio_name={safe_portfolio}/snapshot_id={snapshot_id}.npz"
    )


def _persist_covariance_artifact(
    *,
    snapshot_id: str,
    as_of_date: date,
    portfolio_name: str,
    covariance_matrix: Any,
    covariance_meta: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if covariance_matrix is None or getattr(covariance_matrix, "empty", False):
        return None

    minio_cfg = _resolved_minio_config()
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(key) for key in required):
        logger.info(
            "cw2_features: covariance artifact skipped because MinIO config is incomplete"
        )
        return None

    try:
        ordered_symbols = [
            str(symbol) for symbol in getattr(covariance_matrix, "columns", [])
        ]
        if not ordered_symbols:
            return None
        matrix = (
            covariance_matrix.reindex(index=ordered_symbols, columns=ordered_symbols)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
        )
        buf = BytesIO()
        np.savez_compressed(
            buf,
            covariance=matrix.to_numpy(dtype=float),
            symbols=np.asarray(ordered_symbols, dtype=str),
            as_of_date=np.asarray([as_of_date.isoformat()], dtype=str),
            covariance_meta_json=np.asarray(
                [_json_dumps(covariance_meta or {})], dtype=str
            ),
        )
        payload = buf.getvalue()
        checksum = hashlib.sha256(payload).hexdigest()
        client = _build_minio_client(minio_cfg)
        bucket = str(minio_cfg["bucket"])
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        object_key = _covariance_artifact_object_path(
            snapshot_id=snapshot_id,
            as_of_date=as_of_date,
            portfolio_name=portfolio_name,
        )
        client.put_object(
            bucket,
            object_key,
            data=BytesIO(payload),
            length=len(payload),
            content_type="application/octet-stream",
        )
        return {
            "storage_type": "minio",
            "bucket": bucket,
            "object_key": object_key,
            "format": "npz",
            "content_type": "application/octet-stream",
            "sha256": checksum,
            "size_bytes": len(payload),
            "symbol_count": len(ordered_symbols),
        }
    except Exception as exc:  # pragma: no cover - external service dependent
        logger.warning(
            "cw2_features: covariance artifact persistence skipped snapshot_id=%s as_of=%s error=%r",
            snapshot_id,
            as_of_date,
            exc,
        )
        return None


def _import_cw2_modules() -> tuple[Any, Any, Any, Any, Any, Any]:
    repo_root = str(_repo_root())
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from team_Pearson.coursework_two.modules.feature.composite_alpha import (
        compute_composite_alpha,
        resolve_regime_from_config,
    )
    from team_Pearson.coursework_two.modules.feature.factor_engine import (
        compute_factor_scores_for_date,
    )
    from team_Pearson.coursework_two.modules.portfolio.construction import (
        build_portfolio_targets,
    )
    from team_Pearson.coursework_two.modules.portfolio.universe_screen import (
        build_investable_universe,
    )
    from team_Pearson.coursework_two.modules.risk.overlay import apply_risk_overlay

    return (
        compute_factor_scores_for_date,
        compute_composite_alpha,
        resolve_regime_from_config,
        apply_risk_overlay,
        build_investable_universe,
        build_portfolio_targets,
    )


def _load_cw2_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    configured_path = config_path or os.getenv("CW2_CONFIG_PATH")
    from team_Pearson.coursework_two.modules.utils.config_validation import (
        load_cw2_config,
    )

    return load_cw2_config(
        str(Path(configured_path)) if configured_path else str(_cw2_config_path())
    )


def _ensure_cw2_schema() -> None:
    sql_parts = [_cw2_schema_path().read_text(encoding="utf-8")]
    recommendation_schema = _cw2_root() / "sql" / "cw2_recommendation_schema.sql"
    if recommendation_schema.exists():
        sql_parts.append(recommendation_schema.read_text(encoding="utf-8"))
    sql_text = "\n\n".join(sql_parts)
    engine = get_db_engine()
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()
    finally:
        raw_conn.close()


def _resolve_feature_as_of_date(run_date: date, symbols: List[str]) -> Optional[date]:
    if not symbols:
        return None

    engine = get_db_engine()
    schema = _db_schema()
    min_symbols = max(1, math.ceil(len(set(symbols)) * _feature_as_of_min_coverage_ratio()))
    price_anchor_sql = text(f"""
        SELECT observation_date AS as_of_date
        FROM {schema}.factor_observations
        WHERE symbol = ANY(:symbols)
          AND factor_name = 'adjusted_close_price'
          AND observation_date <= :run_date
          AND {_pit_publish_cutoff_predicate("run_date")}
        GROUP BY observation_date
        HAVING COUNT(DISTINCT symbol) >= :min_symbols
        ORDER BY observation_date DESC
        LIMIT 1
        """)  # nosec B608 - schema identifier is validated before interpolation
    generic_sql = text(f"""
        SELECT observation_date AS as_of_date
        FROM {schema}.factor_observations
        WHERE symbol = ANY(:symbols)
          AND observation_date <= :run_date
          AND {_pit_publish_cutoff_predicate("run_date")}
        GROUP BY observation_date
        HAVING COUNT(DISTINCT symbol) >= :min_symbols
        ORDER BY observation_date DESC
        LIMIT 1
        """)  # nosec B608 - schema identifier is validated before interpolation
    with engine.connect() as conn:
        params = {"symbols": symbols, "run_date": run_date, "min_symbols": min_symbols}
        row = (
            conn.execute(price_anchor_sql, params)
            .mappings()
            .first()
        )
        if row and row["as_of_date"]:
            return row["as_of_date"]
        row = (
            conn.execute(generic_sql, params)
            .mappings()
            .first()
        )
    return row["as_of_date"] if row and row["as_of_date"] else None


def _load_company_info(symbols: List[str]) -> Any:
    import pandas as pd

    if not symbols:
        return pd.DataFrame(columns=["symbol", "security", "gics_sector", "country"])

    engine = get_db_engine()
    schema = _db_schema()
    queries = [
        text(f"""
            SELECT
                symbol,
                NULLIF(TRIM(security), '') AS security,
                COALESCE(gics_sector, 'Unknown') AS gics_sector,
                NULLIF(TRIM(country), '') AS country
            FROM {schema}.company_static
            WHERE symbol = ANY(:symbols)
            """),  # nosec B608 - schema identifier is validated before interpolation
        text(f"""
            SELECT
                symbol,
                NULLIF(TRIM(security), '') AS security,
                COALESCE(gics_sector, 'Unknown') AS gics_sector,
                NULLIF(TRIM(country), '') AS country
            FROM {schema}.equity_static
            WHERE symbol = ANY(:symbols)
            """),  # nosec B608 - schema identifier is validated before interpolation
    ]

    with engine.connect() as conn:
        for query in queries:
            rows = _load_company_info_rows(conn, query, symbols)
            if rows:
                df = pd.DataFrame(rows)
                df["symbol"] = df["symbol"].astype(str)
                if "security" not in df.columns:
                    df["security"] = None
                df["gics_sector"] = df["gics_sector"].fillna("Unknown").astype(str)
                return df

    return pd.DataFrame(
        {
            "symbol": symbols,
            "security": [None] * len(symbols),
            "gics_sector": ["Unknown"] * len(symbols),
            "country": [None] * len(symbols),
        }
    )


def _load_factor_snapshot(
    as_of_date: date,
    symbols: List[str],
    *,
    factor_names: Optional[List[str]] = None,
) -> Any:
    import pandas as pd

    requested_factor_names = None
    if factor_names is not None:
        requested_factor_names = sorted(
            {str(name).strip() for name in factor_names if str(name).strip()}
        )
        if not requested_factor_names:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "observation_date",
                    "factor_name",
                    "factor_value",
                    "publish_date",
                ]
            )

    engine = get_db_engine()
    schema = _db_schema()
    factor_name_clause = ""
    if requested_factor_names is not None:
        factor_name_clause = "\n              AND factor_name = ANY(:factor_names)"
    sql = text(f"""
        WITH ranked AS (
            SELECT
                symbol,
                observation_date,
                factor_name,
                factor_value,
                COALESCE(publish_date, observation_date) AS publish_date,
                ROW_NUMBER() OVER (
                    PARTITION BY symbol, factor_name
                    ORDER BY observation_date DESC,
                             COALESCE(publish_date, observation_date) DESC
                ) AS rn
            FROM {schema}.factor_observations
            WHERE observation_date <= :as_of_date
              AND {_pit_publish_cutoff_predicate("as_of_date")}
              AND (symbol = ANY(:symbols) OR symbol = '_MACRO')
              {factor_name_clause}
        )
        SELECT symbol, observation_date, factor_name, factor_value, publish_date
        FROM ranked
        WHERE rn = 1
        ORDER BY symbol, factor_name
        """)  # nosec B608 - schema identifier is validated before interpolation

    params: Dict[str, Any] = {"as_of_date": as_of_date, "symbols": symbols}
    if requested_factor_names is not None:
        params["factor_names"] = requested_factor_names
    with engine.connect() as conn:
        rows = conn.execute(sql, params)
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if not df.empty:
        df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date
        if "publish_date" in df.columns:
            df["publish_date"] = pd.to_datetime(
                df["publish_date"], errors="coerce"
            ).dt.date
        df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
    return df


def _load_macro_factor_history(
    as_of_date: date,
    factor_name: str,
    *,
    lookback_days: int,
) -> List[float]:
    if lookback_days <= 0:
        return []

    engine = get_db_engine()
    schema = _db_schema()
    start_date = as_of_date - timedelta(days=lookback_days)
    sql = text(f"""
        SELECT observation_date, factor_value
        FROM {schema}.factor_observations
        WHERE symbol = '_MACRO'
          AND factor_name = :factor_name
          AND observation_date BETWEEN :start_date AND :as_of_date
          AND {_pit_publish_cutoff_predicate("as_of_date")}
        ORDER BY observation_date
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.connect() as conn:
        rows = (
            conn.execute(
                sql,
                {
                    "factor_name": factor_name,
                    "start_date": start_date,
                    "as_of_date": as_of_date,
                },
            )
            .mappings()
            .all()
        )

    out: List[float] = []
    for row in rows:
        parsed = _safe_float(row.get("factor_value"))
        if parsed is not None:
            out.append(parsed)
    return out


def _load_macro_factor_series(
    as_of_date: date,
    factor_name: str,
    *,
    lookback_days: int,
) -> pd.Series:
    if lookback_days <= 0:
        return pd.Series(dtype=float)

    engine = get_db_engine()
    schema = _db_schema()
    start_date = as_of_date - timedelta(days=lookback_days)
    sql = text(f"""
        SELECT observation_date, factor_value
        FROM {schema}.factor_observations
        WHERE symbol = '_MACRO'
          AND factor_name = :factor_name
          AND observation_date BETWEEN :start_date AND :as_of_date
          AND {_pit_publish_cutoff_predicate("as_of_date")}
        ORDER BY observation_date
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.connect() as conn:
        rows = (
            conn.execute(
                sql,
                {
                    "factor_name": factor_name,
                    "start_date": start_date,
                    "as_of_date": as_of_date,
                },
            )
            .mappings()
            .all()
        )

    if not rows:
        return pd.Series(dtype=float)

    out = pd.DataFrame(rows)
    out["observation_date"] = pd.to_datetime(
        out["observation_date"], errors="coerce"
    ).dt.date
    out["factor_value"] = pd.to_numeric(out["factor_value"], errors="coerce")
    out = out.dropna(subset=["observation_date", "factor_value"])
    if out.empty:
        return pd.Series(dtype=float)
    return out.set_index("observation_date")["factor_value"].sort_index()


def _load_term_spread_context(
    as_of_date: date,
    *,
    lookback_days: int,
) -> tuple[Optional[float], List[float]]:
    ten_year = _load_macro_factor_series(
        as_of_date, "us_treasury_10y", lookback_days=lookback_days
    )
    three_month = _load_macro_factor_series(
        as_of_date, "us_treasury_3m", lookback_days=lookback_days
    )
    if ten_year.empty or three_month.empty:
        return None, []

    aligned = pd.concat(
        [
            pd.to_numeric(ten_year, errors="coerce").rename("ten_year"),
            pd.to_numeric(three_month, errors="coerce").rename("three_month"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if aligned.empty:
        return None, []

    spread = aligned["ten_year"] - aligned["three_month"]
    latest = _safe_float(spread.iloc[-1])
    return latest, [
        float(value) for value in spread.tolist() if _safe_float(value) is not None
    ]


def _cw2_factor_names(config: Optional[Dict[str, Any]] = None) -> List[str]:
    # ``momentum_12m`` is the CW1 legacy storage name. Its upstream calculation
    # already skips the latest 21 trading days, so CW2 exposes it under the
    # economically accurate sub-variable name ``momentum_12_1m``.
    sub_var_map = {
        "ebitda_margin": ["ebitda_margin"],
        "roe": [],
        "debt_to_equity_inv": ["debt_to_equity"],
        "book_to_price": ["pb_ratio"],
        "earnings_to_price": ["ep_ratio"],
        "ebitda_to_ev": ["ebitda_to_ev"],
        "momentum_1m": ["momentum_1m"],
        "momentum_6m": ["momentum_6m"],
        "momentum_12_1m": ["momentum_12m"],
        "sentiment_7d_avg": ["sentiment_7d_avg"],
        "sentiment_30d_avg": ["sentiment_30d_avg"],
        "sentiment_surprise": ["sentiment_surprise"],
        "dividend_yield": ["dividend_yield"],
        "dividend_stability": ["dividend_stability"],
        "payout_sustainability": ["payout_ratio"],
    }

    configured = set()
    for factor_cfg in ((config or {}).get("factors") or {}).values():
        for sub_var in factor_cfg.get("sub_variables") or []:
            configured.update(sub_var_map.get(str(sub_var), []))
    if configured:
        return sorted(configured)

    # Fallback to the default CW2 factor set when config is absent.
    default_factor_names = set()
    for names in sub_var_map.values():
        default_factor_names.update(names)
    return sorted(default_factor_names)


def _load_latest_factor_snapshot(
    as_of_date: date,
    symbols: List[str],
    factor_names: List[str],
) -> Any:
    import pandas as pd

    if not symbols or not factor_names:
        return pd.DataFrame(
            columns=[
                "symbol",
                "observation_date",
                "factor_name",
                "factor_value",
                "publish_date",
            ]
        )

    engine = get_db_engine()
    schema = _db_schema()
    sql = text(f"""
        WITH ranked AS (
            SELECT
                symbol,
                observation_date,
                factor_name,
                factor_value,
                COALESCE(publish_date, observation_date) AS publish_date,
                ROW_NUMBER() OVER (
                    PARTITION BY symbol, factor_name
                    ORDER BY observation_date DESC,
                             COALESCE(publish_date, observation_date) DESC
                ) AS rn
            FROM {schema}.factor_observations
            WHERE symbol = ANY(:symbols)
              AND observation_date <= :as_of_date
              AND {_pit_publish_cutoff_predicate("as_of_date")}
              AND factor_name = ANY(:factor_names)
        )
        SELECT symbol, observation_date, factor_name, factor_value, publish_date
        FROM ranked
        WHERE rn = 1
        ORDER BY symbol, factor_name
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "symbols": symbols,
                "as_of_date": as_of_date,
                "factor_names": factor_names,
            },
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if not df.empty:
        df["observation_date"] = pd.to_datetime(
            df["observation_date"], errors="coerce"
        ).dt.date
        if "publish_date" in df.columns:
            df["publish_date"] = pd.to_datetime(
                df["publish_date"], errors="coerce"
            ).dt.date
        df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
    return df


def _load_financial_snapshot(
    market_as_of_date: date,
    publish_cutoff_date: date,
    symbols: List[str],
) -> Any:
    import pandas as pd

    engine = get_db_engine()
    schema = _db_schema()
    publish_expr = financial_publish_value_expr()
    publish_cutoff = financial_publish_cutoff_predicate("publish_cutoff_date")
    sql = text(f"""
        SELECT
            symbol,
            report_date,
            metric_name,
            metric_value,
            source,
            {publish_expr} AS publish_date
        FROM {schema}.financial_observations
        WHERE symbol = ANY(:symbols)
          AND report_date <= :market_as_of_date
          AND {publish_cutoff}
          AND metric_name IN ('roe', 'net_income', 'stockholders_equity')
        ORDER BY symbol, report_date, {publish_expr}, metric_name
        """)  # nosec B608 - schema identifier is validated before interpolation

    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "market_as_of_date": market_as_of_date,
                "publish_cutoff_date": publish_cutoff_date,
                "symbols": symbols,
            },
        )
        df = pd.DataFrame(rows.fetchall(), columns=rows.keys())

    if not df.empty:
        df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
        df["publish_date"] = pd.to_datetime(df["publish_date"], errors="coerce").dt.date
        df["metric_value"] = pd.to_numeric(df["metric_value"], errors="coerce")
    return df


def _extract_vix_level(factor_df: Any, as_of_date: date) -> Optional[float]:
    if factor_df is None or factor_df.empty:
        return None
    rows = factor_df[
        (factor_df["symbol"] == "_MACRO")
        & (factor_df["observation_date"] <= as_of_date)
        & (factor_df["factor_name"] == "vix_close")
    ]
    if rows.empty:
        return None
    rows = rows.sort_values("observation_date")
    return _safe_float(rows.iloc[-1]["factor_value"])


def _load_previous_portfolio_positions(
    as_of_date: date,
    *,
    portfolio_name: str,
) -> List[Dict[str, Any]]:
    engine = get_db_engine()
    schema = _db_schema()
    prev_date_sql = text(f"""
        SELECT MAX(as_of_date) AS prev_as_of_date
        FROM {schema}.portfolio_target_positions
        WHERE portfolio_name = :portfolio_name
          AND as_of_date < :as_of_date
        """)  # nosec B608 - schema identifier is validated before interpolation
    with engine.connect() as conn:
        prev_row = (
            conn.execute(
                prev_date_sql,
                {"portfolio_name": portfolio_name, "as_of_date": as_of_date},
            )
            .mappings()
            .first()
        )
        prev_as_of_date = prev_row["prev_as_of_date"] if prev_row else None
        if prev_as_of_date is None:
            return []

        rows = (
            conn.execute(
                text(
                    f"""
                SELECT symbol, target_weight
                FROM {schema}.portfolio_target_positions
                WHERE portfolio_name = :portfolio_name
                  AND as_of_date = :prev_as_of_date
                """
                ),  # nosec B608 - schema identifier is validated before interpolation
                {"portfolio_name": portfolio_name, "prev_as_of_date": prev_as_of_date},
        )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def _load_previous_portfolio_target_snapshot(
    as_of_date: date,
    *,
    portfolio_name: str,
) -> tuple[Optional[date], List[Dict[str, Any]]]:
    engine = get_db_engine()
    schema = _db_schema()
    prev_date_sql = text(f"""
        SELECT MAX(as_of_date) AS prev_as_of_date
        FROM {schema}.portfolio_target_positions
        WHERE portfolio_name = :portfolio_name
          AND as_of_date < :as_of_date
        """)  # nosec B608 - schema identifier is validated before interpolation
    with engine.connect() as conn:
        prev_row = (
            conn.execute(
                prev_date_sql,
                {"portfolio_name": portfolio_name, "as_of_date": as_of_date},
            )
            .mappings()
            .first()
        )
        prev_as_of_date = prev_row["prev_as_of_date"] if prev_row else None
        if prev_as_of_date is None:
            return None, []

        rows = (
            conn.execute(
                text(
                    f"""
                SELECT
                    symbol,
                    selection_rank,
                    selected_signal,
                    target_weight,
                    weighting_scheme,
                    ranking_mode,
                    ranking_score,
                    composite_alpha,
                    regime,
                    gics_sector,
                    country,
                    previous_weight,
                    trade_weight,
                    turnover_cap,
                    realized_turnover,
                    turnover_limited
                FROM {schema}.portfolio_target_positions
                WHERE portfolio_name = :portfolio_name
                  AND as_of_date = :prev_as_of_date
                ORDER BY selection_rank NULLS LAST, symbol
                """
                ),  # nosec B608 - schema identifier is validated before interpolation
                {"portfolio_name": portfolio_name, "prev_as_of_date": prev_as_of_date},
            )
            .mappings()
            .all()
        )
    return prev_as_of_date, [dict(row) for row in rows]


def _portfolio_name(config: Optional[Dict[str, Any]] = None) -> str:
    return str(
        ((config or {}).get("portfolio_construction") or {}).get("portfolio_name")
        or "cw2_core_equity"
    )


def _target_generation_frequency(config: Optional[Dict[str, Any]] = None) -> str:
    portfolio_cfg = (config or {}).get("portfolio_construction") or {}
    value = str(portfolio_cfg.get("target_generation_frequency") or "monthly").strip()
    lowered = value.lower()
    if lowered in {"monthly", "quarterly", "semiannual", "annual"}:
        return lowered
    return "monthly"


def _is_target_refresh_month(as_of_date: date, *, frequency: str) -> bool:
    if frequency == "monthly":
        return True
    if frequency == "quarterly":
        return as_of_date.month in {3, 6, 9, 12}
    if frequency == "semiannual":
        return as_of_date.month in {6, 12}
    if frequency == "annual":
        return as_of_date.month == 12
    return True


def _should_refresh_portfolio_targets(
    as_of_date: date,
    *,
    config: Optional[Dict[str, Any]] = None,
    previous_target_records: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    if not previous_target_records:
        return True
    return _is_target_refresh_month(
        as_of_date,
        frequency=_target_generation_frequency(config),
    )


def _build_carried_forward_portfolio_targets(
    *,
    as_of_date: date,
    portfolio_name: str,
    previous_target_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    carried_records: List[Dict[str, Any]] = []
    for record in previous_target_records:
        target_weight = _safe_float(record.get("target_weight"))
        carried_records.append(
            {
                "as_of_date": as_of_date,
                "portfolio_name": portfolio_name,
                "symbol": record.get("symbol"),
                "selection_rank": record.get("selection_rank"),
                "selected_signal": bool(record.get("selected_signal", True)),
                "target_weight": target_weight,
                "weighting_scheme": record.get("weighting_scheme"),
                "ranking_mode": record.get("ranking_mode"),
                "ranking_score": record.get("ranking_score"),
                "composite_alpha": record.get("composite_alpha"),
                "regime": record.get("regime"),
                "gics_sector": record.get("gics_sector"),
                "country": record.get("country"),
                "previous_weight": target_weight,
                "trade_weight": 0.0 if target_weight is not None else None,
                "turnover_cap": record.get("turnover_cap"),
                "realized_turnover": 0.0 if target_weight is not None else None,
                "turnover_limited": False,
                "source": "frequency_carry",
            }
        )
    return carried_records


def _risk_factor_names(config: Optional[Dict[str, Any]] = None) -> List[str]:
    optional_blacklists = ((config or {}).get("risk_overlay") or {}).get(
        "optional_percentile_blacklists"
    ) or []
    risk_columns = ["log_market_cap", "liquidity_20d", "volatility_60d"]
    for blacklist in optional_blacklists:
        column = str(blacklist.get("column") or "").strip()
        if column and column not in risk_columns:
            risk_columns.append(column)
    return risk_columns


def _regime_history_lookback_days(config: Optional[Dict[str, Any]] = None) -> int:
    cfg = (config or {}).get("regime", {})
    return max(1, int(cfg.get("history_lookback_days", 60)))


def _portfolio_covariance_config(
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return ((config or {}).get("portfolio_construction") or {}).get("covariance") or {}


def _requires_portfolio_covariance(config: Optional[Dict[str, Any]] = None) -> bool:
    portfolio_cfg = (config or {}).get("portfolio_construction") or {}
    weighting = str(portfolio_cfg.get("weighting") or "equal").strip().lower()
    covariance_cfg = _portfolio_covariance_config(config)
    return weighting == "mean_variance" or bool(
        covariance_cfg.get("always_build", False)
    )


def _benchmark_ticker(config: Optional[Dict[str, Any]] = None) -> str:
    return str(((config or {}).get("backtest") or {}).get("benchmark_ticker") or "SPY")


def _build_portfolio_covariance_context(
    as_of_date: date,
    symbols: List[str],
    config: Optional[Dict[str, Any]] = None,
) -> tuple[Any, Dict[str, Any]]:
    import pandas as pd

    if not _requires_portfolio_covariance(config):
        return pd.DataFrame(), {}

    clean_symbols = sorted(
        {
            str(sym).strip()
            for sym in symbols
            if str(sym).strip() and str(sym).strip() != "_MACRO"
        }
    )
    if not clean_symbols:
        return pd.DataFrame(), {}

    repo_root = str(_repo_root())
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from team_Pearson.coursework_two.modules.backtest.data_loader import (
        _build_portfolio_covariance_context as build_covariance_context,
    )

    return build_covariance_context(
        get_db_engine(),
        as_of_date,
        clean_symbols,
        config or {},
    )


def _universe_guard_thresholds(
    config: Optional[Dict[str, Any]] = None,
) -> tuple[int, int]:
    guard_cfg = (config or {}).get("pipeline_guards", {})
    preprocessing_cfg = (config or {}).get("preprocessing", {})
    portfolio_cfg = (config or {}).get("portfolio_construction", {})

    default_scoring = max(1, int(preprocessing_cfg.get("min_observations", 30)))
    default_investable = max(
        1,
        int(
            max(
                portfolio_cfg.get("min_names", 15),
                portfolio_cfg.get("min_candidate_pool", 10),
            )
        ),
    )
    min_scoring_universe = max(
        1, int(guard_cfg.get("min_scoring_universe", default_scoring))
    )
    min_investable_universe = max(
        1, int(guard_cfg.get("min_investable_universe", default_investable))
    )
    return min_scoring_universe, min_investable_universe


def _evaluate_universe_guards(
    *,
    scoring_universe: int,
    investable_universe: int,
    config: Optional[Dict[str, Any]] = None,
) -> UniverseGuardResult:
    min_scoring_universe, min_investable_universe = _universe_guard_thresholds(config)
    allow_factor_scoring = scoring_universe >= min_scoring_universe
    allow_portfolio_construction = (
        allow_factor_scoring and investable_universe >= min_investable_universe
    )
    return UniverseGuardResult(
        min_scoring_universe=min_scoring_universe,
        min_investable_universe=min_investable_universe,
        scoring_universe=scoring_universe,
        investable_universe=investable_universe,
        allow_factor_scoring=allow_factor_scoring,
        allow_portfolio_construction=allow_portfolio_construction,
    )


def _build_cw2_pit_snapshot(
    *,
    requested_as_of_date: date,
    symbols: List[str],
    config: Optional[Dict[str, Any]] = None,
) -> Optional[CW2PITSnapshot]:
    as_of_date = _resolve_feature_as_of_date(requested_as_of_date, symbols)
    if as_of_date is None:
        return None

    factor_names = sorted(
        set(_cw2_factor_names(config) + _risk_factor_names(config) + ["vix_close"])
    )
    factor_df = _load_latest_factor_snapshot(
        as_of_date,
        symbols + ["_MACRO"],
        factor_names=factor_names,
    )
    financial_publish_cutoff_date = requested_as_of_date
    financial_df = _load_financial_snapshot(
        as_of_date,
        financial_publish_cutoff_date,
        symbols,
    )
    company_info = _load_company_info(symbols)
    company_info_lookup = _company_info_map(company_info)
    sector_map = {
        sym: str(info.get("gics_sector") or "Unknown")
        for sym, info in company_info_lookup.items()
    }
    vix_level = _extract_vix_level(factor_df, as_of_date)
    vix_history = _load_macro_factor_history(
        as_of_date,
        "vix_close",
        lookback_days=_regime_history_lookback_days(config),
    )
    term_spread_level, term_spread_history = _load_term_spread_context(
        as_of_date,
        lookback_days=_regime_history_lookback_days(config),
    )
    risk_data = _extract_risk_data(factor_df, config)
    covariance_matrix, covariance_meta = _build_portfolio_covariance_context(
        as_of_date,
        symbols,
        config=config,
    )
    previous_positions = _load_previous_portfolio_positions(
        as_of_date,
        portfolio_name=_portfolio_name(config),
    )
    return CW2PITSnapshot(
        requested_as_of_date=requested_as_of_date,
        as_of_date=as_of_date,
        financial_publish_cutoff_date=financial_publish_cutoff_date,
        factor_df=factor_df,
        financial_df=financial_df,
        company_info=company_info,
        company_info_lookup=company_info_lookup,
        sector_map=sector_map,
        vix_level=vix_level,
        vix_history=vix_history,
        risk_data=risk_data,
        covariance_matrix=covariance_matrix,
        covariance_meta=covariance_meta,
        previous_positions=previous_positions,
        term_spread_level=term_spread_level,
        term_spread_history=term_spread_history,
    )


def _extract_risk_data(factor_df: Any, config: Optional[Dict[str, Any]] = None) -> Any:
    import pandas as pd

    if factor_df is None or factor_df.empty:
        return pd.DataFrame(
            columns=["symbol", "log_market_cap", "liquidity_20d", "volatility_60d"]
        )

    risk_columns = _risk_factor_names(config)

    day = factor_df[factor_df["symbol"] != "_MACRO"].copy()
    if day.empty:
        return pd.DataFrame(columns=["symbol", *risk_columns])

    pivot = day.pivot_table(
        index="symbol", columns="factor_name", values="factor_value", aggfunc="last"
    )
    for column in risk_columns:
        if column not in pivot.columns:
            pivot[column] = None
    out = pivot[risk_columns].reset_index()
    return out


def _company_info_map(company_info: Any) -> Dict[str, Dict[str, Any]]:
    if company_info is None:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        records = company_info.to_dict(orient="records")
    except Exception:
        records = []
    for rec in records:
        symbol = str(rec.get("symbol") or "").strip()
        if not symbol:
            continue
        out[symbol] = {
            "security": rec.get("security"),
            "gics_sector": str(rec.get("gics_sector") or "Unknown"),
            "country": rec.get("country"),
        }
    return out


def _factor_scoring_symbols(
    universe_screen_records: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> set[str]:
    cfg = (config or {}).get("investable_universe", {})
    min_log_mcap = _safe_float(cfg.get("min_market_cap_log", 20.0))

    symbols: set[str] = set()
    for rec in universe_screen_records:
        sym = str(rec.get("symbol") or "").strip()
        if not sym or not bool(rec.get("pass_country")):
            continue
        mcap = _safe_float(rec.get("log_market_cap"))
        pass_mcap_floor = (
            True
            if min_log_mcap is None
            else (mcap is not None and mcap >= min_log_mcap)
        )
        if pass_mcap_floor:
            symbols.add(sym)
    return symbols


def _safe_float(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(v) for v in value]
    if isinstance(value, Decimal):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date,)):
        return value.isoformat()
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return _json_safe_value(value.item())
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug(
                "cw2_features: item() JSON coercion failed for %r: %s", value, exc
            )
    return value


def _json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(
        _json_safe_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def _latest_frame_date(frame: Any, candidate_columns: Iterable[str]) -> Optional[str]:
    if frame is None or getattr(frame, "empty", True):
        return None
    for column in candidate_columns:
        if column not in frame.columns:
            continue
        series = pd.to_datetime(frame[column], errors="coerce")
        latest = series.max()
        if pd.isna(latest):
            continue
        return latest.date().isoformat()
    return None


def _latest_position_date(
    positions: Iterable[Dict[str, Any]], candidate_keys: Iterable[str]
) -> Optional[str]:
    latest: Optional[date] = None
    for record in positions:
        for key in candidate_keys:
            raw = str(record.get(key) or "").strip()
            if not raw:
                continue
            try:
                parsed = date.fromisoformat(raw[:10])
            except ValueError:
                continue
            if latest is None or parsed > latest:
                latest = parsed
    return latest.isoformat() if latest is not None else None


def _sanitize_row(row: Dict[str, Any], allowed_cols: Iterable[str]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for column in allowed_cols:
        value = row.get(column)
        if isinstance(value, float) and not math.isfinite(value):
            value = None
        if value is not None and column.endswith("_json"):
            value = _json_dumps(value) if not isinstance(value, str) else value
        clean[column] = value
    return clean


def _upsert_rows(
    *,
    table_name: str,
    rows: List[Dict[str, Any]],
    allowed_cols: List[str],
    conflict_cols: List[str],
) -> int:
    if not rows:
        return 0

    engine = get_db_engine()
    schema = _db_schema()
    safe_table_name = _validated_identifier(table_name, label="table_name")
    safe_allowed_cols = _validated_identifier_list(allowed_cols, label="column")
    safe_conflict_cols = _validated_identifier_list(
        conflict_cols, label="conflict_column"
    )
    sanitized_rows = [_sanitize_row(row, allowed_cols) for row in rows]

    insert_cols = ", ".join(safe_allowed_cols)
    bind_cols = ", ".join(
        f"CAST(:{col} AS jsonb)" if col.endswith("_json") else f":{col}"
        for col in safe_allowed_cols
    )
    update_cols = [col for col in safe_allowed_cols if col not in safe_conflict_cols]
    update_sql = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)

    sql = text(f"""
        INSERT INTO {schema}.{safe_table_name} ({insert_cols})
        VALUES ({bind_cols})
        ON CONFLICT ({", ".join(safe_conflict_cols)})
        DO UPDATE SET {update_sql}, updated_at = NOW()
        """)  # nosec B608 - schema, table, and column identifiers are validated

    with engine.begin() as conn:
        conn.execute(sql, sanitized_rows)
    return len(sanitized_rows)


def _replace_rows_for_scope(
    *,
    table_name: str,
    rows: List[Dict[str, Any]],
    allowed_cols: List[str],
    conflict_cols: List[str],
    scope_cols: List[str],
    scope_values: Dict[str, Any],
) -> int:
    """Replace all rows inside a logical scope, then upsert the current snapshot rows.

    This keeps reruns idempotent for whole-snapshot outputs such as
    ``portfolio_target_positions`` where an empty current result set should clear
    stale rows from older, looser configurations.
    """
    if not scope_cols:
        raise ValueError("scope_cols cannot be empty")
    missing_scope = [col for col in scope_cols if col not in scope_values]
    if missing_scope:
        raise ValueError(
            f"scope_values missing required keys for {table_name}: {missing_scope}"
        )

    engine = get_db_engine()
    schema = _db_schema()
    safe_table_name = _validated_identifier(table_name, label="table_name")
    safe_scope_cols = _validated_identifier_list(scope_cols, label="scope_column")
    delete_params = {col: scope_values[col] for col in scope_cols}
    where_sql = " AND ".join(f"{col} = :{col}" for col in safe_scope_cols)
    delete_sql = text(
        f"DELETE FROM {schema}.{safe_table_name} WHERE {where_sql}"
    )  # nosec B608 - schema, table, and scope identifiers are validated

    with engine.begin() as conn:
        conn.execute(delete_sql, delete_params)

    return _upsert_rows(
        table_name=table_name,
        rows=rows,
        allowed_cols=allowed_cols,
        conflict_cols=conflict_cols,
    )


def _average(values: List[Optional[float]]) -> Optional[float]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _first_non_null(values: List[Any]) -> Optional[str]:
    for value in values:
        if value is not None and str(value).strip():
            return str(value)
    return None


def _aggregate_sector_weights(records: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for rec in records:
        sector = str(rec.get("gics_sector") or "Unknown")
        out[sector] = out.get(sector, 0.0) + float(
            _safe_float(rec.get("target_weight")) or 0.0
        )
    return {k: round(v, 8) for k, v in sorted(out.items())}


def _write_feature_snapshot_registry(
    *,
    snapshot_id: str,
    requested_as_of: date,
    snapshot: CW2PITSnapshot,
    guard: UniverseGuardResult,
    config: Dict[str, Any],
) -> str:
    engine = get_db_engine()
    version_bundle = select_version_fields(
        resolve_version_bundle(config), FEATURE_VERSION_KEYS
    )
    covariance_meta = dict(snapshot.covariance_meta or {})
    covariance_method = covariance_meta.get("covariance_method") or covariance_meta.get(
        "method"
    )
    covariance_symbol_count = covariance_meta.get("symbol_count")
    if covariance_symbol_count is None and snapshot.covariance_matrix is not None:
        try:
            covariance_symbol_count = int(
                len(getattr(snapshot.covariance_matrix, "columns", []))
            )
        except Exception:
            covariance_symbol_count = None
    row = {
        "snapshot_id": snapshot_id,
        "requested_as_of_date": requested_as_of,
        "as_of_date": snapshot.as_of_date,
        "financial_publish_cutoff_date": snapshot.financial_publish_cutoff_date,
        "snapshot_status": (
            "completed"
            if guard.allow_factor_scoring and guard.allow_portfolio_construction
            else (
                "blocked_portfolio" if guard.allow_factor_scoring else "blocked_scoring"
            )
        ),
        "scoring_universe": int(guard.scoring_universe),
        "investable_universe": int(guard.investable_universe),
        "min_scoring_universe": int(guard.min_scoring_universe),
        "min_investable_universe": int(guard.min_investable_universe),
        "allow_factor_scoring": bool(guard.allow_factor_scoring),
        "allow_portfolio_construction": bool(guard.allow_portfolio_construction),
        "factor_row_count": int(
            len(snapshot.factor_df.index) if hasattr(snapshot.factor_df, "index") else 0
        ),
        "financial_row_count": int(
            len(snapshot.financial_df.index)
            if hasattr(snapshot.financial_df, "index")
            else 0
        ),
        "previous_position_count": int(len(snapshot.previous_positions or [])),
        "vix_level": snapshot.vix_level,
        **version_bundle,
        "covariance_method": covariance_method,
        "covariance_symbol_count": covariance_symbol_count,
        "config_snapshot": _json_dumps(
            {
                "pipeline_guards": config.get("pipeline_guards") or {},
                "portfolio_construction": config.get("portfolio_construction") or {},
                "regime": config.get("regime") or {},
                "financial_publish_cutoff_date": (
                    snapshot.financial_publish_cutoff_date.isoformat()
                ),
                "governance": {"versions": version_bundle},
            }
        ),
    }
    sql = text("""
        INSERT INTO systematic_equity.feature_snapshot_registry (
            snapshot_id,
            requested_as_of_date,
            as_of_date,
            snapshot_status,
            scoring_universe,
            investable_universe,
            min_scoring_universe,
            min_investable_universe,
            allow_factor_scoring,
            allow_portfolio_construction,
            factor_row_count,
            financial_row_count,
            previous_position_count,
            vix_level,
            model_version,
            factor_definition_version,
            covariance_method,
            covariance_method_version,
            risk_overlay_policy_version,
            covariance_symbol_count,
            config_snapshot
        ) VALUES (
            :snapshot_id,
            :requested_as_of_date,
            :as_of_date,
            :snapshot_status,
            :scoring_universe,
            :investable_universe,
            :min_scoring_universe,
            :min_investable_universe,
            :allow_factor_scoring,
            :allow_portfolio_construction,
            :factor_row_count,
            :financial_row_count,
            :previous_position_count,
            :vix_level,
            :model_version,
            :factor_definition_version,
            :covariance_method,
            :covariance_method_version,
            :risk_overlay_policy_version,
            :covariance_symbol_count,
            CAST(:config_snapshot AS jsonb)
        )
        ON CONFLICT (requested_as_of_date, as_of_date) DO UPDATE
        SET snapshot_status = EXCLUDED.snapshot_status,
            scoring_universe = EXCLUDED.scoring_universe,
            investable_universe = EXCLUDED.investable_universe,
            min_scoring_universe = EXCLUDED.min_scoring_universe,
            min_investable_universe = EXCLUDED.min_investable_universe,
            allow_factor_scoring = EXCLUDED.allow_factor_scoring,
            allow_portfolio_construction = EXCLUDED.allow_portfolio_construction,
            factor_row_count = EXCLUDED.factor_row_count,
            financial_row_count = EXCLUDED.financial_row_count,
            previous_position_count = EXCLUDED.previous_position_count,
            vix_level = EXCLUDED.vix_level,
            model_version = EXCLUDED.model_version,
            factor_definition_version = EXCLUDED.factor_definition_version,
            covariance_method = EXCLUDED.covariance_method,
            covariance_method_version = EXCLUDED.covariance_method_version,
            risk_overlay_policy_version = EXCLUDED.risk_overlay_policy_version,
            covariance_symbol_count = EXCLUDED.covariance_symbol_count,
            config_snapshot = EXCLUDED.config_snapshot,
            updated_at = NOW()
        RETURNING snapshot_id
        """)
    with engine.begin() as conn:
        stored_id = conn.execute(sql, row).scalar()
    return str(stored_id or snapshot_id)


def _write_model_input_manifest(
    *,
    snapshot_id: str,
    as_of_date: date,
    manifest_type: str,
    payload: Dict[str, Any],
) -> None:
    engine = get_db_engine()
    delete_sql = text("""
        DELETE FROM systematic_equity.model_input_manifests
        WHERE snapshot_id = :snapshot_id
          AND manifest_type = :manifest_type
        """)
    insert_sql = text("""
        INSERT INTO systematic_equity.model_input_manifests (
            manifest_id,
            snapshot_id,
            as_of_date,
            manifest_type,
            payload_json
        ) VALUES (
            :manifest_id,
            :snapshot_id,
            :as_of_date,
            :manifest_type,
            CAST(:payload_json AS jsonb)
        )
        """)
    with engine.begin() as conn:
        conn.execute(
            delete_sql,
            {
                "snapshot_id": snapshot_id,
                "manifest_type": manifest_type,
            },
        )
        conn.execute(
            insert_sql,
            {
                "manifest_id": str(uuid.uuid4()),
                "snapshot_id": snapshot_id,
                "as_of_date": as_of_date,
                "manifest_type": manifest_type,
                "payload_json": _json_dumps(payload),
            },
        )


def _write_portfolio_snapshot_registry(
    *,
    snapshot_id: str,
    as_of_date: date,
    portfolio_name: str,
    portfolio_target_records: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> None:
    engine = get_db_engine()
    version_bundle = select_version_fields(
        resolve_version_bundle(config), FEATURE_VERSION_KEYS
    )
    source_values = {
        str(rec.get("source") or "").strip().lower()
        for rec in portfolio_target_records
        if rec.get("source") is not None
    }
    snapshot_status = (
        "blocked_portfolio"
        if not portfolio_target_records
        else (
            "carried_forward"
            if source_values and source_values <= {"frequency_carry"}
            else "completed"
        )
    )
    row = {
        "snapshot_id": snapshot_id,
        "as_of_date": as_of_date,
        "portfolio_name": portfolio_name,
        "snapshot_status": snapshot_status,
        "num_positions": len(portfolio_target_records),
        "gross_target_weight": sum(
            _safe_float(rec.get("target_weight")) or 0.0
            for rec in portfolio_target_records
        ),
        "avg_composite_alpha": _average(
            [
                _safe_float(rec.get("composite_alpha"))
                for rec in portfolio_target_records
            ]
        ),
        "expected_turnover": sum(
            abs(_safe_float(rec.get("trade_weight")) or 0.0)
            for rec in portfolio_target_records
        ),
        "weighting_scheme": _first_non_null(
            [rec.get("weighting_scheme") for rec in portfolio_target_records]
        ),
        "ranking_mode": _first_non_null(
            [rec.get("ranking_mode") for rec in portfolio_target_records]
        ),
        "regime": _first_non_null(
            [rec.get("regime") for rec in portfolio_target_records]
        ),
        **version_bundle,
        "summary_json": _json_dumps(
            {
                "top_symbols": [
                    str(rec["symbol"]) for rec in portfolio_target_records[:10]
                ],
                "sector_weights": _aggregate_sector_weights(portfolio_target_records),
                "snapshot_status": snapshot_status,
                "sources": sorted(source_values),
                "version_bundle": version_bundle,
            }
        ),
    }
    sql = text("""
        INSERT INTO systematic_equity.portfolio_snapshot_registry (
            snapshot_id,
            as_of_date,
            portfolio_name,
            snapshot_status,
            num_positions,
            gross_target_weight,
            avg_composite_alpha,
            expected_turnover,
            weighting_scheme,
            ranking_mode,
            regime,
            model_version,
            factor_definition_version,
            covariance_method_version,
            risk_overlay_policy_version,
            summary_json
        ) VALUES (
            :snapshot_id,
            :as_of_date,
            :portfolio_name,
            :snapshot_status,
            :num_positions,
            :gross_target_weight,
            :avg_composite_alpha,
            :expected_turnover,
            :weighting_scheme,
            :ranking_mode,
            :regime,
            :model_version,
            :factor_definition_version,
            :covariance_method_version,
            :risk_overlay_policy_version,
            CAST(:summary_json AS jsonb)
        )
        ON CONFLICT (as_of_date, portfolio_name) DO UPDATE
        SET snapshot_id = EXCLUDED.snapshot_id,
            snapshot_status = EXCLUDED.snapshot_status,
            num_positions = EXCLUDED.num_positions,
            gross_target_weight = EXCLUDED.gross_target_weight,
            avg_composite_alpha = EXCLUDED.avg_composite_alpha,
            expected_turnover = EXCLUDED.expected_turnover,
            weighting_scheme = EXCLUDED.weighting_scheme,
            ranking_mode = EXCLUDED.ranking_mode,
            regime = EXCLUDED.regime,
            model_version = EXCLUDED.model_version,
            factor_definition_version = EXCLUDED.factor_definition_version,
            covariance_method_version = EXCLUDED.covariance_method_version,
            risk_overlay_policy_version = EXCLUDED.risk_overlay_policy_version,
            summary_json = EXCLUDED.summary_json,
            updated_at = NOW()
        """)
    with engine.begin() as conn:
        conn.execute(sql, row)


def _build_portfolio_input_manifest_payload(
    *,
    requested_as_of: date,
    snapshot: CW2PITSnapshot,
    config: Dict[str, Any],
    version_bundle: Dict[str, Any],
    covariance_artifact: Optional[Dict[str, Any]],
    diagnostic_summary: Optional[Dict[str, Any]],
    diagnostic_row_count: int,
) -> Dict[str, Any]:
    construction_summary = dict(diagnostic_summary or {})
    construction_summary.update(
        {
            "row_count": int(diagnostic_row_count),
            "table_name": "systematic_equity.portfolio_construction_diagnostics",
        }
    )
    source_table_row_counts = {
        "factor_snapshot_rows": int(
            len(snapshot.factor_df.index) if hasattr(snapshot.factor_df, "index") else 0
        ),
        "financial_snapshot_rows": int(
            len(snapshot.financial_df.index)
            if hasattr(snapshot.financial_df, "index")
            else 0
        ),
        "company_info_rows": int(
            len(snapshot.company_info.index)
            if hasattr(snapshot.company_info, "index")
            else 0
        ),
        "previous_position_rows": int(len(snapshot.previous_positions or [])),
    }
    latest_upstream_dates = {
        "factor_observation_date": _latest_frame_date(
            snapshot.factor_df,
            ["observation_date", "as_of_date", "period_end_date", "date"],
        ),
        "financial_observation_date": _latest_frame_date(
            snapshot.financial_df,
            [
                "observation_date",
                "statement_date",
                "filing_date",
                "report_date",
                "period_end_date",
                "date",
            ],
        ),
        "company_info_date": _latest_frame_date(
            snapshot.company_info,
            ["as_of_date", "updated_at", "observation_date", "date"],
        ),
        "previous_position_date": _latest_position_date(
            snapshot.previous_positions,
            ["as_of_date", "rebalance_date", "execution_date", "period_end_date"],
        ),
    }
    return {
        "requested_as_of_date": requested_as_of.isoformat(),
        "as_of_date": snapshot.as_of_date.isoformat(),
        "financial_publish_cutoff_date": (
            snapshot.financial_publish_cutoff_date.isoformat()
        ),
        "portfolio_name": _portfolio_name(config),
        "previous_positions": snapshot.previous_positions,
        "source_table_names": {
            "factor_snapshot": "systematic_equity.factor_observations",
            "financial_snapshot": "systematic_equity.financial_observations",
            "company_info_snapshot": "cw1.company_info_snapshot",
            "previous_positions": "systematic_equity.portfolio_target_positions",
        },
        "source_table_row_counts": source_table_row_counts,
        "latest_upstream_dates": latest_upstream_dates,
        "covariance_meta": snapshot.covariance_meta or {},
        "covariance_artifact": covariance_artifact,
        "portfolio_construction_config": config.get("portfolio_construction") or {},
        "regime_config": config.get("regime") or {},
        "construction_diagnostics": construction_summary,
        "version_bundle": version_bundle,
    }


def _write_cw2_quality_gate(
    *,
    requested_as_of: date,
    snapshot: CW2PITSnapshot,
    guard: UniverseGuardResult,
    universe_screen_records: List[Dict[str, Any]],
    sub_score_records: List[Dict[str, Any]],
    factor_score_records: List[Dict[str, Any]],
    risk_overlay_records: List[Dict[str, Any]],
    portfolio_target_records: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> None:
    quality_cfg = dict(config.get("quality_gates") or {})
    portfolio_cfg = dict(config.get("portfolio_construction") or {})
    scoring_universe = max(1, int(guard.scoring_universe))
    risk_pass_count = sum(1 for rec in risk_overlay_records if rec.get("pass_all"))
    factor_score_coverage = len(factor_score_records) / scoring_universe
    risk_pass_rate = risk_pass_count / max(1, len(risk_overlay_records))
    shift_days = abs((snapshot.as_of_date - requested_as_of).days)
    portfolio_target_floor = int(quality_cfg.get("min_portfolio_targets", 0))
    portfolio_warning_ceiling = max(
        portfolio_target_floor,
        int(portfolio_cfg.get("hybrid_min_n", portfolio_target_floor)),
    )
    portfolio_target_rows = len(portfolio_target_records)
    report = {
        "requested_as_of_date": requested_as_of.isoformat(),
        "as_of_date": snapshot.as_of_date.isoformat(),
        "financial_publish_cutoff_date": (
            snapshot.financial_publish_cutoff_date.isoformat()
        ),
        "shift_days": shift_days,
        "universe_screen_rows": len(universe_screen_records),
        "scoring_universe": guard.scoring_universe,
        "investable_universe": guard.investable_universe,
        "sub_score_rows": len(sub_score_records),
        "factor_score_rows": len(factor_score_records),
        "risk_overlay_rows": len(risk_overlay_records),
        "portfolio_target_rows": portfolio_target_rows,
        "portfolio_target_floor": portfolio_target_floor,
        "portfolio_target_warning_ceiling": portfolio_warning_ceiling,
        "portfolio_target_breadth_margin": portfolio_target_rows
        - portfolio_target_floor,
        "factor_score_coverage_vs_scoring": round(factor_score_coverage, 6),
        "risk_pass_rate": round(risk_pass_rate, 6),
        "vix_available": snapshot.vix_level is not None,
    }
    failures: List[str] = []
    warnings: List[str] = []
    if len(sub_score_records) < int(quality_cfg.get("min_sub_score_rows", 0)):
        failures.append("sub_score_rows_below_threshold")
    if len(factor_score_records) < int(quality_cfg.get("min_factor_score_rows", 0)):
        failures.append("factor_score_rows_below_threshold")
    if len(risk_overlay_records) < int(quality_cfg.get("min_risk_overlay_rows", 0)):
        failures.append("risk_overlay_rows_below_threshold")
    if portfolio_target_rows < portfolio_target_floor:
        failures.append("portfolio_target_rows_below_threshold")
    elif portfolio_target_rows < portfolio_warning_ceiling:
        warnings.append("portfolio_target_rows_near_threshold")
    if factor_score_coverage < float(
        quality_cfg.get("min_factor_score_coverage_vs_scoring", 0.0)
    ):
        failures.append("factor_score_coverage_below_threshold")
    if risk_pass_rate < float(quality_cfg.get("min_risk_pass_rate", 0.0)):
        failures.append("risk_pass_rate_below_threshold")
    if shift_days > int(quality_cfg.get("max_as_of_date_shift_days", 9999)):
        failures.append("as_of_shift_exceeds_threshold")
    report["failures"] = failures
    report["warnings"] = warnings
    report["passed"] = len(failures) == 0
    report["row_count"] = portfolio_target_rows
    report["stage_name"] = "cw2_feature_pipeline"
    report["contract_version"] = "cw2-quality-v2"
    write_quality_snapshot(
        run_id=f"cw2::{requested_as_of.isoformat()}::{snapshot.as_of_date.isoformat()}",
        run_date=snapshot.as_of_date.isoformat(),
        dataset_name="cw2_feature_pipeline",
        quality_report=report,
    )


def build_and_load_cw2_features(
    *,
    run_date: str,
    symbols: List[str],
    config_path: Optional[str] = None,
) -> Dict[str, int]:
    """Build and persist CW2 universe screen, first-level factors, risk overlay, and portfolio targets."""
    modules = _import_cw2_modules()
    if len(modules) == 5:
        (
            compute_factor_scores_for_date,
            compute_composite_alpha,
            apply_risk_overlay,
            build_investable_universe,
            build_portfolio_targets,
        ) = modules
        from team_Pearson.coursework_two.modules.feature.composite_alpha import (
            resolve_regime_from_config,
        )
    else:
        (
            compute_factor_scores_for_date,
            compute_composite_alpha,
            resolve_regime_from_config,
            apply_risk_overlay,
            build_investable_universe,
            build_portfolio_targets,
        ) = modules

    _ensure_cw2_schema()
    cfg = _load_cw2_config(config_path=config_path)
    requested_as_of = date.fromisoformat(run_date)
    snapshot = _build_cw2_pit_snapshot(
        requested_as_of_date=requested_as_of,
        symbols=symbols,
        config=cfg,
    )
    if snapshot is None:
        logger.warning(
            "cw2_features: no factor snapshot available on or before %s",
            requested_as_of,
        )
        return {
            "universe_screen": 0,
            "sub_scores": 0,
            "factor_scores": 0,
            "risk_overlay": 0,
            "portfolio_targets": 0,
            "portfolio_diagnostics": 0,
            "covariance_artifact_stored": 0,
            "as_of_date_shifted": 0,
        }

    universe_screen_records = build_investable_universe(
        snapshot.risk_data,
        snapshot.company_info,
        as_of_date=snapshot.as_of_date,
        config=cfg,
    )
    scoring_symbols = _factor_scoring_symbols(universe_screen_records, cfg)
    investable_symbols = {
        str(rec["symbol"]) for rec in universe_screen_records if rec.get("pass_all")
    }
    guard = _evaluate_universe_guards(
        scoring_universe=len(scoring_symbols),
        investable_universe=len(investable_symbols),
        config=cfg,
    )
    snapshot_id = str(uuid.uuid4())
    version_bundle = select_version_fields(
        resolve_version_bundle(cfg), FEATURE_VERSION_KEYS
    )
    logger.info(
        "cw2_features: scoring_universe=%d investable_universe=%d requested_as_of=%s as_of=%s min_scoring=%d min_investable=%d",
        guard.scoring_universe,
        guard.investable_universe,
        requested_as_of,
        snapshot.as_of_date,
        guard.min_scoring_universe,
        guard.min_investable_universe,
    )
    shifted = 1 if snapshot.as_of_date != requested_as_of else 0
    portfolio_name = _portfolio_name(cfg)
    portfolio_scope = {
        "as_of_date": snapshot.as_of_date,
        "portfolio_name": portfolio_name,
    }
    snapshot_id = _write_feature_snapshot_registry(
        snapshot_id=snapshot_id,
        requested_as_of=requested_as_of,
        snapshot=snapshot,
        guard=guard,
        config=cfg,
    )
    covariance_artifact = _persist_covariance_artifact(
        snapshot_id=snapshot_id,
        as_of_date=snapshot.as_of_date,
        portfolio_name=portfolio_name,
        covariance_matrix=snapshot.covariance_matrix,
        covariance_meta=snapshot.covariance_meta,
    )

    universe_count = _upsert_rows(
        table_name="feature_universe_screen",
        rows=universe_screen_records,
        allowed_cols=[
            "as_of_date",
            "symbol",
            "country",
            "gics_sector",
            "log_market_cap",
            "liquidity_20d",
            "pass_country",
            "pass_market_cap",
            "pass_liquidity",
            "pass_all",
        ],
        conflict_cols=["as_of_date", "symbol"],
    )
    _write_model_input_manifest(
        snapshot_id=snapshot_id,
        as_of_date=snapshot.as_of_date,
        manifest_type="feature_input",
        payload={
            "requested_as_of_date": requested_as_of.isoformat(),
            "as_of_date": snapshot.as_of_date.isoformat(),
            "financial_publish_cutoff_date": (
                snapshot.financial_publish_cutoff_date.isoformat()
            ),
            "requested_symbol_count": len(symbols),
            "factor_row_count": int(
                len(snapshot.factor_df.index)
                if hasattr(snapshot.factor_df, "index")
                else 0
            ),
            "financial_row_count": int(
                len(snapshot.financial_df.index)
                if hasattr(snapshot.financial_df, "index")
                else 0
            ),
            "company_info_count": int(
                len(snapshot.company_info.index)
                if hasattr(snapshot.company_info, "index")
                else 0
            ),
            "scoring_symbols": sorted(scoring_symbols),
            "factor_names": _cw2_factor_names(cfg),
            "sector_map": {
                sym: snapshot.sector_map.get(sym, "Unknown")
                for sym in sorted(scoring_symbols)
            },
            "version_bundle": version_bundle,
        },
    )
    _write_model_input_manifest(
        snapshot_id=snapshot_id,
        as_of_date=snapshot.as_of_date,
        manifest_type="risk_input",
        payload={
            "requested_as_of_date": requested_as_of.isoformat(),
            "as_of_date": snapshot.as_of_date.isoformat(),
            "financial_publish_cutoff_date": (
                snapshot.financial_publish_cutoff_date.isoformat()
            ),
            "risk_columns": _risk_factor_names(cfg),
            "investable_symbols": sorted(investable_symbols),
            "risk_row_count": int(
                len(snapshot.risk_data.index)
                if hasattr(snapshot.risk_data, "index")
                else 0
            ),
            "vix_level": snapshot.vix_level,
            "vix_history_length": len(snapshot.vix_history or []),
            "risk_overlay_config": cfg.get("risk_overlay") or {},
            "version_bundle": version_bundle,
        },
    )
    if not guard.allow_factor_scoring:
        _replace_rows_for_scope(
            table_name="portfolio_target_positions",
            rows=[],
            allowed_cols=[
                "as_of_date",
                "portfolio_name",
                "symbol",
                "selection_rank",
                "selected_signal",
                "target_weight",
                "weighting_scheme",
                "ranking_mode",
                "ranking_score",
                "composite_alpha",
                "regime",
                "gics_sector",
                "country",
                "previous_weight",
                "trade_weight",
                "turnover_cap",
                "realized_turnover",
                "turnover_limited",
            ],
            conflict_cols=["as_of_date", "portfolio_name", "symbol"],
            scope_cols=["as_of_date", "portfolio_name"],
            scope_values=portfolio_scope,
        )
        _replace_rows_for_scope(
            table_name="portfolio_construction_diagnostics",
            rows=[],
            allowed_cols=[
                "snapshot_id",
                "as_of_date",
                "portfolio_name",
                "symbol",
                "candidate_rank",
                "selected_signal",
                "selection_drop_reason",
                "gics_sector",
                "country",
                "ranking_mode",
                "ranking_score",
                "composite_alpha",
                "optimizer_requested",
                "optimizer_applied",
                "raw_preference_weight",
                "pre_constraint_weight",
                "constrained_weight",
                "final_target_weight",
                "previous_weight",
                "constraint_weight_delta",
                "turnover_weight_delta",
                "total_weight_delta",
                "sector_weight_pre_constraint",
                "sector_weight_post_constraint",
                "sector_weight_final",
                "max_single_weight",
                "max_sector_weight",
                "single_name_cap_binding",
                "sector_cap_binding",
                "turnover_limited",
                "turnover_cap",
                "realized_turnover",
                "covariance_method",
                "optimizer_fallback_reason",
                "diagnostic_json",
            ],
            conflict_cols=["as_of_date", "portfolio_name", "symbol"],
            scope_cols=["as_of_date", "portfolio_name"],
            scope_values=portfolio_scope,
        )
        _write_model_input_manifest(
            snapshot_id=snapshot_id,
            as_of_date=snapshot.as_of_date,
            manifest_type="portfolio_input",
            payload=_build_portfolio_input_manifest_payload(
                requested_as_of=requested_as_of,
                snapshot=snapshot,
                config=cfg,
                version_bundle=version_bundle,
                covariance_artifact=covariance_artifact,
                diagnostic_summary={
                    "status": "blocked_scoring",
                    "target_generation_frequency": _target_generation_frequency(cfg),
                },
                diagnostic_row_count=0,
            ),
        )
        logger.warning(
            "cw2_features: scoring universe below minimum guard requested_as_of=%s as_of=%s scoring=%d min_scoring=%d; skipping factor scoring and downstream portfolio construction",
            requested_as_of,
            snapshot.as_of_date,
            guard.scoring_universe,
            guard.min_scoring_universe,
        )
        _write_portfolio_snapshot_registry(
            snapshot_id=snapshot_id,
            as_of_date=snapshot.as_of_date,
            portfolio_name=portfolio_name,
            portfolio_target_records=[],
            config=cfg,
        )
        _write_cw2_quality_gate(
            requested_as_of=requested_as_of,
            snapshot=snapshot,
            guard=guard,
            universe_screen_records=universe_screen_records,
            sub_score_records=[],
            factor_score_records=[],
            risk_overlay_records=[],
            portfolio_target_records=[],
            config=cfg,
        )
        return {
            "universe_screen": universe_count,
            "sub_scores": 0,
            "factor_scores": 0,
            "risk_overlay": 0,
            "portfolio_targets": 0,
            "portfolio_diagnostics": 0,
            "covariance_artifact_stored": int(covariance_artifact is not None),
            "as_of_date_shifted": shifted,
        }

    eligible_factor_df = snapshot.factor_df[
        (snapshot.factor_df["symbol"] == "_MACRO")
        | (snapshot.factor_df["symbol"].isin(list(scoring_symbols)))
    ].copy()
    eligible_financial_df = snapshot.financial_df[
        snapshot.financial_df["symbol"].isin(list(scoring_symbols))
    ].copy()
    eligible_sector_map = {
        sym: snapshot.sector_map.get(sym, "Unknown") for sym in scoring_symbols
    }

    actual_regime = resolve_regime_from_config(
        vix_level=snapshot.vix_level,
        config=cfg,
        vix_history=snapshot.vix_history,
        macro_context={
            "term_spread_level": snapshot.term_spread_level,
            "term_spread_history": snapshot.term_spread_history,
        },
    )
    factor_score_kwargs = {"config": cfg}
    if "regime" in inspect.signature(compute_factor_scores_for_date).parameters:
        factor_score_kwargs["regime"] = actual_regime
    sub_score_records, factor_score_records = compute_factor_scores_for_date(
        eligible_factor_df,
        eligible_financial_df,
        snapshot.as_of_date,
        eligible_sector_map,
        **factor_score_kwargs,
    )
    factor_score_records = compute_composite_alpha(
        factor_score_records,
        vix_level=snapshot.vix_level,
        config=cfg,
        vix_history=snapshot.vix_history,
        macro_context={
            "term_spread_level": snapshot.term_spread_level,
            "term_spread_history": snapshot.term_spread_history,
        },
        forced_regime=actual_regime,
    )
    risk_overlay_records = apply_risk_overlay(
        factor_score_records,
        (
            snapshot.risk_data[
                snapshot.risk_data["symbol"].isin(list(scoring_symbols))
            ].copy()
            if not snapshot.risk_data.empty
            else snapshot.risk_data
        ),
        sub_score_records,
        config=cfg,
    )
    previous_target_as_of_date, previous_target_records = (
        _load_previous_portfolio_target_snapshot(
            snapshot.as_of_date,
            portfolio_name=portfolio_name,
        )
    )
    refresh_portfolio_targets = _should_refresh_portfolio_targets(
        snapshot.as_of_date,
        config=cfg,
        previous_target_records=previous_target_records,
    )
    portfolio_diagnostics = None
    if guard.allow_portfolio_construction:
        if refresh_portfolio_targets:
            portfolio_target_records, portfolio_diagnostics = build_portfolio_targets(
                factor_score_records,
                risk_overlay_records,
                universe_screen_records,
                snapshot.company_info_lookup,
                covariance_matrix=snapshot.covariance_matrix,
                covariance_meta=snapshot.covariance_meta,
                previous_positions=snapshot.previous_positions,
                config=cfg,
                return_diagnostics=True,
            )
            logger.info(
                "cw2_features: refreshed portfolio targets as_of=%s frequency=%s previous_target_as_of=%s",
                snapshot.as_of_date,
                _target_generation_frequency(cfg),
                previous_target_as_of_date,
            )
        else:
            portfolio_target_records = _build_carried_forward_portfolio_targets(
                as_of_date=snapshot.as_of_date,
                portfolio_name=portfolio_name,
                previous_target_records=previous_target_records,
            )
            logger.info(
                "cw2_features: carried forward portfolio targets as_of=%s source_as_of=%s frequency=%s positions=%d",
                snapshot.as_of_date,
                previous_target_as_of_date,
                _target_generation_frequency(cfg),
                len(portfolio_target_records),
            )
    else:
        logger.warning(
            "cw2_features: investable universe below minimum guard requested_as_of=%s as_of=%s investable=%d min_investable=%d; skipping portfolio construction",
            requested_as_of,
            snapshot.as_of_date,
            guard.investable_universe,
            guard.min_investable_universe,
        )
        portfolio_target_records = []
        portfolio_diagnostics = None

    if portfolio_target_records:
        default_target_source = (
            "cw2_portfolio_construction" if refresh_portfolio_targets else "frequency_carry"
        )
        portfolio_target_records = [
            {
                **record,
                "source": str(record.get("source") or default_target_source),
            }
            for record in portfolio_target_records
        ]

    sub_count = _upsert_rows(
        table_name="feature_sub_scores",
        rows=sub_score_records,
        allowed_cols=[
            "as_of_date",
            "symbol",
            "factor_group",
            "sub_variable",
            "raw_value",
            "winsorized_value",
            "neutralized_value",
            "z_score",
            "gics_sector",
        ],
        conflict_cols=["as_of_date", "symbol", "factor_group", "sub_variable"],
    )
    factor_count = _upsert_rows(
        table_name="feature_factor_scores",
        rows=factor_score_records,
        allowed_cols=[
            "as_of_date",
            "symbol",
            "quality_score",
            "value_score",
            "market_technical_score",
            "sentiment_score",
            "dividend_score",
            "composite_alpha",
            "regime",
            "vix_level",
        ],
        conflict_cols=["as_of_date", "symbol"],
    )
    risk_count = _upsert_rows(
        table_name="feature_risk_overlay",
        rows=risk_overlay_records,
        allowed_cols=[
            "as_of_date",
            "symbol",
            "log_market_cap",
            "liquidity_20d",
            "volatility_60d",
            "missing_factor_pct",
            "factor_groups_present",
            "pass_market_cap",
            "pass_liquidity",
            "pass_volatility",
            "pass_factor_coverage",
            "pass_data_quality",
            "pass_all",
        ],
        conflict_cols=["as_of_date", "symbol"],
    )
    portfolio_count = _replace_rows_for_scope(
        table_name="portfolio_target_positions",
        rows=portfolio_target_records,
        allowed_cols=[
            "as_of_date",
            "portfolio_name",
            "symbol",
            "selection_rank",
            "selected_signal",
            "target_weight",
            "weighting_scheme",
            "ranking_mode",
            "ranking_score",
            "composite_alpha",
            "regime",
            "gics_sector",
            "country",
            "previous_weight",
            "trade_weight",
            "turnover_cap",
            "realized_turnover",
            "turnover_limited",
            "source",
        ],
        conflict_cols=["as_of_date", "portfolio_name", "symbol"],
        scope_cols=["as_of_date", "portfolio_name"],
        scope_values=portfolio_scope,
    )
    diagnostic_rows = []
    if portfolio_diagnostics is not None:
        diagnostic_rows = [
            {
                **row,
                "snapshot_id": snapshot_id,
            }
            for row in portfolio_diagnostics.records
        ]
    diagnostic_count = _replace_rows_for_scope(
        table_name="portfolio_construction_diagnostics",
        rows=diagnostic_rows,
        allowed_cols=[
            "snapshot_id",
            "as_of_date",
            "portfolio_name",
            "symbol",
            "candidate_rank",
            "selected_signal",
            "selection_drop_reason",
            "gics_sector",
            "country",
            "ranking_mode",
            "ranking_score",
            "composite_alpha",
            "optimizer_requested",
            "optimizer_applied",
            "raw_preference_weight",
            "pre_constraint_weight",
            "constrained_weight",
            "final_target_weight",
            "previous_weight",
            "constraint_weight_delta",
            "turnover_weight_delta",
            "total_weight_delta",
            "sector_weight_pre_constraint",
            "sector_weight_post_constraint",
            "sector_weight_final",
            "max_single_weight",
            "max_sector_weight",
            "single_name_cap_binding",
            "sector_cap_binding",
            "turnover_limited",
            "turnover_cap",
            "realized_turnover",
            "covariance_method",
            "optimizer_fallback_reason",
            "diagnostic_json",
        ],
        conflict_cols=["as_of_date", "portfolio_name", "symbol"],
        scope_cols=["as_of_date", "portfolio_name"],
        scope_values=portfolio_scope,
    )
    _write_model_input_manifest(
        snapshot_id=snapshot_id,
        as_of_date=snapshot.as_of_date,
        manifest_type="portfolio_input",
        payload=_build_portfolio_input_manifest_payload(
            requested_as_of=requested_as_of,
            snapshot=snapshot,
            config=cfg,
            version_bundle=version_bundle,
            covariance_artifact=covariance_artifact,
            diagnostic_summary=(
                portfolio_diagnostics.summary
                if portfolio_diagnostics is not None
                else (
                    {
                        "status": "carried_forward",
                        "source_as_of_date": (
                            previous_target_as_of_date.isoformat()
                            if previous_target_as_of_date is not None
                            else None
                        ),
                        "target_generation_frequency": _target_generation_frequency(
                            cfg
                        ),
                    }
                    if (guard.allow_portfolio_construction and portfolio_target_records)
                    else {"status": "blocked_portfolio"}
                )
            ),
            diagnostic_row_count=diagnostic_count,
        ),
    )
    _write_portfolio_snapshot_registry(
        snapshot_id=snapshot_id,
        as_of_date=snapshot.as_of_date,
        portfolio_name=portfolio_name,
        portfolio_target_records=portfolio_target_records,
        config=cfg,
    )
    _write_cw2_quality_gate(
        requested_as_of=requested_as_of,
        snapshot=snapshot,
        guard=guard,
        universe_screen_records=universe_screen_records,
        sub_score_records=sub_score_records,
        factor_score_records=factor_score_records,
        risk_overlay_records=risk_overlay_records,
        portfolio_target_records=portfolio_target_records,
        config=cfg,
    )

    logger.info(
        "cw2_features: as_of=%s requested_as_of=%s universe_screen=%d sub_scores=%d factor_scores=%d risk_overlay=%d portfolio_targets=%d portfolio_diagnostics=%d",
        snapshot.as_of_date,
        requested_as_of,
        universe_count,
        sub_count,
        factor_count,
        risk_count,
        portfolio_count,
        diagnostic_count,
    )
    return {
        "universe_screen": universe_count,
        "sub_scores": sub_count,
        "factor_scores": factor_count,
        "risk_overlay": risk_count,
        "portfolio_targets": portfolio_count,
        "portfolio_diagnostics": diagnostic_count,
        "covariance_artifact_stored": int(covariance_artifact is not None),
        "as_of_date_shifted": shifted,
    }
