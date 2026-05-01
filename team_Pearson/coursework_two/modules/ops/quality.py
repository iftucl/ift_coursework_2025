from __future__ import annotations

"""Shared helpers for CW2 derived-output quality snapshots."""

import json
import logging
from datetime import date, datetime
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def record_quality_snapshot(
    *,
    engine: Engine,
    dataset_name: str,
    run_id: str,
    run_date: date | datetime | str,
    quality_report: Dict[str, Any] | None,
) -> None:
    """Persist one CW2 quality snapshot without making the main flow brittle."""

    report = dict(quality_report or {})
    passed = report.get("passed")
    warnings = list(report.get("warnings") or [])
    if passed is False:
        status = "fail"
    elif warnings:
        status = "warn"
    elif passed is True:
        status = "pass"
    else:
        status = "unknown"

    sql = text("""
        INSERT INTO systematic_equity.quality_snapshots (
            run_id, run_date, dataset_name, quality_report, status
        ) VALUES (
            :run_id, :run_date, :dataset_name, CAST(:quality_report AS jsonb), :status
        )
        ON CONFLICT (run_id, run_date, dataset_name) DO UPDATE
        SET
            quality_report = EXCLUDED.quality_report,
            status = EXCLUDED.status
        """)
    params = {
        "run_id": str(run_id),
        "run_date": _normalize_run_date(run_date),
        "dataset_name": str(dataset_name),
        "quality_report": json.dumps(report, ensure_ascii=False, sort_keys=True),
        "status": status,
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
    except Exception:  # pragma: no cover - governance telemetry must not break the main pipeline
        logger.warning(
            "cw2_quality: failed to persist quality snapshot dataset=%s run_id=%s",
            dataset_name,
            run_id,
            exc_info=True,
        )


def _normalize_run_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value or "").strip()
    if not text_value:
        raise ValueError("run_date is required for quality snapshot persistence")
    if len(text_value) >= 10:
        return text_value[:10]
    raise ValueError(f"Invalid run_date value: {value!r}")
