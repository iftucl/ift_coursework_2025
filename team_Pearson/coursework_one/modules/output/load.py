from __future__ import annotations

"""Database load helpers for curated factor observations."""

from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.db import FactorObservation, FinancialObservation, get_db_engine

logger = logging.getLogger(__name__)
DEFAULT_WRITE_BATCH_SIZE = 10_000


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


def _get_table_column(table: Any, column_name: str) -> Any | None:
    """Return a SQLAlchemy column-like object from reflected or fake test tables."""
    table_c = getattr(table, "c", None)
    if table_c is not None:
        getter = getattr(table_c, "get", None)
        if callable(getter):
            column = getter(column_name)
            if column is not None:
                return column
        if hasattr(table_c, "__contains__") and column_name in table_c:
            return table_c[column_name]
    for column in getattr(table, "columns", []):
        if getattr(column, "name", None) == column_name:
            return column
    return None


def _numeric_precision_scale(table: Any, column_name: str) -> tuple[int | None, int | None]:
    """Read precision/scale from the target table definition when available."""
    column = _get_table_column(table, column_name)
    column_type = getattr(column, "type", None)
    precision = getattr(column_type, "precision", None)
    scale = getattr(column_type, "scale", None)
    return precision, scale


def _preserve_existing_non_null_where(
    *,
    table: Any,
    excluded_value_column: Any,
    value_column_name: str,
) -> Any | None:
    """Return a conflict-update guard that blocks null overwrites of non-null values.

    Incremental re-runs may recompute a shorter history window whose first observation has
    a null value (for example ``daily_return`` at the new window boundary). In that case we
    should not overwrite an already materialized non-null database value with the newer null.
    """
    existing_value_column = _get_table_column(table, value_column_name)
    if existing_value_column is None:
        return None
    if not hasattr(excluded_value_column, "is_not") or not hasattr(existing_value_column, "is_"):
        return None
    return excluded_value_column.is_not(None) | existing_value_column.is_(None)


def _numeric_max_abs(precision: int, scale: int) -> Decimal:
    """Return the maximum representable absolute value for NUMERIC(precision, scale)."""
    integer_digits = precision - scale
    if integer_digits <= 0:
        integer_part = "0"
    else:
        integer_part = "9" * integer_digits
    if scale <= 0:
        return Decimal(integer_part)
    return Decimal(f"{integer_part}.{'9' * scale}")


def _coerce_numeric_for_db(
    value: Any,
    *,
    precision: int | None,
    scale: int | None,
    pd_module: Any,
) -> tuple[Decimal | None, str | None]:
    """Coerce numeric-like values for NUMERIC columns.

    Returns a tuple of ``(coerced_value, status)`` where ``status`` is:
    - ``None``: value is valid
    - ``invalid``: non-finite / malformed value; caller may keep row with NULL
    - ``out_of_range``: finite value exceeds schema range; caller should drop row
    """
    if value is None or pd_module.isna(value):
        return None, None

    text = str(value).strip()
    if not text:
        return None, "invalid"

    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, "invalid"

    if not dec.is_finite():
        return None, "invalid"

    if scale is not None:
        quantizer = Decimal(1).scaleb(-scale)
        dec = dec.quantize(quantizer, rounding=ROUND_HALF_EVEN)

    if (
        precision is not None
        and scale is not None
        and abs(dec) > _numeric_max_abs(precision, scale)
    ):
        return None, "out_of_range"

    return dec, None


def _log_out_of_range_rows(
    *,
    dataset_label: str,
    value_column: str,
    group_field: str,
    rejected_rows: List[Dict[str, Any]],
) -> None:
    """Emit a compact warning for rows dropped due to schema range overflow."""
    if not rejected_rows:
        return

    grouped = Counter(
        str(row.get(group_field))
        for row in rejected_rows
        if row.get(group_field) is not None
    )
    grouped_text = ", ".join(f"{name} x{count}" for name, count in grouped.most_common(5))

    samples = []
    for row in rejected_rows[:3]:
        symbol = row.get("symbol")
        row_date = row.get("report_date") or row.get("observation_date")
        field_name = row.get(group_field)
        raw_value = row.get(value_column)
        samples.append(f"{symbol}/{row_date}/{field_name}={raw_value}")
    sample_text = "; ".join(samples)

    logger.warning(
        "Skipped %d out-of-range %s rows for %s. Affected %s: %s. Examples: %s",
        len(rejected_rows),
        dataset_label,
        value_column,
        group_field,
        grouped_text or "unknown",
        sample_text or "none",
    )


def _sanitize_numeric_column(
    df: Any,
    *,
    table: Any,
    column_name: str,
    pd_module: Any,
    dataset_label: str,
    group_field: str,
) -> Any:
    """Coerce NUMERIC column values and drop finite rows outside schema bounds."""
    precision, scale = _numeric_precision_scale(table, column_name)
    if precision is None or scale is None:
        # Fallback for simplified unit-test doubles that do not expose SQL types.
        df[column_name] = (
            df[column_name]
            .map(_coerce_finite_float_or_none)
            .astype("object")
            .where(pd_module.notna(df[column_name]), None)
        )
        return df

    coerced_values: List[Decimal | None] = []
    rejected_indexes: List[Any] = []
    rejected_rows: List[Dict[str, Any]] = []

    for idx, raw_value in df[column_name].items():
        coerced, status = _coerce_numeric_for_db(
            raw_value,
            precision=precision,
            scale=scale,
            pd_module=pd_module,
        )
        if status == "out_of_range":
            rejected_indexes.append(idx)
            row_snapshot = {"symbol": df.at[idx, "symbol"], column_name: raw_value}
            for key in ("observation_date", "report_date", group_field):
                if key in df.columns:
                    row_snapshot[key] = df.at[idx, key]
            rejected_rows.append(row_snapshot)
        coerced_values.append(coerced)

    df[column_name] = coerced_values
    if rejected_rows:
        _log_out_of_range_rows(
            dataset_label=dataset_label,
            value_column=column_name,
            group_field=group_field,
            rejected_rows=rejected_rows,
        )
        df = df.drop(index=rejected_indexes)
    return df


