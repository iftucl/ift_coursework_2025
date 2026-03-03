from __future__ import annotations

"""Database load helpers for curated factor observations."""

import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.db import FactorObservation, FinancialObservation, get_db_engine

logger = logging.getLogger(__name__)


def _find_unique_constraint_name(table, expected_cols: set[str], fallback: str) -> str:
    """Resolve unique constraint name by column set with fallback value."""
    for constraint in table.constraints:
        cols = getattr(constraint, "columns", None)
        name = getattr(constraint, "name", None)
        if not cols or not name:
            continue
        col_names = {c.name for c in cols}
        if col_names == expected_cols:
            return str(name)
    return fallback


def _count_existing_rows(
    conn: Any,
    *,
    table: Any,
    key_columns: tuple[str, ...],
    records: List[Dict[str, Any]],
) -> int:
    """Count existing rows by unique key before upsert (for observability only)."""
    if not records:
        return 0
    from sqlalchemy import and_, bindparam, select  # type: ignore

    where_terms = [table.c[col] == bindparam(col) for col in key_columns]
    stmt = select(table.c[key_columns[0]]).where(and_(*where_terms)).limit(1)
    count = 0
    for rec in records:
        params = {k: rec.get(k) for k in key_columns}
        row = conn.execute(stmt, params).first()
        if row is not None:
            count += 1
    return count


_FACTOR_TABLE_NAME = FactorObservation.__table__.name
_FACTOR_DEFAULT_SCHEMA = FactorObservation.__table__.schema or "systematic_equity"
_FACTOR_CONSTRAINT_UNIQ = _find_unique_constraint_name(
    FactorObservation.__table__,
    expected_cols={"symbol", "observation_date", "factor_name"},
    fallback="uniq_observation",
)

_FINANCIAL_TABLE_NAME = FinancialObservation.__table__.name
_FINANCIAL_DEFAULT_SCHEMA = FinancialObservation.__table__.schema or "systematic_equity"
_FINANCIAL_CONSTRAINT_UNIQ = _find_unique_constraint_name(
    FinancialObservation.__table__,
    expected_cols={"symbol", "report_date", "metric_name"},
    fallback="uniq_financial_observation",
)


