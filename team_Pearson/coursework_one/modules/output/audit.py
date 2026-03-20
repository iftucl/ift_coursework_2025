from __future__ import annotations

"""Pipeline run audit persistence helpers."""

import os
from typing import Optional

from sqlalchemy import text

from modules.db import get_db_engine


def _audit_enabled() -> bool:
    return os.getenv("CW1_TEST_MODE") != "1"


def write_pipeline_run_start(
    *,
    run_id: str,
    run_date: str,
    started_at: str,
    frequency: str,
    backfill_years: int,
    company_limit: Optional[int],
    enabled_extractors: str,
    notes: str = "",
) -> None:
    """Insert (or overwrite) a run row as ``running``."""
    if not _audit_enabled():
        return

    sql = text(
        """
        INSERT INTO systematic_equity.pipeline_runs (
            run_id, run_date, started_at, status, frequency, backfill_years,
            company_limit, enabled_extractors, notes
        ) VALUES (
            :run_id, :run_date, :started_at, 'running', :frequency, :backfill_years,
            :company_limit, :enabled_extractors, :notes
        )
        ON CONFLICT (run_id) DO UPDATE
        SET run_date = EXCLUDED.run_date,
            started_at = EXCLUDED.started_at,
            status = 'running',
            frequency = EXCLUDED.frequency,
            backfill_years = EXCLUDED.backfill_years,
            company_limit = EXCLUDED.company_limit,
            enabled_extractors = EXCLUDED.enabled_extractors,
            notes = EXCLUDED.notes,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    params = {
        "run_id": run_id,
        "run_date": run_date,
        "started_at": started_at,
        "frequency": frequency,
        "backfill_years": int(backfill_years),
        "company_limit": company_limit,
        "enabled_extractors": enabled_extractors,
        "notes": notes,
    }
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(sql, params)


def write_pipeline_run_finish(
    *,
    run_id: str,
    run_date: str,
    finished_at: str,
    status: str,
    rows_written: int,
    error_message: str = "",
    error_traceback: str = "",
    notes: str = "",
    frequency: Optional[str] = None,
    backfill_years: Optional[int] = None,
    company_limit: Optional[int] = None,
    enabled_extractors: Optional[str] = None,
) -> None:
    """Update a run row with final status; fallback to insert if row is missing."""
    if not _audit_enabled():
        return

    update_sql = text(
        """
        UPDATE systematic_equity.pipeline_runs
        SET finished_at = :finished_at,
            status = :status,
            rows_written = :rows_written,
            error_message = :error_message,
            error_traceback = :error_traceback,
            notes = :notes,
            updated_at = CURRENT_TIMESTAMP
        WHERE run_id = :run_id
        """
    )
    insert_sql = text(
        """
        INSERT INTO systematic_equity.pipeline_runs (
            run_id, run_date, started_at, finished_at, status, frequency, backfill_years,
            company_limit, enabled_extractors, rows_written, error_message, error_traceback, notes
        ) VALUES (
            :run_id, :run_date, :finished_at, :finished_at, :status, :frequency, :backfill_years,
            :company_limit, :enabled_extractors, :rows_written, :error_message,
            :error_traceback, :notes
        )
        ON CONFLICT (run_id) DO UPDATE
        SET finished_at = EXCLUDED.finished_at,
            status = EXCLUDED.status,
            rows_written = EXCLUDED.rows_written,
            error_message = EXCLUDED.error_message,
            error_traceback = EXCLUDED.error_traceback,
            notes = EXCLUDED.notes,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    params = {
        "run_id": run_id,
        "run_date": run_date,
        "finished_at": finished_at,
        "status": status,
        "rows_written": int(rows_written),
        "error_message": error_message,
        "error_traceback": error_traceback,
        "notes": notes,
        "frequency": frequency,
        "backfill_years": backfill_years,
        "company_limit": company_limit,
        "enabled_extractors": enabled_extractors,
    }
    engine = get_db_engine()
    with engine.begin() as conn:
        result = conn.execute(update_sql, params)
        if result.rowcount == 0:
            conn.execute(insert_sql, params)
