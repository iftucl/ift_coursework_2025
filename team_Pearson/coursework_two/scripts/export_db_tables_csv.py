#!/usr/bin/env python3
"""Export PostgreSQL tables to gzip-compressed CSV files for handoff.

The exporter is intentionally read-only. It uses PostgreSQL COPY TO STDOUT so
large tables can be streamed without loading them into memory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
for path in (str(CW1_ROOT), str(REPO_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.scripts.orchestration import load_env_layers  # noqa: E402


def _quote_ident(value: str) -> str:
    clean = str(value).strip()
    if not clean or "\x00" in clean:
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return '"' + clean.replace('"', '""') + '"'


def _parse_csv(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _table_inventory(engine, schemas: Iterable[str]) -> List[Dict[str, object]]:
    schema_list = list(schemas)
    sql = text("""
        SELECT
            n.nspname AS table_schema,
            c.relname AS table_name,
            COALESCE(s.n_live_tup, 0)::bigint AS estimated_rows,
            pg_total_relation_size(c.oid)::bigint AS relation_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s
          ON s.schemaname = n.nspname
         AND s.relname = c.relname
        WHERE c.relkind = 'r'
          AND n.nspname = ANY(:schemas)
        ORDER BY pg_total_relation_size(c.oid), n.nspname, c.relname
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"schemas": schema_list}).mappings().all()
    return [dict(row) for row in rows]


def _export_table(raw_conn, table: Mapping[str, object], output_root: Path) -> Dict[str, object]:
    schema = str(table["table_schema"])
    table_name = str(table["table_name"])
    schema_dir = output_root / schema
    schema_dir.mkdir(parents=True, exist_ok=True)
    output_path = schema_dir / f"{table_name}.csv.gz"
    copy_sql = (
        "COPY (SELECT * FROM "
        f"{_quote_ident(schema)}.{_quote_ident(table_name)}"
        ") TO STDOUT WITH CSV HEADER"
    )

    started_at = datetime.now(timezone.utc)
    with raw_conn.cursor() as cursor:
        with gzip.open(output_path, "wt", newline="", encoding="utf-8") as fh:
            cursor.copy_expert(copy_sql, fh)
    ended_at = datetime.now(timezone.utc)

    return {
        **dict(table),
        "file": str(output_path),
        "file_bytes": output_path.stat().st_size,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
    }


def _write_manifest(output_root: Path, records: List[Mapping[str, object]]) -> None:
    manifest_json = output_root / "manifest.json"
    manifest_csv = output_root / "manifest.csv"
    manifest_json.write_text(
        json.dumps(records, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    if records:
        fields = list(records[0].keys())
        with manifest_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export DB tables to CSV.gz files.")
    parser.add_argument(
        "--schemas",
        default="systematic_equity",
        help="Comma-separated schemas to export.",
    )
    parser.add_argument(
        "--output-dir",
        default="team_Pearson/coursework_two/outputs/handoff/db_csv_formal_s30",
    )
    parser.add_argument(
        "--skip-tables",
        default="",
        help="Comma-separated table names to skip, with or without schema prefix.",
    )
    parser.add_argument(
        "--limit-tables",
        default="",
        help="Comma-separated table names to export, with or without schema prefix.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_env_layers()
    schemas = _parse_csv(args.schemas)
    skip = set(_parse_csv(args.skip_tables))
    limit = set(_parse_csv(args.limit_tables))
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    engine = get_db_engine()
    tables = _table_inventory(engine, schemas)
    if limit:
        tables = [
            table
            for table in tables
            if str(table["table_name"]) in limit
            or f"{table['table_schema']}.{table['table_name']}" in limit
        ]
    if skip:
        tables = [
            table
            for table in tables
            if str(table["table_name"]) not in skip
            and f"{table['table_schema']}.{table['table_name']}" not in skip
        ]

    records: List[Dict[str, object]] = []
    raw_conn = engine.raw_connection()
    try:
        for idx, table in enumerate(tables, start=1):
            label = f"{table['table_schema']}.{table['table_name']}"
            print(
                json.dumps(
                    {
                        "status": "export_started",
                        "ordinal": idx,
                        "table_count": len(tables),
                        "table": label,
                        "estimated_rows": table.get("estimated_rows"),
                        "relation_bytes": table.get("relation_bytes"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            record = _export_table(raw_conn, table, output_root)
            records.append(record)
            _write_manifest(output_root, records)
            print(
                json.dumps(
                    {
                        "status": "export_completed",
                        "ordinal": idx,
                        "table_count": len(tables),
                        "table": label,
                        "file": record.get("file"),
                        "file_bytes": record.get("file_bytes"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        raw_conn.close()

    _write_manifest(output_root, records)
    print(
        json.dumps(
            {
                "status": "completed",
                "table_count": len(records),
                "output_dir": str(output_root),
                "manifest_json": str(output_root / "manifest.json"),
                "manifest_csv": str(output_root / "manifest.csv"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