def _coerce_finite_float_or_none(value: Any) -> float | None:
    """Convert numeric-like value to finite float, otherwise None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def load_curated(
    records: List[Dict[str, Any]],
    *,
    dry_run: bool = False,
    table_name: str = _FACTOR_TABLE_NAME,
    stats_out: Optional[Dict[str, int]] = None,
) -> int:
    """Load curated records into PostgreSQL with upsert semantics.

    Parameters
    ----------
    records:
        Normalized records to insert/update.
    dry_run:
        If ``True``, skips DB I/O and returns the number of input records.
    table_name:
        Target table name in the configured schema.

    Returns
    -------
    int
        Number of records written (or would be written for ``dry_run``).

    Raises
    ------
    ModuleNotFoundError
        If pandas/SQLAlchemy are not installed.
    ValueError
        If required columns are missing in input records.
    """
    if not records:
        if stats_out is not None:
            stats_out.update({"attempted": 0, "inserted": 0, "updated": 0, "invalid": 0})
        return 0
    if dry_run:
        if stats_out is not None:
            stats_out.update(
                {
                    "attempted": int(len(records)),
                    "inserted": int(len(records)),
                    "updated": 0,
                    "invalid": 0,
                }
            )
        return len(records)

    try:
        import pandas as pd  # type: ignore
        from sqlalchemy import MetaData, Table  # type: ignore
        from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore
    except ModuleNotFoundError as e:  # pragma: no cover
        raise ModuleNotFoundError(
            "Loading to Postgres requires pandas + SQLAlchemy. "
            "Install dependencies via Poetry: `poetry install`."
        ) from e

    df = pd.DataFrame.from_records(records)
    attempted_count = int(len(df))

    required = {"symbol", "observation_date", "factor_name"}
    if not required.issubset(df.columns):
        missing = required.difference(df.columns)
        raise ValueError(f"Missing required columns for load: {sorted(missing)}")

    schema = os.getenv("POSTGRES_SCHEMA", _FACTOR_DEFAULT_SCHEMA)

    engine = get_db_engine()
    metadata = MetaData()
    table = Table(table_name, metadata, schema=schema, autoload_with=engine)

    table_columns = {c.name for c in table.columns}
    ignored_columns = sorted(c for c in df.columns if c not in table_columns)
    if ignored_columns:
        logger.debug("Ignored columns not in DB schema: %s", ", ".join(ignored_columns))

    writable_columns = [c for c in df.columns if c in table_columns]
    df = df[writable_columns]
    df = df.where(df.notna(), None)

    # Final defensive guard for date columns before SQL bind.
    if "observation_date" in df.columns:
        obs = pd.to_datetime(df["observation_date"], errors="coerce")
        df = df[obs.notna()].copy()
        if df.empty:
            if stats_out is not None:
                stats_out.update(
                    {
                        "attempted": attempted_count,
                        "inserted": 0,
                        "updated": 0,
                        "invalid": attempted_count,
                    }
                )
            return 0
        df["observation_date"] = obs[obs.notna()].dt.date.values

    if "source_report_date" in df.columns:
        report = pd.to_datetime(df["source_report_date"], errors="coerce")
        # Keep Python ``date`` or ``None`` only; avoid pandas NaT leaking into SQL binds.
        df["source_report_date"] = [ts.date() if pd.notna(ts) else None for ts in report]
    if "factor_value" in df.columns:
        df["factor_value"] = pd.to_numeric(df["factor_value"], errors="coerce")
        df["factor_value"] = (
            df["factor_value"]
            .map(_coerce_finite_float_or_none)
            .astype("object")
            .where(pd.notna(df["factor_value"]), None)
        )

    records_out = df.to_dict(orient="records")
    invalid_count = max(0, attempted_count - int(len(records_out)))
    stmt = pg_insert(table).values(records_out)

    update_dict = {
        "factor_value": stmt.excluded.factor_value,
        "source": stmt.excluded.source,
        "metric_frequency": stmt.excluded.metric_frequency,
        "source_report_date": stmt.excluded.source_report_date,
        "updated_at": datetime.now(),
    }

    upsert_stmt = stmt.on_conflict_do_update(
        constraint=_FACTOR_CONSTRAINT_UNIQ,
        set_=update_dict,
    )

    with engine.begin() as conn:
        existing_count = 0
        if stats_out is not None:
            existing_count = _count_existing_rows(
                conn,
                table=table,
                key_columns=("symbol", "observation_date", "factor_name"),
                records=records_out,
            )
        conn.execute(upsert_stmt)

    if stats_out is not None:
        updated_count = min(existing_count, int(len(records_out)))
        inserted_count = int(len(records_out)) - updated_count
        stats_out.update(
            {
                "attempted": attempted_count,
                "inserted": inserted_count,
                "updated": updated_count,
                "invalid": invalid_count,
            }
        )

    return len(records_out)


def load_financial_observations(
    records: List[Dict[str, Any]],
    *,
    dry_run: bool = False,
    table_name: str = _FINANCIAL_TABLE_NAME,
    stats_out: Optional[Dict[str, int]] = None,
) -> int:
    """Load atomic financial observations into PostgreSQL with upsert semantics."""
    if not records:
        if stats_out is not None:
            stats_out.update({"attempted": 0, "inserted": 0, "updated": 0, "invalid": 0})
        return 0
    if dry_run:
        if stats_out is not None:
            stats_out.update(
                {
                    "attempted": int(len(records)),
                    "inserted": int(len(records)),
                    "updated": 0,
                    "invalid": 0,
                }
            )
        return len(records)

    try:
        import pandas as pd  # type: ignore
        from sqlalchemy import MetaData, Table  # type: ignore
        from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore
    except ModuleNotFoundError as e:  # pragma: no cover
        raise ModuleNotFoundError(
            "Loading to Postgres requires pandas + SQLAlchemy. "
            "Install dependencies via Poetry: `poetry install`."
        ) from e

    df = pd.DataFrame.from_records(records)
    attempted_count = int(len(df))
    required = {"symbol", "report_date", "metric_name"}
    if not required.issubset(df.columns):
        missing = required.difference(df.columns)
        raise ValueError(f"Missing required columns for financial load: {sorted(missing)}")

    schema = os.getenv("POSTGRES_SCHEMA", _FINANCIAL_DEFAULT_SCHEMA)
    engine = get_db_engine()
    metadata = MetaData()
    table = Table(table_name, metadata, schema=schema, autoload_with=engine)

    table_columns = {c.name for c in table.columns}
    writable_columns = [c for c in df.columns if c in table_columns]
    df = df[writable_columns]
    df = df.where(df.notna(), None)

    report = pd.to_datetime(df["report_date"], errors="coerce")
    df = df[report.notna()].copy()
    if df.empty:
        if stats_out is not None:
            stats_out.update(
                {
                    "attempted": attempted_count,
                    "inserted": 0,
                    "updated": 0,
                    "invalid": attempted_count,
                }
            )
        return 0
    df["report_date"] = report[report.notna()].dt.date.values

    if "as_of" in df.columns:
        as_of = pd.to_datetime(df["as_of"], errors="coerce")
        df["as_of"] = [ts.date() if pd.notna(ts) else None for ts in as_of]

    if "metric_value" in df.columns:
        df["metric_value"] = pd.to_numeric(df["metric_value"], errors="coerce")
        df["metric_value"] = (
            df["metric_value"]
            .map(_coerce_finite_float_or_none)
            .astype("object")
            .where(pd.notna(df["metric_value"]), None)
        )

    records_out = df.to_dict(orient="records")
    invalid_count = max(0, attempted_count - int(len(records_out)))
    stmt = pg_insert(table).values(records_out)
    update_dict = {
        "metric_value": stmt.excluded.metric_value,
        "currency": stmt.excluded.currency,
        "period_type": stmt.excluded.period_type,
        "source": stmt.excluded.source,
        "as_of": stmt.excluded.as_of,
        "metric_definition": stmt.excluded.metric_definition,
        "updated_at": datetime.now(),
    }
    upsert_stmt = stmt.on_conflict_do_update(
        constraint=_FINANCIAL_CONSTRAINT_UNIQ,
        set_=update_dict,
    )
    with engine.begin() as conn:
        existing_count = 0
        if stats_out is not None:
            existing_count = _count_existing_rows(
                conn,
                table=table,
                key_columns=("symbol", "report_date", "metric_name"),
                records=records_out,
            )
        conn.execute(upsert_stmt)
    if stats_out is not None:
        updated_count = min(existing_count, int(len(records_out)))
        inserted_count = int(len(records_out)) - updated_count
        stats_out.update(
            {
                "attempted": attempted_count,
                "inserted": inserted_count,
                "updated": updated_count,
                "invalid": invalid_count,
            }
        )
    return len(records_out)
