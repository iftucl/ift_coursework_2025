from __future__ import annotations

"""Import legacy AV raw news JSONL from a local directory into MinIO.

Reads the old ``run_date=YYYY-MM-DD/year=YYYY/month=MM/symbol=XXXX.jsonl``
tree, uploads each file to MinIO under the same object key structure, and
creates ``news_current`` (merged view) and ``news_cursor`` (closed marker)
objects so that the pipeline treats these months as already ingested.

Usage::

    # Ensure MinIO is running (docker compose up miniocw minio_client_cw)
    poetry run python scripts/import_raw_news_to_minio.py \
        --source-dir /path/to/source_b/news \
        --cutoff-date 2026-03-01

    # Dry-run (no actual upload):
    poetry run python scripts/import_raw_news_to_minio.py \
        --source-dir /path/to/source_b/news \
        --dry-run
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Import legacy AV raw news JSONL into MinIO.",
    )
    p.add_argument(
        "--source-dir",
        required=True,
        help="Path to local raw/source_b/news/ directory tree.",
    )
    p.add_argument(
        "--cutoff-date",
        default="2026-03-01",
        help="AV cutoff date (YYYY-MM-DD). Months before this are marked closed.",
    )
    p.add_argument(
        "--minio-endpoint",
        default=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
    )
    p.add_argument(
        "--minio-access-key",
        default=os.getenv("MINIO_ACCESS_KEY", "ift_bigdata"),
    )
    p.add_argument(
        "--minio-secret-key",
        default=os.getenv("MINIO_SECRET_KEY", "minio_password"),
    )
    p.add_argument(
        "--minio-bucket",
        default=os.getenv("MINIO_BUCKET", "csreport"),
    )
    p.add_argument("--dry-run", action="store_true", help="Print plan without uploading.")
    return p.parse_args()


def _last_day_of_month(year: int, month: int) -> date:
    """Return the last day of the given month."""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1).replace(day=1).__class__(year, month + 1, 1) - __import__(
        "datetime"
    ).timedelta(days=1)


def _upload_bytes(client, bucket: str, key: str, data: bytes, content_type: str) -> None:
    client.put_object(
        bucket,
        key,
        data=BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source_dir).expanduser().resolve()
    cutoff = date.fromisoformat(args.cutoff_date)

    if not source_dir.is_dir():
        logger.error("Source directory does not exist: %s", source_dir)
        return 1

    # Discover all JSONL files
    # Expected structure: run_date=YYYY-MM-DD/year=YYYY/month=MM/symbol=XXXX.jsonl
    run_date_re = re.compile(r"run_date=(\d{4}-\d{2}-\d{2})")
    year_re = re.compile(r"year=(\d{4})")
    month_re = re.compile(r"month=(\d{2})")
    symbol_re = re.compile(r"symbol=([A-Za-z0-9.\-]+)\.jsonl$")

    jsonl_files = sorted(source_dir.rglob("*.jsonl"))
    logger.info("Found %d JSONL files in %s", len(jsonl_files), source_dir)

    if not jsonl_files:
        logger.warning("No JSONL files found. Nothing to import.")
        return 0

    if args.dry_run:
        logger.info("DRY RUN — no files will be uploaded.")

    # Group by (year, month, symbol) for cursor creation
    # key: (year_str, month_str, symbol) -> list of (run_date_str, file_path)
    month_symbol_files: dict[tuple[str, str, str], list[tuple[str, Path]]] = {}

    for fp in jsonl_files:
        parts = str(fp)
        rd_m = run_date_re.search(parts)
        yr_m = year_re.search(parts)
        mo_m = month_re.search(parts)
        sy_m = symbol_re.search(fp.name)
        if not (rd_m and yr_m and mo_m and sy_m):
            logger.warning("Skipping unrecognised path: %s", fp)
            continue
        run_date_str = rd_m.group(1)
        year_str = yr_m.group(1)
        month_str = mo_m.group(1)
        symbol = sy_m.group(1)
        month_symbol_files.setdefault((year_str, month_str, symbol), []).append((run_date_str, fp))

    if not args.dry_run:
        from minio import Minio

        client = Minio(
            endpoint=args.minio_endpoint,
            access_key=args.minio_access_key,
            secret_key=args.minio_secret_key,
            secure=False,
        )
        bucket = args.minio_bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("Created bucket: %s", bucket)
    else:
        client = None
        bucket = args.minio_bucket

    uploaded = 0
    cursors_created = 0
    current_created = 0

    for (year_str, month_str, symbol), file_list in sorted(month_symbol_files.items()):
        year_int = int(year_str)
        month_int = int(month_str)
        month_start = date(year_int, month_int, 1)
        month_end = _last_day_of_month(year_int, month_int)

        # 1) Upload raw snapshot files
        for run_date_str, fp in file_list:
            raw_key = (
                f"raw/source_b/news/run_date={run_date_str}"
                f"/year={year_str}/month={month_str}"
                f"/symbol={symbol}.jsonl"
            )
            if args.dry_run:
                logger.info("[dry-run] would upload %s -> %s", fp.name, raw_key)
            else:
                data = fp.read_bytes()
                _upload_bytes(client, bucket, raw_key, data, "application/x-ndjson")
            uploaded += 1

        # 2) Upload news_current (merged view) — use the latest file as the merged view
        latest_file = file_list[-1][1]  # sorted, last = latest run_date
        current_key = (
            f"raw/source_b/news_current"
            f"/year={year_str}/month={month_str}"
            f"/symbol={symbol}.jsonl"
        )
        if not args.dry_run:
            data = latest_file.read_bytes()
            _upload_bytes(client, bucket, current_key, data, "application/x-ndjson")
        current_created += 1

        # 3) Create cursor — mark months before cutoff as closed
        is_closed = month_start < cutoff
        last_ingested = month_end if is_closed else min(month_end, date.today())
        cursor_payload = {
            "symbol": symbol,
            "month_start": month_start.isoformat(),
            "last_ingested_date": last_ingested.isoformat(),
            "is_closed": is_closed,
            "updated_at": datetime.utcnow().isoformat(),
        }
        cursor_key = (
            f"raw/source_b/news_cursor"
            f"/year={year_str}/month={month_str}"
            f"/symbol={symbol}.json"
        )
        if args.dry_run:
            if cursors_created < 3:
                logger.info("[dry-run] cursor %s closed=%s", cursor_key, is_closed)
        else:
            cursor_data = json.dumps(cursor_payload, ensure_ascii=False).encode("utf-8")
            _upload_bytes(client, bucket, cursor_key, cursor_data, "application/json")
        cursors_created += 1

    logger.info(
        "Import complete: raw_files=%d current_views=%d cursors=%d",
        uploaded,
        current_created,
        cursors_created,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