def _resolve_write_batch_size(explicit_value: int | None = None) -> int:
    """Resolve bounded DB write batch size from arg/env/fallback."""
    raw = explicit_value
    if raw is None:
        raw = os.getenv("CW1_DB_WRITE_BATCH_SIZE")
    try:
        size = int(raw) if raw not in (None, "") else DEFAULT_WRITE_BATCH_SIZE
    except (TypeError, ValueError):
        size = DEFAULT_WRITE_BATCH_SIZE
    return max(1, size)


def _iter_record_chunks(records: List[Dict[str, Any]], batch_size: int) -> Any:
    """Yield successive chunks for bounded insert/upsert statements."""
    for offset in range(0, len(records), batch_size):
        yield offset // batch_size + 1, records[offset : offset + batch_size]


def load_curated(
    records: List[Dict[str, Any]],
    *,
    dry_run: bool = False,
    table_name: str = _FACTOR_TABLE_NAME,
    stats_out: Optional[Dict[str, int]] = None,
    batch_size: int | None = None,
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
        df = _sanitize_numeric_column(
            df,
            table=table,
            column_name="factor_value",
            pd_module=pd,
            dataset_label="curated factor",
            group_field="factor_name",
        )

    records_out = df.to_dict(orient="records")
    invalid_count = max(0, attempted_count - int(len(records_out)))
    if not records_out:
        if stats_out is not None:
            stats_out.update(
                {
                    "attempted": attempted_count,
                    "inserted": 0,
                    "updated": 0,
                    "invalid": invalid_count,
                }
            )
        return 0
    resolved_batch_size = _resolve_write_batch_size(batch_size)
    total_updated = 0
    total_inserted = 0
    total_chunks = max(1, math.ceil(len(records_out) / resolved_batch_size))
    with engine.begin() as conn:
        for chunk_no, chunk_records in _iter_record_chunks(records_out, resolved_batch_size):
            stmt = pg_insert(table).values(chunk_records)
            preserve_non_null_where = _preserve_existing_non_null_where(
                table=table,
                excluded_value_column=stmt.excluded.factor_value,
                value_column_name="factor_value",
            )
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
                where=preserve_non_null_where,
            )

            existing_count = 0
            if stats_out is not None:
                existing_count = _count_existing_rows(
                    conn,
                    table=table,
                    key_columns=("symbol", "observation_date", "factor_name"),
                    records=chunk_records,
                )
            conn.execute(upsert_stmt)
            updated_count = min(existing_count, int(len(chunk_records)))
            inserted_count = int(len(chunk_records)) - updated_count
            total_updated += updated_count
            total_inserted += inserted_count

            if total_chunks > 1:
                logger.info(
                    "db_batch_progress dataset=factor_observations "
                    "chunk=%s/%s rows=%s inserted=%s updated=%s",
                    chunk_no,
                    total_chunks,
                    len(chunk_records),
                    inserted_count,
                    updated_count,
                )

    if stats_out is not None:
        stats_out.update(
            {
                "attempted": attempted_count,
                "inserted": total_inserted,
                "updated": total_updated,
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
    batch_size: int | None = None,
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
        df = _sanitize_numeric_column(
            df,
            table=table,
            column_name="metric_value",
            pd_module=pd,
            dataset_label="financial observation",
            group_field="metric_name",
        )

    records_out = df.to_dict(orient="records")
    invalid_count = max(0, attempted_count - int(len(records_out)))
    if not records_out:
        if stats_out is not None:
            stats_out.update(
                {
                    "attempted": attempted_count,
                    "inserted": 0,
                    "updated": 0,
                    "invalid": invalid_count,
                }
            )
        return 0
    resolved_batch_size = _resolve_write_batch_size(batch_size)
    total_updated = 0
    total_inserted = 0
    total_chunks = max(1, math.ceil(len(records_out) / resolved_batch_size))
    with engine.begin() as conn:
        for chunk_no, chunk_records in _iter_record_chunks(records_out, resolved_batch_size):
            stmt = pg_insert(table).values(chunk_records)
            preserve_non_null_where = _preserve_existing_non_null_where(
                table=table,
                excluded_value_column=stmt.excluded.metric_value,
                value_column_name="metric_value",
            )
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
                where=preserve_non_null_where,
            )
            existing_count = 0
            if stats_out is not None:
                existing_count = _count_existing_rows(
                    conn,
                    table=table,
                    key_columns=("symbol", "report_date", "metric_name"),
                    records=chunk_records,
                )
            conn.execute(upsert_stmt)
            updated_count = min(existing_count, int(len(chunk_records)))
            inserted_count = int(len(chunk_records)) - updated_count
            total_updated += updated_count
            total_inserted += inserted_count

            if total_chunks > 1:
                logger.info(
                    "db_batch_progress dataset=financial_observations "
                    "chunk=%s/%s rows=%s inserted=%s updated=%s",
                    chunk_no,
                    total_chunks,
                    len(chunk_records),
                    inserted_count,
                    updated_count,
                )
    if stats_out is not None:
        stats_out.update(
            {
                "attempted": attempted_count,
                "inserted": total_inserted,
                "updated": total_updated,
                "invalid": invalid_count,
            }
        )
    return len(records_out)
