from __future__ import annotations

"""Command-line parser utilities."""

import argparse
from datetime import datetime, timezone

ALLOWED_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "annual"}


def valid_date(value: str) -> str:
    """Validate date argument format as ``YYYY-MM-DD``."""
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        return dt.date().isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY-MM-DD."
        ) from exc


def parse_csv_lower_list(value: str) -> list[str]:
    """Parse comma-separated values into a lower-cased de-duplicated list."""
    if value is None:
        return []

    out: list[str] = []
    seen = set()
    for item in str(value).split(","):
        token = item.strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def build_parser() -> argparse.ArgumentParser:
    """Build and return the project CLI parser."""
    parser = argparse.ArgumentParser(
        description="CW1 pipeline skeleton (Team Pearson).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="config/conf.yaml",
        help="Path to YAML config relative to coursework_one/",
    )
    today_iso = datetime.now(timezone.utc).date().isoformat()
    parser.add_argument(
        "--run-date",
        required=False,
        default=today_iso,
        type=valid_date,
        help="Run date in YYYY-MM-DD (defaults to today, UTC).",
    )
    parser.add_argument(
        "--frequency",
        required=False,
        default=None,
        choices=sorted(ALLOWED_FREQUENCIES),
        help="Data frequency for the pipeline run (default from config).",
    )
    parser.add_argument(
        "--backfill-years",
        type=int,
        default=None,
        help="How many years of history to fetch (default from config).",
    )
    parser.add_argument(
        "--company-limit",
        type=int,
        default=None,
        help="Limit companies for debugging (default from config).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline without loading to storage (still runs transforms/quality).",
    )
    parser.add_argument(
        "--enabled-extractors",
        type=parse_csv_lower_list,
        default=None,
        help="Comma-separated extractors to run, e.g. source_a,source_b (default from config).",
    )
    parser.add_argument(
        "--index-mongo",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After successful main pipeline run, also build Mongo news index "
            "(disable with --no-index-mongo)."
        ),
    )
    return parser
