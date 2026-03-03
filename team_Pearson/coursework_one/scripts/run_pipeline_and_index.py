from __future__ import annotations

"""Pipeline orchestrator: run Main.py, then optionally build Mongo search index."""

import argparse
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import List

from modules.utils.env import load_dotenv_if_exists


def _build_main_cmd(args: argparse.Namespace) -> List[str]:
    """Build Main.py command from orchestrator arguments."""
    cmd = [
        sys.executable,
        "Main.py",
        "--run-date",
        args.run_date,
        "--frequency",
        args.frequency,
    ]
    if args.config:
        cmd.extend(["--config", args.config])
    if args.backfill_years is not None:
        cmd.extend(["--backfill-years", str(args.backfill_years)])
    if args.company_limit is not None:
        cmd.extend(["--company-limit", str(args.company_limit)])
    if args.enabled_extractors:
        cmd.extend(["--enabled-extractors", args.enabled_extractors])
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def _build_mongo_cmd(args: argparse.Namespace) -> List[str]:
    """Build index_news_to_mongo.py command from orchestrator arguments."""
    cmd = [
        sys.executable,
        "scripts/index_news_to_mongo.py",
        "--run-date",
        args.run_date,
    ]
    if args.config:
        cmd.extend(["--config", args.config])
    if args.mongo_db:
        cmd.extend(["--mongo-db", args.mongo_db])
    if args.mongo_collection:
        cmd.extend(["--collection", args.mongo_collection])
    if args.mongo_skip_indexes:
        cmd.append("--skip-indexes")
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI parser for pipeline + optional Mongo indexing."""
    parser = argparse.ArgumentParser(
        description=(
            "Run Main.py pipeline first; optionally build Mongo index from MinIO raw "
            "(best-effort, non-blocking)."
        )
    )
    parser.add_argument("--run-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--frequency", required=True, help="daily|weekly|monthly|quarterly|annual")
    parser.add_argument("--config", default="config/conf.yaml")
    parser.add_argument("--backfill-years", type=int, default=None)
    parser.add_argument("--company-limit", type=int, default=None)
    parser.add_argument("--enabled-extractors", default="")
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument(
        "--index-mongo",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After Main succeeds, run scripts/index_news_to_mongo.py (default: enabled).",
    )
    parser.add_argument("--mongo-db", default="", help="Mongo database name override.")
    parser.add_argument(
        "--mongo-collection",
        default="news_articles",
        help="Mongo collection name for indexed news.",
    )
    parser.add_argument(
        "--mongo-skip-indexes",
        action="store_true",
        help="Pass --skip-indexes to index_news_to_mongo.py.",
    )
    return parser


def main() -> int:
    """Run main pipeline first, then best-effort Mongo indexing."""
    args = build_parser().parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv_if_exists(project_root / ".env")

    main_cmd = _build_main_cmd(args)
    print("[orchestrator] main command: " + " ".join(main_cmd))
    main_result = subprocess.run(main_cmd, check=False)  # nosec B603
    if main_result.returncode != 0:
        print(f"[orchestrator] main failed rc={main_result.returncode}; skip mongo indexing")
        return int(main_result.returncode)

    if not args.index_mongo:
        print("[orchestrator] mongo indexing disabled (--no-index-mongo)")
        return 0

    mongo_cmd = _build_mongo_cmd(args)
    print("[orchestrator] mongo command: " + " ".join(mongo_cmd))
    mongo_result = subprocess.run(mongo_cmd, check=False)  # nosec B603
    if mongo_result.returncode != 0:
        print(
            f"[orchestrator] warning: mongo indexing failed rc={mongo_result.returncode}; "
            "pipeline remains successful"
        )
    else:
        print("[orchestrator] mongo indexing completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
