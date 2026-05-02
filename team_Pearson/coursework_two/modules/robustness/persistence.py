from __future__ import annotations

"""Persist robustness summary outputs and row-level metrics into PostgreSQL."""

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

try:
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot
except ModuleNotFoundError:  # pragma: no cover
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from team_Pearson.coursework_two.modules.ops.quality import record_quality_snapshot

logger = logging.getLogger(__name__)

_SCHEMA = "systematic_equity"


def ensure_robustness_schema(engine: Engine) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "sql" / "cw2_robustness_schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.execute(sql_text)
        raw_conn.commit()
    finally:
        raw_conn.close()


def persist_robustness_outputs(
    *,
    engine: Engine,
    report_name: str,
    output_root: str | Path,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    """Persist robustness CSV/markdown/json outputs and row-level metrics."""

    root = Path(output_root).resolve()
    ensure_robustness_schema(engine)
    artifacts = _collect_artifacts(root)
    report_id = _upsert_report_header(
        engine=engine,
        report_name=report_name,
        output_root=root,
        source_run_id=source_run_id,
        artifacts=artifacts,
    )
    _replace_artifacts(engine=engine, robustness_report_id=report_id, artifacts=artifacts)
    row_count = _replace_rows(engine=engine, robustness_report_id=report_id, artifacts=artifacts)
    quality_report = {
        "passed": len(artifacts) > 0,
        "artifact_count": len(artifacts),
        "row_count": row_count,
        "output_root_exists": root.exists(),
        "csv_artifact_count": sum(1 for item in artifacts if item["artifact_role"] == "csv"),
    }
    try:
        record_quality_snapshot(
            engine=engine,
            dataset_name="robustness_reports",
            run_id=report_id,
            run_date=pd.Timestamp.now(tz="UTC").date().isoformat(),
            quality_report=quality_report,
        )
    except Exception:  # pragma: no cover
        logger.warning(
            "cw2_robustness: failed to persist quality snapshot report_name=%s",
            report_name,
            exc_info=True,
        )
    return {
        "robustness_report_id": report_id,
        "report_name": report_name,
        "output_root": str(root),
        "artifact_count": len(artifacts),
        "row_count": row_count,
    }


def _collect_artifacts(root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if not root.exists():
        return artifacts
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        role = {
            ".csv": "csv",
            ".md": "markdown",
            ".json": "json",
            ".png": "plot",
            ".yaml": "config",
            ".yml": "config",
            ".log": "log",
            ".cmd": "script",
        }.get(suffix, "other")
        row_count = None
        if role == "csv":
            try:
                row_count = int(len(pd.read_csv(path)))
            except Exception:
                row_count = None
        artifacts.append(
            {
                "artifact_name": str(path.relative_to(root)).replace("\\", "/"),
                "artifact_group": _artifact_group(path.relative_to(root).parts),
                "artifact_role": role,
                "artifact_path": str(path),
                "row_count": row_count,
                "artifact_metadata": {
                    "size_bytes": path.stat().st_size,
                    "suffix": suffix,
                },
            }
        )
    return artifacts


def _artifact_group(parts: tuple[str, ...]) -> str:
    if not parts:
        return "root"
    first = parts[0].lower()
    if first.startswith("part_"):
        return first
    return first


def _upsert_report_header(
    *,
    engine: Engine,
    report_name: str,
    output_root: Path,
    source_run_id: str | None,
    artifacts: list[dict[str, Any]],
) -> str:
    report_id = str(uuid.uuid4())
    summary = {
        "artifact_count": len(artifacts),
        "csv_artifact_count": sum(1 for item in artifacts if item["artifact_role"] == "csv"),
        "markdown_artifact_count": sum(
            1 for item in artifacts if item["artifact_role"] == "markdown"
        ),
    }
    sql = text(f"""
        INSERT INTO {_SCHEMA}.robustness_reports (
            robustness_report_id,
            report_name,
            report_scope,
            report_status,
            output_root,
            source_run_id,
            summary_json
        ) VALUES (
            :robustness_report_id,
            :report_name,
            'robustness_outputs',
            'generated',
            :output_root,
            :source_run_id,
            CAST(:summary_json AS jsonb)
        )
        ON CONFLICT (report_name, output_root) DO UPDATE
        SET
            source_run_id = EXCLUDED.source_run_id,
            summary_json = EXCLUDED.summary_json,
            updated_at = NOW()
        RETURNING robustness_report_id
        """)
    with engine.begin() as conn:
        row = (
            conn.execute(
                sql,
                {
                    "robustness_report_id": report_id,
                    "report_name": report_name,
                    "output_root": str(output_root),
                    "source_run_id": source_run_id,
                    "summary_json": json.dumps(summary, ensure_ascii=False, sort_keys=True),
                },
            )
            .mappings()
            .first()
        )
    return str(row["robustness_report_id"])


def _replace_artifacts(
    *,
    engine: Engine,
    robustness_report_id: str,
    artifacts: list[dict[str, Any]],
) -> None:
    delete_sql = text(
        f"DELETE FROM {_SCHEMA}.robustness_report_artifacts WHERE robustness_report_id = :robustness_report_id"
    )
    insert_sql = text(f"""
        INSERT INTO {_SCHEMA}.robustness_report_artifacts (
            robustness_report_id,
            artifact_name,
            artifact_group,
            artifact_role,
            artifact_path,
            row_count,
            artifact_metadata
        ) VALUES (
            :robustness_report_id,
            :artifact_name,
            :artifact_group,
            :artifact_role,
            :artifact_path,
            :row_count,
            CAST(:artifact_metadata AS jsonb)
        )
        """)
    with engine.begin() as conn:
        conn.execute(delete_sql, {"robustness_report_id": robustness_report_id})
        for artifact in artifacts:
            conn.execute(
                insert_sql,
                {
                    "robustness_report_id": robustness_report_id,
                    "artifact_name": artifact["artifact_name"],
                    "artifact_group": artifact["artifact_group"],
                    "artifact_role": artifact["artifact_role"],
                    "artifact_path": artifact["artifact_path"],
                    "row_count": artifact["row_count"],
                    "artifact_metadata": json.dumps(
                        artifact.get("artifact_metadata") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            )


def _replace_rows(
    *,
    engine: Engine,
    robustness_report_id: str,
    artifacts: list[dict[str, Any]],
) -> int:
    delete_sql = text(
        f"DELETE FROM {_SCHEMA}.robustness_report_rows WHERE robustness_report_id = :robustness_report_id"
    )
    insert_sql = text(f"""
        INSERT INTO {_SCHEMA}.robustness_report_rows (
            robustness_report_id,
            dataset_name,
            row_number,
            row_payload
        ) VALUES (
            :robustness_report_id,
            :dataset_name,
            :row_number,
            CAST(:row_payload AS jsonb)
        )
        """)
    inserted = 0
    with engine.begin() as conn:
        conn.execute(delete_sql, {"robustness_report_id": robustness_report_id})
        for artifact in artifacts:
            if artifact["artifact_role"] != "csv":
                continue
            path = Path(artifact["artifact_path"])
            try:
                df = pd.read_csv(path)
            except Exception:
                logger.warning("cw2_robustness: failed to read csv path=%s", path, exc_info=True)
                continue
            dataset_name = artifact["artifact_name"].replace("/", "__").replace("\\", "__")
            if dataset_name.lower().endswith(".csv"):
                dataset_name = dataset_name[:-4]
            for row_number, row in enumerate(df.to_dict(orient="records"), start=1):
                normalized = {key: _normalize_cell(value) for key, value in row.items()}
                conn.execute(
                    insert_sql,
                    {
                        "robustness_report_id": robustness_report_id,
                        "dataset_name": dataset_name,
                        "row_number": row_number,
                        "row_payload": json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    },
                )
                inserted += 1
    return inserted


def _normalize_cell(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value
