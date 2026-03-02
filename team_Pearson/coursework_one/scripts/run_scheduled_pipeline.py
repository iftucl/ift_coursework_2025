from __future__ import annotations

"""Run pipeline schedule wrapper in one entrypoint.

Typical usage with cron/launchd:
    poetry run python scripts/run_scheduled_pipeline.py
"""

import argparse
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List

from modules.utils.env import load_dotenv_if_exists


@dataclass
class RunSpec:
    frequency: str
    run_date: str


def _parse_run_date(raw: str | None) -> date:
    if raw:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    return datetime.now(timezone.utc).date()


def _build_run_specs(
    *,
    run_date: date,
    include_daily: bool,
    force_frequencies: List[str] | None,
) -> List[RunSpec]:
    if force_frequencies:
        return [RunSpec(frequency=f, run_date=run_date.isoformat()) for f in force_frequencies]

    specs: List[RunSpec] = []
    # Default schedule mode runs daily only.
    if include_daily:
        specs.append(RunSpec(frequency="daily", run_date=run_date.isoformat()))
    return specs


def _build_cmd(
    *,
    run_spec: RunSpec,
    backfill_years: int | None,
    company_limit: int | None,
    dry_run: bool,
    index_mongo: bool,
) -> List[str]:
    cmd = [
        sys.executable,
        "scripts/run_pipeline_and_index.py",
        "--run-date",
        run_spec.run_date,
        "--frequency",
        run_spec.frequency,
    ]
    if backfill_years is not None:
        cmd.extend(["--backfill-years", str(backfill_years)])
    if company_limit is not None:
        cmd.extend(["--company-limit", str(company_limit)])
    if dry_run:
        cmd.append("--dry-run")
    if index_mongo:
        cmd.append("--index-mongo")
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Calendar-triggered runner for Main.py")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD; default is today (UTC).")
    parser.add_argument(
        "--only",
        default="",
        help=(
            "Comma-separated frequencies to force (daily,monthly,quarterly). "
            "Default schedule mode runs daily only."
        ),
    )
    parser.add_argument(
        "--skip-daily",
        action="store_true",
        help="Disable daily trigger in automatic mode.",
    )
    parser.add_argument("--backfill-years", type=int, default=None)
    parser.add_argument("--company-limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--index-mongo",
        action="store_true",
        help="Also run Mongo news indexing after each successful Main.py run (best-effort).",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Print would-run commands without executing.",
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv_if_exists(project_root / ".env")

    run_date = _parse_run_date(args.run_date)
    forced = [x.strip().lower() for x in args.only.split(",") if x.strip()]
    valid = {"daily", "monthly", "quarterly"}
    invalid = [x for x in forced if x not in valid]
    if invalid:
        raise SystemExit(f"Unsupported frequencies in --only: {invalid}")

    specs = _build_run_specs(
        run_date=run_date,
        include_daily=not args.skip_daily,
        force_frequencies=forced or None,
    )
    if not specs:
        print(f"No frequency scheduled for run_date={run_date.isoformat()}")
        return 0

    for spec in specs:
        cmd = _build_cmd(
            run_spec=spec,
            backfill_years=args.backfill_years,
            company_limit=args.company_limit,
            dry_run=args.dry_run,
            index_mongo=bool(args.index_mongo),
        )
        print(f"[scheduled] frequency={spec.frequency} run_date={spec.run_date}")
        print("[cmd] " + " ".join(cmd))
        if args.plan_only:
            continue
        subprocess.run(cmd, check=True)  # nosec B603
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
